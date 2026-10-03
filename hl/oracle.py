"""
What a one-direction Hyperliquid perp trade costs, measured now, at size.

WHY A DIRECTIONAL MODEL
-----------------------
The Binance oracle priced a funding carry: two legs, delta-neutral, paid by
funding. Most trading agents do not trade that way. They go long or short one
perp and hope the price moves. That trade has no edge the oracle can measure,
because the edge is the agent's opinion. What the oracle can measure is the
hurdle: how far the price has to move in the agent's favour before the trade
has paid for itself. That number is the product.

    break-even move = entry crossing + exit crossing
                    + 2 x taker fee + 2 x builder fee
                    + adverse funding over the hold

Every term is per unit of notional, in bps.

entry crossing   distance from mid to the VWAP of walking the book for the
                 real size. Measured.
exit crossing    the same walk on the other side, for the same size, on the
                 book as it stands now. ASSUMED: the exit book looks like
                 today's. Reported as an assumption, not a measurement.
fees             the account's taker rate, HIP-3 scaled. See venue.py.
builder fee      what the agent's framework charges per fill. This is the term
                 that a live Senpi review (senpi-skills PR #800) found was
                 charged and never read: a +$410.14 headline, far less net.
funding          hourly rate x hours held. Charged when it runs against the
                 position, never credited when it runs for it, because the rate
                 can flip within the hold. Same rule as the Binance oracle's
                 floored basis: a favourable number is reported, not banked.

THE TEST
--------
If the caller states the move it expects (expected_move_bps), the trade must
clear break-even plus MIN_EDGE_BPS. If it does not, the trade is held to
MAX_COST_BPS, which catches broken books rather than judging the idea.

Public REST only. Holds no keys and cannot place an order.
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hl import band, info, sessions, venue

getcontext().prec = 28

with open(os.path.join(HERE, "xyz_registry.json"), encoding="utf-8") as _f:
    XYZ_REGISTRY = json.load(_f)

BPS = Decimal("10000")
ZERO = Decimal("0")
SCHEMA_VERSION = "2.0.0"

# POLICY numbers, not measurements. Same values as the Binance oracle so the
# two cannot disagree about what "too expensive" means.
TTL_SECONDS = 10
MIN_EDGE_BPS = Decimal("10")
MAX_COST_BPS = Decimal("50")

# ASSUMED hold when the caller does not say. Funding is hourly on Hyperliquid,
# so this is in hours, not Binance's 8-hour settlements.
DEFAULT_HOLD_HOURS = 8

# Hyperliquid caps builder fees on perps at 0.1% (10 bps) per fill.
MAX_BUILDER_FEE_BPS = Decimal("10")


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _f(d, places=2):
    return float(round(d, places))


def walk(levels, qty):
    """(vwap, worst_px, cover) for taking qty off one side. vwap None if it cannot fill."""
    need, spend, got, total, worst = qty, ZERO, ZERO, ZERO, None
    for px, q in levels:
        total += q
        if need > 0:
            take = min(need, q)
            spend += take * px
            got += take
            need -= take
            worst = px
    cover = total / qty if qty > 0 else ZERO
    if need > 0 or got <= 0:
        return None, None, cover
    return spend / got, worst, cover


def book(coin):
    t0 = time.time()
    raw = info.l2_book(coin)
    latency_ms = int((time.time() - t0) * 1000)
    bids = [(Decimal(l["px"]), Decimal(l["sz"])) for l in raw["levels"][0]]
    asks = [(Decimal(l["px"]), Decimal(l["sz"])) for l in raw["levels"][1]]
    return bids, asks, latency_ms


def builder_fee_bps(declared_bps=None, user=None, builder=None):
    """The builder fee to charge, and where the number came from.

    If both addresses are given, the approved maximum is read from the
    exchange (maxBuilderFee, in tenths of a bp) and used as the bound, because
    that is what the framework is allowed to take. Otherwise the declared
    figure is used and labelled declared.
    """
    if user and builder:
        tenths = info.q({"type": "maxBuilderFee", "user": user, "builder": builder})
        return Decimal(tenths) / 10, "approved maximum, read from exchange"
    if declared_bps is not None:
        return Decimal(str(declared_bps)), "declared by caller"
    return ZERO, "none declared"


def price_source(spec, now=None):
    """Who sets the price on this market right now: the real exchange or the book.

    Main-dex crypto trades 24/7 against itself and has no external session.
    xyz markets follow the schedule in xyz_registry.json. Other HIP-3 dexes
    publish no schedule this module can read, so they count as unknown.
    """
    if not spec["hip3"]:
        return None
    coin = spec["coin"]
    entry = XYZ_REGISTRY["markets"].get(coin) if spec["dex"] == "xyz" else None
    schedule = entry["schedule"] if entry else "unknown"
    state, why, eastern = sessions.session(schedule, now)
    out = {"schedule": schedule, "session": state, "why": why, "eastern_time": eastern,
           "registry": XYZ_REGISTRY["source"] if entry else "no published schedule found"}
    if entry and entry.get("discovery_bound") and spec["max_leverage"]:
        implied = 1 / Decimal(spec["max_leverage"])
        if abs(Decimal(str(entry["discovery_bound"])) - implied) > Decimal("0.0001"):
            out["bound_note"] = (f"published bound {entry['discovery_bound']} differs from "
                                 f"1/maxLeverage {float(round(implied, 4))}; published value used")
    if state == sessions.INTERNAL and entry:
        out["band"] = band.discovery_band(coin, entry, spec["mark_px"], now)
    return out


def evaluate_perp(coin, notional_usd, side, hold_hours=None, expected_move_bps=None,
                  builder_fee=None, builder=None, user=None, accept_internal_price=False):
    measured_at = _now()
    side = str(side or "").upper().strip()
    hold = Decimal(str(hold_hours if hold_hours is not None else DEFAULT_HOLD_HOURS))

    def refuse(reason, **extra):
        out = {
            "schema_version": SCHEMA_VERSION,
            "decision": "REJECT",
            "reason": reason,
            "venue": "hyperliquid",
            "coin": coin,
            "side": side or None,
            "strategy": "perp_entry",
            "measured_at": _iso(measured_at),
            "expires_at": _iso(measured_at + timedelta(seconds=TTL_SECONDS)),
            "ttl_seconds": TTL_SECONDS,
            "max_notional_usd": 0.0,
        }
        out.update(extra)
        return out

    if side not in ("BUY", "SELL"):
        return refuse("side_required", detail="Pass side=BUY (long) or side=SELL (short).")
    is_buy = side == "BUY"

    try:
        spec = venue.market(coin)
        fees = venue.perp_fee_bps(spec, user)
        bfee, bfee_source = builder_fee_bps(builder_fee, user, builder)
        bids, asks, latency_ms = book(coin)
        # The verdict describes the book at the moment it was read, so its
        # lifetime starts here, not when the request arrived.
        measured_at = _now()
    except KeyError as e:
        return refuse("unknown_market", detail=str(e))
    except Exception as e:  # unknown cost is not acceptable cost
        return refuse("pricing_failed", detail=f"{type(e).__name__}: {e}")

    if spec["is_delisted"]:
        return refuse("delisted", detail="Market is delisted; orders would be rejected.")
    source = price_source(spec)
    if source and source["session"] == sessions.INTERNAL and not accept_internal_price:
        return refuse(
            "internal_price_session",
            detail=f"{source['why']} ({source['eastern_time']}). The price is set by this "
                   "market's own order book, not the underlying exchange, so what the "
                   "position is worth at reopen cannot be measured. Pass "
                   "accept_internal_price=true to trade anyway.",
            price_source=source)
    if bfee > MAX_BUILDER_FEE_BPS:
        return refuse("builder_fee_above_cap",
                      detail=f"{bfee} bps exceeds the {MAX_BUILDER_FEE_BPS} bps perp cap.")
    if not bids or not asks:
        return refuse("empty_book")

    mid = (bids[0][0] + asks[0][0]) / 2
    qty = venue.round_size(spec, Decimal(str(notional_usd)) / mid)
    notional = qty * mid
    if notional < venue.MIN_NOTIONAL_USD:
        return refuse("below_venue_minimum",
                      detail=f"${_f(notional)} after size rounding; Hyperliquid's minimum "
                             f"order value is ${venue.MIN_NOTIONAL_USD}.",
                      min_notional_usd=float(venue.MIN_NOTIONAL_USD))

    entry_side, exit_side = (asks, bids) if is_buy else (bids, asks)
    entry_vwap, entry_worst, cover = walk(entry_side, qty)
    exit_vwap, _, _ = walk(exit_side, qty)
    if entry_vwap is None or exit_vwap is None:
        return refuse("insufficient_depth",
                      detail=f"20 visible levels cover {_f(cover, 2)}x the order.",
                      depth_cover_x=_f(cover, 2))

    entry_cross = abs(entry_vwap - mid) / mid * BPS
    exit_cross = abs(exit_vwap - mid) / mid * BPS
    fee_total = 2 * fees["taker_bps"]
    builder_total = 2 * bfee
    # Positive funding: longs pay shorts. Signed so that positive means "you pay".
    funding_signed = spec["funding_hourly"] * hold * BPS * (1 if is_buy else -1)
    funding_cost = max(ZERO, funding_signed)
    top_cross = abs(entry_side[0][0] - mid) / mid * BPS

    total = entry_cross + exit_cross + fee_total + builder_total + funding_cost

    result = {
        "schema_version": SCHEMA_VERSION,
        "venue": "hyperliquid",
        "coin": coin,
        "dex": spec["dex"],
        "strategy": "perp_entry",
        "side": side,
        "measured_at": _iso(measured_at),
        "expires_at": _iso(measured_at + timedelta(seconds=TTL_SECONDS)),
        "ttl_seconds": TTL_SECONDS,
        "size": {
            "requested_notional_usd": float(notional_usd),
            "qty": str(qty),
            "priced_notional_usd": _f(notional, 2),
            "depth_cover_x": _f(cover, 1),
        },
        "cost_bps": {
            "entry_crossing": _f(entry_cross),
            "exit_crossing": _f(exit_cross),
            "fees_round_trip": _f(fee_total),
            "builder_fee_round_trip": _f(builder_total),
            "funding_over_hold": _f(funding_cost),
            "total": _f(total),
        },
        "break_even_move_bps": _f(total),
        "evidence": {
            "mid": str(mid),
            "entry_vwap": str(entry_vwap),
            "exit_vwap": str(exit_vwap),
            "depth_impact_bps": _f(entry_cross - top_cross),
            "taker_fee_bps": _f(fees["taker_bps"], 3),
            "fee_basis": f"{fees['fee_source']}; base {_f(fees['base_taker_bps'], 3)} bps "
                         f"x HIP-3 {fees['hip3_scale']} x growth mode {fees['growth_mode_scale']}"
                         f" x (1 - referral {fees['referral_discount']})",
            "builder_fee_bps": _f(bfee, 1),
            "builder_fee_source": bfee_source,
            "funding_hourly": str(spec["funding_hourly"]),
            "funding_signed_bps": _f(funding_signed),
            "funding_note": "charged when adverse, reported but not credited when favourable",
            "hold_hours": float(hold),
            "hold_source": "caller" if hold_hours is not None else "ASSUMED default",
            "exit_crossing_basis": "ASSUMED: exit book resembles the current book",
            "only_isolated_margin": spec["only_isolated"],
            "price_source": source,
            "internal_price_accepted": bool(source and source["session"] == sessions.INTERNAL),
            "book_levels": 20,
            "quote_latency_ms": latency_ms,
        },
    }

    if expected_move_bps is not None:
        need = total + MIN_EDGE_BPS
        approved = Decimal(str(expected_move_bps)) >= need
        result["test"] = {"expected_move_bps": float(expected_move_bps),
                          "required_bps": _f(need), "min_edge_bps": _f(MIN_EDGE_BPS)}
        reason_ok, reason_bad = "edge_clears_cost", "edge_below_cost"
        shortfall = need - Decimal(str(expected_move_bps))
    else:
        approved = total <= MAX_COST_BPS
        result["test"] = {"max_cost_bps": _f(MAX_COST_BPS)}
        reason_ok, reason_bad = "cost_within_ceiling", "cost_exceeds_ceiling"
        shortfall = total - MAX_COST_BPS

    result["decision"] = "APPROVE" if approved else "REJECT"
    result["reason"] = reason_ok if approved else reason_bad
    result["max_notional_usd"] = _f(notional, 2) if approved else 0.0
    if approved:
        # The gateway sends one IOC limit at this price. Anything worse than the
        # deepest level this verdict priced cannot fill, so the fill cannot cost
        # more than the verdict says.
        limit_px = venue.round_price(spec, entry_worst, is_buy)
        result["authorization"] = {
            "venue": "hyperliquid",
            "coin": coin,
            "asset_id": spec["asset_id"],
            "is_buy": is_buy,
            "qty": str(qty),
            "limit_px": str(limit_px),
            "tif": "Ioc",
            "max_entry_crossing_bps": _f(abs(limit_px - mid) / mid * BPS),
            "expires_at": result["expires_at"],
        }
    else:
        result["shortfall_bps"] = _f(shortfall)
    return result


if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser(description="Price a Hyperliquid perp trade.")
    p.add_argument("coin")
    p.add_argument("notional", type=float)
    p.add_argument("side", choices=["BUY", "SELL", "buy", "sell"])
    p.add_argument("--hold-hours", type=float)
    p.add_argument("--expected-move-bps", type=float)
    p.add_argument("--builder-fee-bps", type=float)
    p.add_argument("--accept-internal-price", action="store_true")
    a = p.parse_args()
    print(json.dumps(evaluate_perp(a.coin, a.notional, a.side, a.hold_hours,
                                   a.expected_move_bps, a.builder_fee_bps,
                                   accept_internal_price=a.accept_internal_price), indent=2))
