"""
The cost engine, separated from the scanner so a tool call can reach it.

scanner.py prices a trade against a constant. This prices it against the book
that exists at the moment of the call, at the size actually being traded, and
returns a decision object with the workings attached.

WHY THIS EXISTS RATHER THAN A CONSTANT
--------------------------------------
The paired run of 2026-09-05 06:33 UTC is the argument. The executor measured
a 13.55 bps entry basis at plan time, carried 19.32 bps in the constant, and
paid 30.50 bps on the fill, all inside one minute. A constant is the wrong
shape for a quantity that moves that fast. The only honest way to know it is
to measure it at the moment of trading.

THE PRICING MODEL, AND WHY THE OLD ONE WAS WRONG
------------------------------------------------
The executor predicted the price cost of a round trip as the two spreads it
crosses, 6.77 bps. Realised was 30.50. That is not a calibration error, it is
the wrong model, and the fills say so:

    open    spot BUY  0.02962      perp SELL 0.02953     basis +30.43 bps
    close   spot SELL 0.02954      perp BUY  0.02954     basis   0.00 bps
                                                         ----------------
    entry basis + exit basis                                   30.43 bps
    realised price term, from the reconciliation                30.50 bps

So the round trip costs the basis you enter at plus the basis you exit at,
not the spreads. The two models only agree when the basis at the close equals
the basis at the open. It did not: the venues were 9 ticks apart going in and
level coming out.

That has a consequence worth stating, because it is the whole reason a hedge
can be sized correctly and still lose. Opening a delta-neutral hedge into a
wide positive basis means being long the expensive venue and short the cheap
one. If the dislocation persists you give the basis back on the exit and pay
only spreads. If it converges you eat all of it. Convergence is the direction
a basis tends to move, so the conservative assumption is that it reverts, and
this module prices it that way:

    price cost = entry basis (measured now, at size, floored at zero)
               + exit spread (both venues, half each, at a basis of zero)

Erring conservative can only make the oracle refuse more. It can never
manufacture a trade. That is the same rule scanner.py already follows, and it
is why the entry basis is floored: a basis that happens to point the right way
is reported in evidence but not banked as a discount, because a dislocation
can widen as easily as it reverts and a favourable one must never be allowed
to argue a trade into existence.

EVERYTHING IS MEASURED AT SIZE
------------------------------
Top of book is not a price for an order, it is a price for the first slice of
one. Every figure below walks the actual depth ladder for the actual quantity
and returns the VWAP, so a thin book shows up as a worse price rather than as
a footnote. The gap between the top-of-book number and the at-size number is
reported separately as depth impact.

Public REST only. No auth, no keys, no MCP. This module reads books and does
arithmetic; it cannot place an order and holds no credentials.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext

import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from execution import venue
except ImportError:
    import venue

getcontext().prec = 28

BPS = Decimal("10000")
ZERO = Decimal("0")

FAPI = venue.FAPI
SAPI = venue.SAPI

TRADES_PATH = os.path.join(ROOT, "evidence", "trades.jsonl")
if not os.path.exists(TRADES_PATH) and os.path.exists(os.path.join(HERE, "trades.jsonl")):
    TRADES_PATH = os.path.join(HERE, "trades.jsonl")

# How many ladder levels to pull. 100 covers several hundred dollars of depth
# on the thin symbols this account can afford, and costs weight 5 per venue.
DEPTH_LIMIT = 100

# How long a quote stays good. This is a POLICY choice, not a measurement, and
# it is deliberately short: the basis on the one run we have moved from 13.55
# to 30.50 bps in under a minute. A decision object older than this describes
# a book that no longer exists.
TTL_SECONDS = 10

# Settlements the carry is underwritten over, and the profit required above
# cost before this is called a trade. Both match scanner.py, which is the
# point: the tool and the scanner must not be able to disagree.
HOLD_PERIODS = 3
MIN_EDGE_BPS = Decimal("10")

# The ceiling a single-leg conversion has to come in under. A conversion earns
# nothing, so there is no edge for it to clear and MIN_EDGE_BPS does not apply;
# what it can still do is be a bad fill. This is the line between "you asked
# for this trade and it costs what it costs" and "this book is broken". It is a
# POLICY number like TTL_SECONDS, not a measurement, and it is set well above
# the 7.5 bps fee floor so that it catches thin books rather than ordinary ones.
MAX_COST_BPS = Decimal("50")

# Funding must have held its sign this many prints running.
PERSISTENCE = 3

SCHEMA_VERSION = "1.0.0"


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def bps(part, whole):
    if whole <= 0:
        return Decimal("99999")
    return part / whole * BPS


# --- Depth ------------------------------------------------------------

def depth(symbol, market, limit=DEPTH_LIMIT):
    """One side's ladder, as Decimals. market is 'spot' or 'futures'."""
    if market == "spot":
        raw = venue.http_get(f"{SAPI}/api/v3/depth",
                             {"symbol": symbol, "limit": limit})
    else:
        raw = venue.http_get(f"{FAPI}/fapi/v1/depth",
                             {"symbol": symbol, "limit": limit})
    return (
        [(Decimal(p), Decimal(q)) for p, q in raw.get("bids", [])],
        [(Decimal(p), Decimal(q)) for p, q in raw.get("asks", [])],
    )


def walk(levels, qty):
    """
    VWAP of taking `qty` off one side of a ladder.

    Returns (vwap, cover) where cover is how many multiples of qty the visible
    ladder holds. None if the book cannot fill the order at all, because a
    price for a quantity the market will not supply is not a price.
    """
    need, spend, got, total = qty, ZERO, ZERO, ZERO
    for px, q in levels:
        total += q
        if need > 0:
            take = min(need, q)
            spend += take * px
            got += take
            need -= take
    if need > 0 or got <= 0:
        return None, (total / qty if qty > 0 else ZERO)
    return spend / got, total / qty


# --- Pricing ----------------------------------------------------------

def price_hedge(symbol, notional_usdt, spot_spec, fut_spec):
    """
    What a delta-neutral round trip on `symbol` costs right now, at this size.

    Sizes the way executor.py sizes: the futures leg first, because it carries
    the coarser minimum, then the spot leg truncated to the spot step. The
    residual that truncation leaves is priced as a cost rather than mentioned
    as a caveat.
    """
    t0 = time.time()
    s_bids, s_asks = depth(symbol, "spot")
    f_bids, f_asks = depth(symbol, "futures")
    latency_ms = int((time.time() - t0) * 1000)

    if not (s_bids and s_asks and f_bids and f_asks):
        return None, "no_two_sided_market"

    s_ask_top, f_bid_top = s_asks[0][0], f_bids[0][0]
    s_bid_top, f_ask_top = s_bids[0][0], f_asks[0][0]
    ref = (s_ask_top + f_bid_top) / 2
    if ref <= 0:
        return None, "no_two_sided_market"

    # Size the futures leg first, exactly as the executor will.
    target_qty = Decimal(str(notional_usdt)) / f_bid_top
    f_min = venue.ceil_step(
        max(fut_spec.min_qty, fut_spec.min_notional / f_bid_top), fut_spec.step)
    s_min = venue.ceil_step(
        max(spot_spec.min_qty, spot_spec.min_notional / s_ask_top), spot_spec.step)
    q_min = venue.ceil_step(max(f_min, s_min), fut_spec.step)

    fut_qty = venue.floor_step(target_qty, fut_spec.step)
    scaled_up = False
    if fut_qty < q_min:
        fut_qty, scaled_up = q_min, True
    spot_qty = venue.floor_step(fut_qty, spot_spec.step)
    if spot_qty <= 0 or spot_qty * s_ask_top < spot_spec.min_notional:
        return None, "below_min_notional"

    # Four sides, four walks. Open lifts the spot ask and hits the futures
    # bid; close does the reverse. All four have to hold the size.
    s_ask_vwap, s_ask_cover = walk(s_asks, spot_qty)
    s_bid_vwap, s_bid_cover = walk(s_bids, spot_qty)
    f_bid_vwap, f_bid_cover = walk(f_bids, fut_qty)
    f_ask_vwap, f_ask_cover = walk(f_asks, fut_qty)
    cover = min(s_ask_cover, s_bid_cover, f_bid_cover, f_ask_cover)
    if None in (s_ask_vwap, s_bid_vwap, f_bid_vwap, f_ask_vwap):
        return None, "insufficient_depth"

    # The basis being locked in, at size. Positive means the long leg is the
    # expensive one and the hedge starts underwater.
    entry_basis = bps(s_ask_vwap - f_bid_vwap, ref)

    # A negative basis means spot is the cheap venue and the hedge starts
    # ahead. That is a real credit if the basis reverts, and it is reported,
    # but it is not banked. The rule this module works to is that erring
    # conservative can only ever make it refuse more, and a favourable basis
    # counted as a discount would break that: it would let a dislocation that
    # happens to point the right way argue a trade into existence. It can
    # also widen instead of reverting. So the charge is floored at zero and
    # the measured value goes into evidence.
    entry_charged = max(ZERO, entry_basis)

    # What the exit costs if the basis reverts to zero, which is the
    # conservative case: half of each spread, crossed at size.
    exit_spread = bps(
        (s_ask_vwap - s_bid_vwap) / 2 + (f_ask_vwap - f_bid_vwap) / 2, ref)

    # Same two terms priced off top of book alone. The difference is what
    # trading at size actually costs, and it is the honest uncertainty term:
    # it is measured, not assumed.
    top_entry = max(ZERO, bps(s_ask_top - f_bid_top, ref))
    top_exit = bps(
        (s_ask_top - s_bid_top) / 2 + (f_ask_top - f_bid_top) / 2, ref)
    depth_impact = (entry_charged + exit_spread) - (top_entry + top_exit)

    # Truncation leaves the futures leg larger than the spot leg. That excess
    # is unhedged, and it is charged here rather than disclosed in a footnote.
    lot_residual = fut_qty - spot_qty
    lot_residual_usd = lot_residual * s_ask_vwap

    fees = (venue.SPOT_TAKER * 2 + venue.FUT_TAKER * 2) * BPS
    notional = fut_qty * f_bid_vwap
    lot_residual_bps = bps(lot_residual_usd, notional)

    total = fees + entry_charged + exit_spread + lot_residual_bps

    return {
        "fut_qty": fut_qty,
        "spot_qty": spot_qty,
        "notional": notional,
        "scaled_up": scaled_up,
        "cover": cover,
        "latency_ms": latency_ms,
        "cost": {
            "fees_bps": fees,
            "entry_basis_bps": entry_charged,
            "exit_spread_bps": exit_spread,
            "lot_residual_bps": lot_residual_bps,
            "total_bps": total,
        },
        "entry_basis_measured_bps": entry_basis,
        "depth_impact_bps": depth_impact,
        "lot_residual": lot_residual,
        "lot_residual_usd": lot_residual_usd,
        "quotes": {
            "spot_ask_vwap": s_ask_vwap, "spot_bid_vwap": s_bid_vwap,
            "fut_bid_vwap": f_bid_vwap, "fut_ask_vwap": f_ask_vwap,
            "spot_ask_top": s_ask_top, "spot_bid_top": s_bid_top,
            "fut_bid_top": f_bid_top, "fut_ask_top": f_ask_top,
        },
    }, None


def price_conversion(symbol, notional_usdt, side, spot_spec):
    """
    What one spot crossing costs right now, at this size. No second leg.

    This is a different trade from the one price_hedge() prices, and it is
    priced by a different function rather than by passing the hedge model a
    flag, because three of that model's four cost terms do not exist here:

      entry basis    there is no second venue to be dislocated from
      exit spread    a conversion is not a round trip; you are not coming back
      lot residual   nothing is left unhedged, because nothing was hedged

    Those terms are omitted from the result, not set to zero. A zero would be
    a claim that the term was measured and found to be nil, which is a
    different and false statement.

    What remains is the fee and the crossing. The crossing is charged
    directionally: the distance from mid to the VWAP actually paid, at size,
    rather than half the spread. Those coincide only on a symmetric book, and
    the honest number is the one you pay.
    """
    t0 = time.time()
    bids, asks = depth(symbol, "spot")
    latency_ms = int((time.time() - t0) * 1000)

    if not (bids and asks):
        return None, "no_two_sided_market"

    ask_top, bid_top = asks[0][0], bids[0][0]
    ref = (ask_top + bid_top) / 2
    if ref <= 0:
        return None, "no_two_sided_market"

    # Size against the side being crossed, then respect the venue's filters.
    # A request under the minimum is scaled up rather than quietly refused,
    # and the result says so: on BNBUSDT a 5 USDT buy is really 5.22, because
    # 5 truncates to 0.006 BNB and the exchange will not take it.
    cross_top = ask_top if side == "BUY" else bid_top
    qty = venue.floor_step(Decimal(str(notional_usdt)) / cross_top, spot_spec.step)
    q_min = venue.ceil_step(
        max(spot_spec.min_qty, spot_spec.min_notional / cross_top), spot_spec.step)
    scaled_up = False
    if qty < q_min:
        qty, scaled_up = q_min, True
    if qty <= 0:
        return None, "below_min_notional"

    # Both sides are walked even though only one is crossed: the untraded side
    # is what makes the crossing cost measurable against a real mid.
    ask_vwap, ask_cover = walk(asks, qty)
    bid_vwap, bid_cover = walk(bids, qty)
    if ask_vwap is None or bid_vwap is None:
        return None, "insufficient_depth"

    cross_vwap = ask_vwap if side == "BUY" else bid_vwap
    slip = (cross_vwap - ref) if side == "BUY" else (ref - cross_vwap)
    spread_bps = bps(slip, ref)

    top_slip = (ask_top - ref) if side == "BUY" else (ref - bid_top)
    depth_impact = spread_bps - bps(top_slip, ref)

    # One crossing, one fee. The hedge pays this four times; this pays it once.
    fees = venue.SPOT_TAKER * BPS
    notional = qty * cross_vwap

    return {
        "side": side,
        "qty": qty,
        "notional": notional,
        "scaled_up": scaled_up,
        "cover": min(ask_cover, bid_cover),
        "latency_ms": latency_ms,
        "cost": {
            "fees_bps": fees,
            "spread_bps": spread_bps,
            "total_bps": fees + spread_bps,
        },
        "depth_impact_bps": depth_impact,
        "quotes": {
            "ask_vwap": ask_vwap, "bid_vwap": bid_vwap,
            "cross_vwap": cross_vwap,
            "ask_top": ask_top, "bid_top": bid_top, "mid": ref,
        },
    }, None


# --- Funding ----------------------------------------------------------

def funding_outlook(symbol, hold_periods=HOLD_PERIODS):
    """Current funding, hours to the next settlement, and sign persistence."""
    rows = venue.http_get(f"{FAPI}/fapi/v1/premiumIndex", {"symbol": symbol})
    row = rows[0] if isinstance(rows, list) else rows
    rate = Decimal(str(row.get("lastFundingRate") or "0"))
    hours = (int(row["nextFundingTime"]) - int(time.time() * 1000)) / 3_600_000

    hist = venue.http_get(f"{FAPI}/fapi/v1/fundingRate",
                          {"symbol": symbol, "limit": PERSISTENCE})
    sign = 1 if rate > 0 else -1
    persistent = (
        len(hist) >= PERSISTENCE
        and all((1 if Decimal(str(h["fundingRate"])) > 0 else -1) == sign
                for h in hist)
    )
    return {
        "rate_bps": rate * BPS,
        "gross_bps": rate * BPS * hold_periods,
        "hours_to_next": hours,
        "persistent": persistent,
        "prints": [str(Decimal(str(h["fundingRate"])) * BPS) for h in hist],
    }


# --- Calibration ------------------------------------------------------

def calibration():
    """
    How wrong this model has been on real fills, read from the trade log.

    Compares the entry basis measured at plan time against the price term the
    reconciliation actually charged. It is a record of executions, not a
    distribution: with a handful of runs there is no standard deviation to
    quote and none is quoted. `n` is returned so the caller can see exactly
    how much weight the number deserves.
    """
    if not os.path.exists(TRADES_PATH):
        return {"n": 0, "mean_gap_bps": ZERO, "gaps_bps": []}

    planned, gaps = None, []
    with open(TRADES_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event") == "plan":
                planned = rec.get("predicted", {})
            elif rec.get("event") == "report" and planned:
                try:
                    fees = Decimal(planned["fees_bps"])
                    eb = Decimal(planned["entry_basis_bps"])
                    realised_price = Decimal(rec["realised_bps"]) - fees
                    gaps.append(realised_price - eb)
                except (KeyError, ArithmeticError):
                    pass
                planned = None

    mean = sum(gaps) / len(gaps) if gaps else ZERO
    return {"n": len(gaps), "mean_gap_bps": mean, "gaps_bps": gaps}


# --- The decision -----------------------------------------------------

def _f(d, places=2):
    return float(round(Decimal(d), places))


def _evaluate_carry(symbol, notional_usdt=5.0, hold_periods=HOLD_PERIODS,
                    min_edge_bps=None, refresh=False):
    """
    Price a proposed delta-neutral funding carry and return a verdict.

    The verdict carries its own arithmetic. A refusal that cannot be checked
    is just an opinion, and an agent has no reason to respect one.

    Reached through evaluate() below, which picks between this and the
    single-leg pricer. The body is deliberately untouched by that split:
    verify_conversion.py pins its output byte for byte against a baseline
    captured before the refactor, because the README quotes these exact
    figures as evidence.
    """
    symbol = symbol.upper().strip()
    min_edge = Decimal(str(min_edge_bps)) if min_edge_bps is not None else MIN_EDGE_BPS
    measured_at = _now()

    def refuse(reason, **extra):
        out = {
            "schema_version": SCHEMA_VERSION,
            "decision": "REJECT",
            "reason": reason,
            "symbol": symbol,
            "strategy": "funding_carry_delta_neutral",
            "measured_at": _iso(measured_at),
            "expires_at": _iso(measured_at + timedelta(seconds=TTL_SECONDS)),
            "ttl_seconds": TTL_SECONDS,
            "max_notional_usdt": 0.0,
        }
        out.update(extra)
        return out

    spot, _ = venue.spot_specs(refresh=refresh)
    fut, _ = venue.futures_specs(refresh=refresh)
    if symbol not in fut:
        return refuse("no_futures_market")
    if symbol not in spot:
        return refuse("no_spot_market",
                      detail="No USDT spot listing, so the long leg cannot be built.")
    if spot[symbol].base != fut[symbol].base:
        # A matching symbol string is not proof of a matching unit. The 1000X
        # contracts are a different base asset from their spot listing, and
        # hedging one with the other is not a hedge.
        return refuse("base_asset_mismatch",
                      detail=f"spot base {spot[symbol].base}, "
                             f"futures base {fut[symbol].base}")

    priced, err = price_hedge(symbol, notional_usdt, spot[symbol], fut[symbol])
    if priced is None:
        return refuse(err)

    fund = funding_outlook(symbol, hold_periods)
    cal = calibration()

    cost = priced["cost"]
    # The buffer is the depth impact we just measured plus however much this
    # model has under-charged on real fills. Both are observed. Neither is a
    # confidence interval, and calling it one with this many executions
    # behind it would be dressing up an anecdote.
    buffer_bps = max(ZERO, priced["depth_impact_bps"]) + max(ZERO, cal["mean_gap_bps"])
    net = fund["gross_bps"] - cost["total_bps"]
    risk_adjusted = net - buffer_bps

    result = {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "strategy": "funding_carry_delta_neutral",
        "measured_at": _iso(measured_at),
        "expires_at": _iso(measured_at + timedelta(seconds=TTL_SECONDS)),
        "ttl_seconds": TTL_SECONDS,
        "size": {
            "requested_notional_usdt": float(notional_usdt),
            "futures_qty": venue.fmt_qty(priced["fut_qty"], fut[symbol].step),
            "spot_qty": venue.fmt_qty(priced["spot_qty"], spot[symbol].step),
            "priced_notional_usdt": _f(priced["notional"], 4),
            "scaled_to_venue_minimum": priced["scaled_up"],
            "lot_residual_base": venue.fmt_qty(priced["lot_residual"], spot[symbol].step),
            "lot_residual_usdt": _f(priced["lot_residual_usd"], 6),
            "depth_cover_x": _f(priced["cover"], 1),
        },
        "cost_bps": {
            "fees": _f(cost["fees_bps"]),
            "entry_basis": _f(cost["entry_basis_bps"]),
            "exit_spread": _f(cost["exit_spread_bps"]),
            "lot_residual": _f(cost["lot_residual_bps"]),
            "total": _f(cost["total_bps"]),
        },
        "edge_bps": {
            "funding_per_settlement": _f(fund["rate_bps"], 3),
            "hold_periods": hold_periods,
            "gross_funding": _f(fund["gross_bps"]),
            "net": _f(net),
            "risk_adjusted": _f(risk_adjusted),
            "min_edge_required": _f(min_edge),
        },
        "uncertainty_bps": {
            "depth_impact": _f(priced["depth_impact_bps"]),
            "calibration_gap": _f(cal["mean_gap_bps"]),
            "calibration_n": cal["n"],
            "total_buffer": _f(buffer_bps),
        },
        "evidence": {
            "spot_ask_vwap": str(priced["quotes"]["spot_ask_vwap"]),
            "futures_bid_vwap": str(priced["quotes"]["fut_bid_vwap"]),
            "spot_bid_vwap": str(priced["quotes"]["spot_bid_vwap"]),
            "futures_ask_vwap": str(priced["quotes"]["fut_ask_vwap"]),
            "entry_basis_measured_bps": _f(priced["entry_basis_measured_bps"]),
            "entry_basis_top_of_book_bps": _f(
                bps(priced["quotes"]["spot_ask_top"] - priced["quotes"]["fut_bid_top"],
                    (priced["quotes"]["spot_ask_top"] + priced["quotes"]["fut_bid_top"]) / 2)),
            "hours_to_next_funding": round(fund["hours_to_next"], 2),
            "funding_prints_bps": fund["prints"],
            "funding_sign_persistent": fund["persistent"],
            "book_depth_levels": DEPTH_LIMIT,
            "quote_latency_ms": priced["latency_ms"],
            "fee_basis": "spot 7.5 bps and futures 5 bps, verified 2026-09-04 "
                         "against settled fills; see venue.py",
        },
    }

    # Order matters. The cheapest checks that can veto a trade run first, so a
    # refusal names the binding reason rather than the last one tested.
    if fund["rate_bps"] <= 0:
        reason = "funding_not_positive"
    elif not fund["persistent"]:
        reason = "funding_sign_not_persistent"
    elif fund["hours_to_next"] < 1.0:
        # Entering just before settlement pays the full round trip for a
        # sliver of carry.
        reason = "too_close_to_settlement"
    elif risk_adjusted < min_edge:
        reason = "insufficient_edge"
    else:
        reason = "edge_clears_cost"

    approved = reason == "edge_clears_cost"
    result["decision"] = "APPROVE" if approved else "REJECT"
    result["reason"] = reason
    result["max_notional_usdt"] = _f(priced["notional"], 2) if approved else 0.0
    if approved:
        # An approval is not permission to trade whatever the model likes. It
        # authorises this size, on this symbol, at no worse than this cost,
        # until it expires.
        result["authorization"] = {
            "symbol": symbol,
            "legs": [
                {"venue": "futures_usds", "side": "SELL", "order": 1,
                 "quantity": result["size"]["futures_qty"], "leverage": 1},
                {"venue": "spot", "side": "BUY", "order": 2,
                 "quantity": "size from leg 1 executedQty, truncated to the "
                             "spot stepSize"},
            ],
            "max_entry_basis_bps": _f(cost["entry_basis_bps"] + buffer_bps),
            "expires_at": result["expires_at"],
        }
    else:
        result["shortfall_bps"] = _f(min_edge - risk_adjusted)
    return result


def _evaluate_conversion(symbol, notional_usdt=5.0, side=None,
                         max_cost_bps=None, refresh=False):
    """
    Price a single spot crossing and return a verdict in the same shape.

    A conversion has no edge to clear, so the test is not "does it earn more
    than it costs" but "is this a sane price for a trade you have already
    decided to make". Those are different questions and this returns the
    second one honestly rather than borrowing the first one's machinery.

    Two things the carry path carries are deliberately not carried here. The
    calibration gap is measured against hedge fills and says nothing about a
    single crossing, so applying it would be borrowing an unrelated error bar.
    Funding is irrelevant to a trade held for no settlements.
    """
    ceiling = Decimal(str(max_cost_bps)) if max_cost_bps is not None else MAX_COST_BPS
    measured_at = _now()

    def refuse(reason, **extra):
        out = {
            "schema_version": SCHEMA_VERSION,
            "decision": "REJECT",
            "reason": reason,
            "symbol": symbol,
            "strategy": "spot_conversion",
            "measured_at": _iso(measured_at),
            "expires_at": _iso(measured_at + timedelta(seconds=TTL_SECONDS)),
            "ttl_seconds": TTL_SECONDS,
            "max_notional_usdt": 0.0,
        }
        out.update(extra)
        return out

    if side is None:
        # The caller asked for a conversion without saying which way. Guessing
        # would be inventing an intention, so this refuses instead.
        return refuse("side_required",
                      detail="A conversion has a direction. Pass side=BUY or "
                             "side=SELL.")
    side = str(side).upper().strip()
    if side not in ("BUY", "SELL"):
        return refuse("side_invalid", detail=f"side must be BUY or SELL, got {side!r}")

    spot, _ = venue.spot_specs(refresh=refresh)
    if symbol not in spot:
        return refuse("no_spot_market",
                      detail="Not a tradable USDT spot pair.")

    priced, err = price_conversion(symbol, notional_usdt, side, spot[symbol])
    if priced is None:
        return refuse(err)

    cost = priced["cost"]
    buffer_bps = max(ZERO, priced["depth_impact_bps"])
    total = cost["total_bps"]

    result = {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "strategy": "spot_conversion",
        "side": side,
        "measured_at": _iso(measured_at),
        "expires_at": _iso(measured_at + timedelta(seconds=TTL_SECONDS)),
        "ttl_seconds": TTL_SECONDS,
        "size": {
            "requested_notional_usdt": float(notional_usdt),
            "spot_qty": venue.fmt_qty(priced["qty"], spot[symbol].step),
            "priced_notional_usdt": _f(priced["notional"], 4),
            "scaled_to_venue_minimum": priced["scaled_up"],
            "depth_cover_x": _f(priced["cover"], 1),
        },
        # Three of the hedge's four cost terms are absent rather than zero.
        # See price_conversion: a zero would claim they were measured.
        "cost_bps": {
            "fees": _f(cost["fees_bps"]),
            "spread": _f(cost["spread_bps"]),
            "total": _f(total),
            "ceiling": _f(ceiling),
        },
        "uncertainty_bps": {
            "depth_impact": _f(priced["depth_impact_bps"]),
            "total_buffer": _f(buffer_bps),
        },
        "evidence": {
            "spot_ask_vwap": str(priced["quotes"]["ask_vwap"]),
            "spot_bid_vwap": str(priced["quotes"]["bid_vwap"]),
            "crossed_vwap": str(priced["quotes"]["cross_vwap"]),
            "mid_at_top_of_book": str(priced["quotes"]["mid"]),
            "book_depth_levels": DEPTH_LIMIT,
            "quote_latency_ms": priced["latency_ms"],
            "fee_basis": "spot 7.5 bps, one crossing, verified 2026-09-04 "
                         "against settled fills; see venue.py",
            "omitted_terms": "entry_basis, exit_spread and lot_residual do not "
                             "exist for a single leg and are omitted rather "
                             "than reported as zero",
        },
    }

    approved = total <= ceiling
    result["decision"] = "APPROVE" if approved else "REJECT"
    result["reason"] = "cost_within_ceiling" if approved else "cost_exceeds_ceiling"
    result["max_notional_usdt"] = _f(priced["notional"], 2) if approved else 0.0
    if approved:
        result["authorization"] = {
            "symbol": symbol,
            "legs": [
                {"venue": "spot", "side": side, "order": 1,
                 "quantity": result["size"]["spot_qty"]},
            ],
            "max_cost_bps": _f(total + buffer_bps),
            "expires_at": result["expires_at"],
        }
    else:
        result["shortfall_bps"] = _f(total - ceiling)
    return result


def evaluate(symbol, notional_usdt=5.0, side=None, strategy="auto",
             hold_periods=HOLD_PERIODS, min_edge_bps=None,
             max_cost_bps=None, refresh=False):
    """
    Price a proposed trade and return a verdict. Picks the model first.

    Two trades reach this function and they cost different things. A hedge is
    two legs, four crossings and a cross-venue basis. A conversion is one leg
    and one crossing. Pricing the second with the first model is how a plain
    5 USDT BNB buy came back REJECT at a 51 bps shortfall on 2026-09-06: the
    arithmetic was right and the question was wrong.

    The symbol cannot settle it, because BNBUSDT is a valid conversion and a
    valid hedge. Direction can: a conversion has one side, a hedge has both.
    So `side` selects, and `strategy` overrides when the caller wants to be
    explicit. Callers that pass neither, scanner.py included, get the carry
    model exactly as before.
    """
    symbol = symbol.upper().strip()
    strategy = (strategy or "auto").lower().strip()

    if strategy == "auto":
        strategy = "conversion" if side is not None else "carry"
    if strategy not in ("carry", "conversion"):
        return {
            "schema_version": SCHEMA_VERSION,
            "decision": "REJECT",
            "reason": "strategy_unknown",
            "detail": f"strategy must be auto, carry or conversion, got "
                      f"{strategy!r}",
            "symbol": symbol,
            "measured_at": _iso(_now()),
            "expires_at": _iso(_now() + timedelta(seconds=TTL_SECONDS)),
            "ttl_seconds": TTL_SECONDS,
            "max_notional_usdt": 0.0,
        }

    if strategy == "conversion":
        return _evaluate_conversion(symbol, notional_usdt=notional_usdt,
                                    side=side, max_cost_bps=max_cost_bps,
                                    refresh=refresh)
    return _evaluate_carry(symbol, notional_usdt=notional_usdt,
                           hold_periods=hold_periods,
                           min_edge_bps=min_edge_bps, refresh=refresh)


def _explain_conversion(d):
    """A conversion as a human reads it. No funding lines, because none exist."""
    L = [f"{d['decision']}  {d['symbol']}  {d.get('side', '')}  ({d['reason']})"]
    if "cost_bps" not in d:
        L.append(f"  {d.get('detail', 'no priceable market')}")
        return "\n".join(L)
    c, u, s = d["cost_bps"], d["uncertainty_bps"], d["size"]
    L += [
        f"  measured {d['measured_at']}   expires {d['expires_at']}"
        f"   ({d['ttl_seconds']}s)",
        f"  size            {s['spot_qty']} = {s['priced_notional_usdt']} USDT"
        + ("   scaled up to the venue minimum" if s["scaled_to_venue_minimum"] else ""),
        "",
        f"  fee             {c['fees']:>7.2f} bps   one taker crossing",
        f"  spread          {c['spread']:>7.2f} bps   mid to fill, at size",
        f"                  {'':>7}       {'-' * 7}",
        f"  cost            {c['total']:>7.2f} bps   against {c['ceiling']:.2f} "
        f"allowed",
        "",
        f"  buffer          {u['total_buffer']:>7.2f} bps   depth impact, measured",
        "  no entry basis, exit spread or lot residual: one leg, one crossing.",
    ]
    if d["decision"] == "REJECT":
        L.append(f"\n  over by {d.get('shortfall_bps', 0):.2f} bps. Not trading.")
    else:
        L.append(f"\n  authorised to {d['max_notional_usdt']} USDT "
                 f"until {d['expires_at']}.")
    return "\n".join(L)


def explain(d):
    """The decision as a human reads it. Same numbers, no second source."""
    if d.get("strategy") == "spot_conversion":
        return _explain_conversion(d)
    L = [f"{d['decision']}  {d['symbol']}  ({d['reason']})"]
    if "cost_bps" not in d:
        L.append(f"  {d.get('detail', 'no priceable market')}")
        return "\n".join(L)
    c, e, u = d["cost_bps"], d["edge_bps"], d["uncertainty_bps"]
    L += [
        f"  measured {d['measured_at']}   expires {d['expires_at']}"
        f"   ({d['ttl_seconds']}s)",
        f"  size            {d['size']['futures_qty']} perp / "
        f"{d['size']['spot_qty']} spot  "
        f"= {d['size']['priced_notional_usdt']} USDT per leg",
        "",
        f"  fees            {c['fees']:>7.2f} bps   verified, four taker fills",
        f"  entry basis     {c['entry_basis']:>7.2f} bps   at size, spot ask "
        f"vs futures bid",
        f"  exit spread     {c['exit_spread']:>7.2f} bps   at size, both venues",
        f"  lot residual    {c['lot_residual']:>7.2f} bps   unhedgeable "
        f"truncation",
        f"                  {'':>7}       {'-' * 7}",
        f"  cost to beat    {c['total']:>7.2f} bps",
        "",
        f"  funding         {e['funding_per_settlement']:>7.3f} bps x "
        f"{e['hold_periods']} settlements = {e['gross_funding']:.2f} bps",
        f"  net             {e['net']:>7.2f} bps",
        f"  buffer          {u['total_buffer']:>7.2f} bps   "
        f"depth {u['depth_impact']:.2f} + calibration {u['calibration_gap']:.2f} "
        f"(n={u['calibration_n']})",
        f"  risk adjusted   {e['risk_adjusted']:>7.2f} bps   against "
        f"{e['min_edge_required']:.2f} required",
    ]
    if d["decision"] == "REJECT":
        L.append(f"\n  short by {d.get('shortfall_bps', 0):.2f} bps. Not trading.")
    else:
        L.append(f"\n  authorised to {d['max_notional_usdt']} USDT per leg "
                 f"until {d['expires_at']}.")
    return "\n".join(L)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Price a proposed trade against live books. Passing --side "
                    "prices a single spot crossing; omitting it prices a "
                    "delta-neutral funding carry.")
    ap.add_argument("symbol")
    ap.add_argument("--notional", type=float, default=5.0)
    ap.add_argument("--side", choices=["BUY", "SELL"], default=None,
                    help="single-leg conversion in this direction")
    ap.add_argument("--strategy", choices=["auto", "carry", "conversion"],
                    default="auto", help="override the model selection")
    ap.add_argument("--hold", type=int, default=HOLD_PERIODS,
                    help="carry only: settlements underwritten")
    ap.add_argument("--max-cost", type=float, default=None,
                    help="conversion only: cost ceiling in bps")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    d = evaluate(a.symbol, notional_usdt=a.notional, side=a.side,
                 strategy=a.strategy, hold_periods=a.hold,
                 max_cost_bps=a.max_cost)
    print(json.dumps(d, indent=2) if a.json else "\n" + explain(d) + "\n")
