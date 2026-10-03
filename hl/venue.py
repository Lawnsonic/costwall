"""
Hyperliquid venue rules: what an order on a given coin is allowed to look like,
and what it costs in fees. Read from the API, never typed in.

WHERE EACH RULE COMES FROM
--------------------------
size        rounded to the asset's szDecimals                       (meta)
price       at most 5 significant figures and at most
            MAX_DECIMALS - szDecimals decimal places; integers
            always allowed. MAX_DECIMALS is 6 for perps             (docs: tick-and-lot-size)
asset id    main dex: index in meta. HIP-3 dex n:
            100000 + n * 10000 + index                              (docs: asset-ids)
fees        the account's own rates from userFees, scaled for
            HIP-3 markets exactly as the docs' feeRates() does      (docs: fees)
minimum     $10 order value                                         (exchange error text)

HIP-3 FEES, THE PART NOBODY PRICES
----------------------------------
A builder-deployed market charges the account's base rate times a HIP-3
scale (2x at the default deployerFeeScale of 1.0, because the deployer keeps
half), times 0.1 if the deployer has growth mode on. On xyz today most stock
markets have growth mode on and a few do not, so two stock perps on the same
venue can differ ten-fold in fees. The scale is per asset and the deployer can
change it, so it is read on every call rather than cached for long.

Aligned quote tokens get a lower taker fee. This module does not detect them
and charges the unaligned rate, which can only overstate cost, never hide it.
"""

import os
import sys
import time
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hl import info

BPS = Decimal("10000")
PERP_MAX_DECIMALS = 6
PRICE_SIG_FIGS = 5
MIN_NOTIONAL_USD = Decimal("10")

# With no address the public base tier is used, and the result says so.
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# Meta is re-read after this many seconds. Short, because a deployer can flip
# growth mode or the fee scale at any time and fees are part of the verdict.
META_TTL = 60

_cache = {}


def _cached(key, fn, ttl):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def dex_index():
    """{dex name: perp_dex_index}. The main dex is "" at index 0."""
    def load():
        raw = info.q({"type": "perpDexs"})
        return {(d["name"] if d else ""): i for i, d in enumerate(raw)}
    return _cached("dexs", load, META_TTL)


def split_coin(coin):
    """'xyz:TSLA' -> ('xyz', 'xyz:TSLA'); 'BTC' -> ('', 'BTC')."""
    return (coin.split(":", 1)[0], coin) if ":" in coin else ("", coin)


def market(coin):
    """Static rules plus the live context for one perp, in one meta read.

    Raises KeyError for a coin or dex the exchange does not list, which the
    oracle turns into a refusal: an unknown market has unknown fees.
    """
    dex, name = split_coin(coin)
    dexs = dex_index()
    if dex not in dexs:
        raise KeyError(f"unknown dex {dex!r}")
    universe, ctxs = _cached(f"meta:{dex}", lambda: info.meta_and_ctxs(dex), META_TTL)
    for i, (a, c) in enumerate(zip(universe, ctxs)):
        if a["name"] == name:
            n = dexs[dex]
            return {
                "coin": name,
                "dex": dex or "main",
                "hip3": bool(dex),
                "asset_id": i if not dex else 100000 + n * 10000 + i,
                "sz_decimals": a["szDecimals"],
                "max_leverage": a["maxLeverage"],
                "growth_mode": a.get("growthMode") == "enabled",
                "deployer_fee_scale": Decimal(a.get("deployerFeeScale", "1.0")),
                "is_delisted": bool(a.get("isDelisted")),
                "only_isolated": bool(a.get("onlyIsolated")),
                # Hourly rate. On HIP-3 the deployer's funding multiplier is
                # already applied: xyz shows 0.00000625 = 0.5 x 0.0000125.
                "funding_hourly": Decimal(c["funding"]),
                "premium": Decimal(c["premium"]) if c.get("premium") else None,
                "oracle_px": Decimal(c["oraclePx"]),
                "mark_px": Decimal(c["markPx"]),
                "mid_px": Decimal(c["midPx"]) if c.get("midPx") else None,
                "day_ntl_vlm": Decimal(c["dayNtlVlm"]),
            }
    raise KeyError(f"unknown coin {coin!r}")


def round_size(spec, qty):
    """Truncate toward zero. Never round a size up past what was approved."""
    step = Decimal(1).scaleb(-spec["sz_decimals"])
    return (Decimal(qty) / step).to_integral_value(rounding=ROUND_FLOOR) * step


def round_price(spec, px, is_buy):
    """Legal limit price that never crosses the approved ceiling.

    A buy rounds down and a sell rounds up, so the order can only be more
    conservative than the authorization, never less.
    """
    px = Decimal(px)
    rounding = ROUND_FLOOR if is_buy else ROUND_CEILING
    if px == px.to_integral_value():
        return px
    max_dp = PERP_MAX_DECIMALS - spec["sz_decimals"]
    sig_dp = PRICE_SIG_FIGS - px.adjusted() - 1
    dp = max(0, min(max_dp, sig_dp))
    out = px.quantize(Decimal(1).scaleb(-dp), rounding=rounding)
    if out == 0:
        raise ValueError(f"price {px} has no legal tick on {spec['coin']}")
    return out


def account_fees(user=None):
    """The account's own base rates. Tier, staking and referral come from here."""
    addr = user or os.environ.get("HL_ADDRESS") or ZERO_ADDRESS
    uf = _cached(f"fees:{addr}", lambda: info.q({"type": "userFees", "user": addr}), 3600)
    return {
        "address": addr,
        "source": "account" if addr != ZERO_ADDRESS else "public base tier (no HL_ADDRESS set)",
        "taker": Decimal(uf["userCrossRate"]),
        "maker": Decimal(uf["userAddRate"]),
        "referral_discount": Decimal(uf.get("activeReferralDiscount") or "0"),
    }


def perp_fee_bps(spec, user=None):
    """Taker and maker in bps for this perp. Mirrors the docs' feeRates()."""
    acct = account_fees(user)
    hip3_scale, growth_scale = Decimal(1), Decimal(1)
    if spec["hip3"]:
        s = spec["deployer_fee_scale"]
        hip3_scale = s + 1 if s < 1 else s * 2
        growth_scale = Decimal("0.1") if spec["growth_mode"] else Decimal(1)
    ref = 1 - acct["referral_discount"]
    taker = acct["taker"] * hip3_scale * growth_scale * ref * BPS
    maker = acct["maker"] * growth_scale * BPS
    if maker > 0:
        maker *= hip3_scale * ref
    return {
        "taker_bps": taker,
        "maker_bps": maker,
        "base_taker_bps": acct["taker"] * BPS,
        "hip3_scale": hip3_scale,
        "growth_mode_scale": growth_scale,
        "referral_discount": acct["referral_discount"],
        "fee_source": acct["source"],
    }
