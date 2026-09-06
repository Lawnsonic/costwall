"""
Verification for the single-leg conversion path and, more importantly, a
regression guard on the hedge path it was added beside.

WHY THIS FILE IS SHAPED THIS WAY
--------------------------------
Adding the conversion model meant splitting evaluate() into a selector over
two pricers. A refactor like that can change field order, a rounding path or
a format string without changing anything a smoke test would notice, and the
README quotes exact evaluate_trade output as evidence. Two numbers on screen
that disagree is the failure this project keeps having, so the carry path is
pinned here byte for byte, not merely checked for plausibility.

Byte-identical against live books is impossible, so the inputs are frozen:

  --capture SYMBOL   hit live REST once, save the raw payloads to fixtures/
  --baseline         replay them through the CURRENT oracle, save the output
  (no flag)          replay them again and assert the output has not moved

The baseline is generated BEFORE the refactor and committed. If the diff at
the end is empty, the carry path survived. If it is not, the refactor changed
a number the README cites, and that is a bug regardless of how it looks.

The conversion checks recompute the arithmetic independently, from the same
fixture ladder, rather than calling the function under test and agreeing with
it. A test that shares an implementation with its subject proves nothing.
"""

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from execution import venue

try:
    from cost import cost_oracle
except ImportError:
    import cost_oracle

FIX = os.path.join(HERE, "fixtures")
SYMBOL = "BNBUSDT"

# A fixed instant, so measured_at, expires_at, hours_to_next_funding and the
# quote latency are all constants rather than whatever the clock said.
FROZEN = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)
FROZEN_EPOCH = FROZEN.timestamp()

BPS = Decimal("10000")
ZERO = Decimal("0")


def _key(url, params):
    """Stable cache key for a REST call: path plus sorted query."""
    path = url.split(".com", 1)[-1]
    items = sorted((params or {}).items())
    return path + "?" + "&".join(f"{k}={v}" for k, v in items)


def books_path(symbol):
    return os.path.join(FIX, f"{symbol.lower()}_books.json")


def baseline_path(symbol):
    return os.path.join(FIX, f"{symbol.lower()}_carry_baseline.json")


# --- Fixture capture --------------------------------------------------

def capture(symbol):
    """Record every REST payload the oracle needs, once, from live venues."""
    calls = [
        (venue.SAPI + "/api/v3/depth",
         {"symbol": symbol, "limit": cost_oracle.DEPTH_LIMIT}),
        (venue.FAPI + "/fapi/v1/depth",
         {"symbol": symbol, "limit": cost_oracle.DEPTH_LIMIT}),
        (venue.FAPI + "/fapi/v1/premiumIndex", {"symbol": symbol}),
        (venue.FAPI + "/fapi/v1/fundingRate",
         {"symbol": symbol, "limit": cost_oracle.PERSISTENCE}),
    ]
    store = {}
    for url, params in calls:
        store[_key(url, params)] = venue.http_get(url, params)
    os.makedirs(FIX, exist_ok=True)
    with open(books_path(symbol), "w", encoding="utf-8") as fh:
        json.dump(store, fh, indent=2)
    print(f"captured {len(store)} payloads -> {books_path(symbol)}")


class _Replay:
    """http_get, served from the fixture. An unstubbed call is a test bug."""

    def __init__(self, store):
        self.store = store
        self.seen = []

    def __call__(self, url, params=None, timeout=None, retries=None):
        k = _key(url, params)
        self.seen.append(k)
        if k not in self.store:
            raise AssertionError(f"unstubbed REST call: {k}")
        return self.store[k]


class _FrozenTime:
    """Only what cost_oracle asks of the time module."""

    @staticmethod
    def time():
        return FROZEN_EPOCH


class _Sandbox:
    """Replayed books and a stopped clock, restored on exit."""

    def __init__(self, symbol):
        with open(books_path(symbol), "r", encoding="utf-8") as fh:
            self.store = json.load(fh)

    def __enter__(self):
        self._http = venue.http_get
        self._time = cost_oracle.time
        self._now = cost_oracle._now
        self.replay = _Replay(self.store)
        venue.http_get = self.replay
        cost_oracle.time = _FrozenTime
        cost_oracle._now = lambda: FROZEN
        return self

    def __exit__(self, *exc):
        venue.http_get = self._http
        cost_oracle.time = self._time
        cost_oracle._now = self._now
        return False


def write_baseline(symbol):
    with _Sandbox(symbol):
        out = cost_oracle.evaluate(symbol, notional_usdt=5.0)
    with open(baseline_path(symbol), "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    print(f"carry baseline -> {baseline_path(symbol)}")
    print(f"  {out['decision']}  {out['reason']}  "
          f"total {out.get('cost_bps', {}).get('total')} bps")


# --- Checks -----------------------------------------------------------

FAILURES = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not ok:
        FAILURES.append(name)
    return ok


def check_carry_unchanged(symbol):
    """The whole point. Same books, same clock, same bytes."""
    print("\ncarry path, byte-identical against pre-refactor baseline")
    if not os.path.exists(baseline_path(symbol)):
        return check("baseline exists", False, "run --baseline before refactoring")
    with open(baseline_path(symbol), "r", encoding="utf-8") as fh:
        want = fh.read()
    with _Sandbox(symbol):
        got = json.dumps(cost_oracle.evaluate(symbol, notional_usdt=5.0), indent=2)
    if got == want:
        return check("carry output unchanged", True, f"{len(got)} bytes")
    check("carry output unchanged", False)
    w, g = want.splitlines(), got.splitlines()
    for i in range(max(len(w), len(g))):
        a = w[i] if i < len(w) else "<missing>"
        b = g[i] if i < len(g) else "<missing>"
        if a != b:
            print(f"        line {i + 1}\n        was: {a.strip()}\n        now: {b.strip()}")
    return False


def _expected_conversion(store, symbol, side, notional):
    """
    The conversion arithmetic, computed here from the raw ladder, with no
    reference to the module under test beyond the fee constant and the shared
    step arithmetic. If this and price_conversion agree, they agree for a
    reason.
    """
    raw = store[_key(venue.SAPI + "/api/v3/depth",
                     {"symbol": symbol, "limit": cost_oracle.DEPTH_LIMIT})]
    bids = [(Decimal(p), Decimal(q)) for p, q in raw["bids"]]
    asks = [(Decimal(p), Decimal(q)) for p, q in raw["asks"]]
    spec = venue.spot_specs()[0][symbol]

    ask_top, bid_top = asks[0][0], bids[0][0]
    ref = (ask_top + bid_top) / 2
    cross_top = ask_top if side == "BUY" else bid_top

    # Sizing follows the venue's own filters, which are shared arithmetic and
    # not part of what is being verified here. On BNBUSDT a 5 USDT request
    # floors to 0.006 BNB, which is 4.47 USDT and under the 5 USDT minimum, so
    # the order that actually reaches the exchange is 0.007 BNB for 5.22. The
    # cost terms below are what this function checks independently.
    qty = venue.floor_step(Decimal(str(notional)) / cross_top, spec.step)
    q_min = venue.ceil_step(
        max(spec.min_qty, spec.min_notional / cross_top), spec.step)
    if qty < q_min:
        qty = q_min

    def vwap(levels, need):
        spend, got = ZERO, ZERO
        for px, q in levels:
            if need <= 0:
                break
            take = min(need, q)
            spend += take * px
            got += take
            need -= take
        return spend / got

    ask_vwap, bid_vwap = vwap(asks, qty), vwap(bids, qty)
    cross_vwap = ask_vwap if side == "BUY" else bid_vwap

    # The cost of the crossing is the distance from mid to the price actually
    # paid, at size. Directional, not a symmetric half-spread.
    slip = (cross_vwap - ref) if side == "BUY" else (ref - cross_vwap)
    fees = venue.SPOT_TAKER * BPS
    return {
        "qty": qty,
        "fees": fees,
        "spread": slip / ref * BPS,
        "total": fees + slip / ref * BPS,
        "notional": qty * cross_vwap,
    }


def check_conversion_arithmetic(symbol):
    print("\nconversion arithmetic, against an independent recomputation")
    for side in ("BUY", "SELL"):
        with _Sandbox(symbol) as box:
            got = cost_oracle.evaluate(symbol, notional_usdt=5.0, side=side)
            want = _expected_conversion(box.store, symbol, side, 5.0)
        c = got.get("cost_bps", {})
        check(f"{side} strategy is conversion",
              got.get("strategy") == "spot_conversion", got.get("strategy", "?"))
        check(f"{side} fees", c.get("fees") == float(round(want["fees"], 2)),
              f"{c.get('fees')} bps")
        check(f"{side} spread", c.get("spread") == float(round(want["spread"], 2)),
              f"{c.get('spread')} bps")
        check(f"{side} total", c.get("total") == float(round(want["total"], 2)),
              f"{c.get('total')} bps")
        check(f"{side} quantity",
              got.get("size", {}).get("spot_qty") == venue.fmt_qty(
                  want["qty"], venue.spot_specs()[0][symbol].step),
              got.get("size", {}).get("spot_qty", "?"))
        # A hedge term must not appear on a single leg, at any value. Silently
        # zeroing it would be a claim that it was measured and found to be nil.
        for absent in ("entry_basis", "exit_spread", "lot_residual"):
            check(f"{side} omits {absent}", absent not in c)
        check(f"{side} no funding block", "edge_bps" not in got)


def check_selector(symbol):
    print("\nselector routing")
    cases = [
        ({}, "funding_carry_delta_neutral", "no side -> carry"),
        ({"side": "BUY"}, "spot_conversion", "side -> conversion"),
        ({"side": "BUY", "strategy": "carry"}, "funding_carry_delta_neutral",
         "explicit strategy overrides side"),
    ]
    for kwargs, want, label in cases:
        with _Sandbox(symbol):
            got = cost_oracle.evaluate(symbol, notional_usdt=5.0, **kwargs)
        check(label, got.get("strategy") == want, got.get("strategy", "?"))

    with _Sandbox(symbol):
        got = cost_oracle.evaluate(symbol, notional_usdt=5.0, strategy="conversion")
    check("conversion without side is refused, not guessed",
          got.get("decision") == "REJECT" and got.get("reason") == "side_required",
          f"{got.get('decision')}/{got.get('reason')}")

    with _Sandbox(symbol):
        got = cost_oracle.evaluate(symbol, notional_usdt=5.0, side="SIDEWAYS")
    check("an unusable side is refused",
          got.get("decision") == "REJECT" and got.get("reason") == "side_invalid",
          f"{got.get('decision')}/{got.get('reason')}")


def check_ceiling(symbol):
    print("\ncost ceiling")
    with _Sandbox(symbol):
        loose = cost_oracle.evaluate(symbol, notional_usdt=5.0, side="BUY")
        tight = cost_oracle.evaluate(symbol, notional_usdt=5.0, side="BUY",
                                     max_cost_bps=1.0)
    check("clears a 50 bps ceiling", loose.get("decision") == "APPROVE",
          f"{loose.get('reason')} at {loose.get('cost_bps', {}).get('total')} bps")
    check("refused under a 1 bps ceiling",
          tight.get("decision") == "REJECT"
          and tight.get("reason") == "cost_exceeds_ceiling",
          f"{tight.get('reason')} short by {tight.get('shortfall_bps')} bps")
    if tight.get("decision") == "REJECT":
        want = round(tight["cost_bps"]["total"] - 1.0, 2)
        check("shortfall is cost minus ceiling",
              abs(tight.get("shortfall_bps", 0) - want) < 0.011,
              f"{tight.get('shortfall_bps')} vs {want}")
    check("approval authorises one spot leg only",
          len(loose.get("authorization", {}).get("legs", [])) == 1)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--capture":
        return capture(args[1] if len(args) > 1 else SYMBOL)
    if args and args[0] == "--baseline":
        return write_baseline(args[1] if len(args) > 1 else SYMBOL)

    symbol = args[0] if args else SYMBOL
    if not os.path.exists(books_path(symbol)):
        print(f"no fixture for {symbol}; run --capture {symbol} first")
        return sys.exit(2)

    print(f"replaying {symbol} books frozen at {FROZEN.isoformat()}")
    check_carry_unchanged(symbol)
    check_conversion_arithmetic(symbol)
    check_selector(symbol)
    check_ceiling(symbol)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("all checks pass")


if __name__ == "__main__":
    main()
