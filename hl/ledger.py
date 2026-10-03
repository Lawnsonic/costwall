"""
Net ledger: what an address made after everything, next to what it would claim.

Paste any Hyperliquid address. No key is needed; fills and funding are public.

WHY
---
A live review of a Senpi trading skill (Senpi-ai/senpi-skills PR #800,
merged 2026-09-30) found a headline of +$410.14 that it put at +$256.61 net,
because closedPnl is gross and builderFee was never read. That is not a
Senpi problem, it is the default: an agent that sums closedPnl reports profit
before fees, and one that subtracts only the exchange fee still misses the
builder fee, which on Hyperliquid can be the larger of the two. This shows all
three numbers side by side so the gap is visible:

    closedPnl only           what a naive dashboard shows
    minus exchange fees      what an agent that forgot builder fees shows
    true net                 minus builder fees, plus or minus funding

WHERE EACH NUMBER COMES FROM (userFillsByTime, userFunding)
----------------------------
closedPnl     realised price PnL on closing fills, before any fee
fee           total fee on the fill, INCLUDING the builder fee. Hyperliquid's
              info docs: "the total fee, inclusive of builderFee". Confirmed
              on 5,910 live fills 2026-10-03: fee >= builderFee on every one,
              and fee - builderFee matches the exchange rate. Adding
              builderFee on top of fee double-counts it; PR #800 above does.
builderFee    the builder's share, present only when a builder code was used
funding       userFunding deltas, signed: negative is paid

Crossing cost (the spread paid by taker fills) is already inside closedPnl,
so it is not subtracted again. It is shown as a breakdown of where gross went,
measured against the recorder's books when one exists within 15 s of the fill,
and reported as unmeasured otherwise rather than estimated.

LIMITS
------
Hyperliquid documents a 10,000-fill history limit per address; above it
the totals may be incomplete and the output says so. Open
positions contribute their fees and funding but no realised PnL yet. Fees
paid in a token other than USDC are counted separately, not converted.
"""

import bisect
import glob
import gzip
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hl import info

ZERO = Decimal(0)
BOOKS_DIR = os.path.join(ROOT, "data", "books")
BOOK_MATCH_MS = 15_000


def _paged(kind, address, start_ms, end_ms, key=lambda r: r["time"]):
    """All rows of a time-ranged info query, walking forward past the page cap."""
    rows, cursor = [], start_ms
    while cursor < end_ms:
        page = info.q({"type": kind, "user": address, "startTime": cursor, "endTime": end_ms})
        if not page:
            break
        rows += page
        last = max(key(r) for r in page)
        if last < cursor or len(page) < 500:
            break
        cursor = last + 1
    seen, out = set(), []
    for r in rows:  # page edges can repeat a row
        k = (r.get("tid"), r.get("hash"), key(r), json.dumps(r.get("delta"), sort_keys=True))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return sorted(out, key=key)


def fills(address, start_ms, end_ms):
    return _paged("userFillsByTime", address, start_ms, end_ms)


def funding(address, start_ms, end_ms):
    return _paged("userFunding", address, start_ms, end_ms)


class BookIndex:
    """Mid prices from recorded books, looked up by coin and time."""

    def __init__(self, start_ms, end_ms):
        self.times, self.mids = defaultdict(list), defaultdict(list)
        first = datetime.fromtimestamp(start_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
        last = datetime.fromtimestamp(end_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
        for path in sorted(glob.glob(os.path.join(BOOKS_DIR, "*.jsonl.gz"))):
            day = os.path.basename(path)[:10]
            if not first <= day <= last:
                continue
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    bids, asks = r["levels"]
                    if bids and asks:
                        self.times[r["coin"]].append(r["time"])
                        self.mids[r["coin"]].append(
                            (Decimal(bids[0]["px"]) + Decimal(asks[0]["px"])) / 2)
        for coin in self.times:
            order = sorted(range(len(self.times[coin])), key=self.times[coin].__getitem__)
            self.times[coin] = [self.times[coin][i] for i in order]
            self.mids[coin] = [self.mids[coin][i] for i in order]

    def mid(self, coin, t_ms):
        ts = self.times.get(coin)
        if not ts:
            return None
        i = bisect.bisect_left(ts, t_ms)
        best = min((j for j in (i - 1, i) if 0 <= j < len(ts)), key=lambda j: abs(ts[j] - t_ms))
        return self.mids[coin][best] if abs(ts[best] - t_ms) <= BOOK_MATCH_MS else None


def summarize(address, days=7, now_ms=None):
    end_ms = now_ms or int(time.time() * 1000)
    start_ms = end_ms - int(days * 86_400_000)
    fs = fills(address, start_ms, end_ms)
    fu = funding(address, start_ms, end_ms)
    books = BookIndex(start_ms, end_ms)

    by_coin = defaultdict(lambda: defaultdict(lambda: ZERO))
    other_token_fees = defaultdict(lambda: ZERO)
    crossed_n = measured_n = 0
    spread_paid = ZERO
    for f in fs:
        c = by_coin[f["coin"]]
        notional = Decimal(f["px"]) * Decimal(f["sz"])
        c["fills"] += 1
        c["volume"] += notional
        c["closed_pnl"] += Decimal(f["closedPnl"])
        builder = Decimal(f.get("builderFee") or "0")
        if f.get("feeToken", "USDC") == "USDC":
            c["exchange_fee"] += Decimal(f["fee"]) - builder
            c["builder_fee"] += builder
        else:
            other_token_fees[f["feeToken"]] += Decimal(f["fee"])
        if f.get("crossed"):
            crossed_n += 1
            mid = books.mid(f["coin"], f["time"])
            if mid:
                measured_n += 1
                cost = abs(Decimal(f["px"]) - mid) * Decimal(f["sz"])
                c["spread_paid"] += cost
                spread_paid += cost
    for r in fu:
        d = r["delta"]
        by_coin[d["coin"]]["funding"] += Decimal(d["usdc"])

    tot = defaultdict(lambda: ZERO)
    for c in by_coin.values():
        for k, v in c.items():
            tot[k] += v
    naive = tot["closed_pnl"]
    forgot_builder = naive - tot["exchange_fee"]
    net = forgot_builder - tot["builder_fee"] + tot["funding"]

    def money(x):
        return float(round(x, 2))

    return {
        "address": address,
        "window_days": days,
        "from": datetime.fromtimestamp(start_ms / 1000, timezone.utc).isoformat(timespec="minutes"),
        "to": datetime.fromtimestamp(end_ms / 1000, timezone.utc).isoformat(timespec="minutes"),
        "fills": len(fs),
        "fill_cap_note": "Hyperliquid documents a 10,000-fill history limit; "
                         "totals above it may be incomplete" if len(fs) >= 10_000 else None,
        "headline": {
            "closed_pnl_only": money(naive),
            "minus_exchange_fees": money(forgot_builder),
            "true_net": money(net),
        },
        "costs": {
            "exchange_fees": money(tot["exchange_fee"]),
            "builder_fees": money(tot["builder_fee"]),
            "funding_net": money(tot["funding"]),
            "volume": money(tot["volume"]),
            "builder_fee_share_of_all_fees": (
                float(round(tot["builder_fee"] / (tot["builder_fee"] + tot["exchange_fee"]), 3))
                if tot["builder_fee"] + tot["exchange_fee"] > 0 else None),
            "other_token_fees_unconverted": {k: str(v) for k, v in other_token_fees.items()},
        },
        "crossing": {
            "taker_fills": crossed_n,
            "measured_against_recorded_book": measured_n,
            "spread_paid_measured": money(spread_paid),
            "note": "already inside closed_pnl; shown as a breakdown, not subtracted. "
                    "Unmeasured fills are not estimated.",
        },
        "by_coin": {
            coin: {k: money(v) if k != "fills" else int(v) for k, v in c.items()}
            for coin, c in sorted(by_coin.items(), key=lambda kv: -kv[1]["volume"])
        },
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="True net PnL for a Hyperliquid address.")
    p.add_argument("address")
    p.add_argument("--days", type=float, default=7)
    a = p.parse_args()
    print(json.dumps(summarize(a.address, a.days), indent=2))
