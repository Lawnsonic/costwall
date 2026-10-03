"""
Records Hyperliquid order books and market state to disk, starting now.

WHY THIS RUNS FIRST
-------------------
Colosseum only judges work done inside the hackathon window, so the Binance
evidence from September does not count. Three later pieces need history that
nobody else will hand us:

  - replay tests: price a trade against a book we saved, get the same answer
  - calibration: compare what the oracle predicted with what a fill paid,
    which needs the book as it stood at the fill, not just the fill price
  - refusal value: what would a refused trade actually have cost

A public fill tells you the price paid but not the mid at that moment, so it
cannot measure crossing cost alone. The book can. Every day this does not run
is a day of evidence that cannot be collected later.

WHAT IT WRITES
--------------
data/books/YYYY-MM-DD.jsonl.gz   one line per coin per poll: 20 levels a side
data/ctx/YYYY-MM-DD.jsonl.gz     one line per dex per minute: funding, premium,
                                 oracle and mark price, OI, volume, flags

Appended gzip members, readable with gzip.open() as one stream. The coin set
is the most-traded names on the main dex plus the most-traded live markets on
xyz (trade.xyz: stocks, indices, commodities), refreshed hourly.

Run:  python -m hl.recorder
Stop: Ctrl+C. Safe to restart; it only appends.
"""

import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hl import info

DATA = os.path.join(ROOT, "data")

BOOK_EVERY = 15        # seconds between book polls
CTX_EVERY = 60         # seconds between market-state snapshots
UNIVERSE_EVERY = 3600  # seconds between re-picking the coin set
TOP_MAIN = 8
TOP_HIP3 = 8
HIP3_DEXS = ("xyz",)

# Weight per minute at these settings: (8+8) coins * 2 * 4 polls + 2 dexs * 20
# = 168, against a limit of 1200. Leaves room for the oracle to run alongside.


def _now():
    return datetime.now(timezone.utc)


def _append(kind, rows):
    day = _now().strftime("%Y-%m-%d")
    folder = os.path.join(DATA, kind)
    os.makedirs(folder, exist_ok=True)
    with gzip.open(os.path.join(folder, f"{day}.jsonl.gz"), "at", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")


def pick_coins():
    """Top names by 24h notional volume. Delisted markets are skipped."""
    coins = []
    for dex, top in [("", TOP_MAIN)] + [(d, TOP_HIP3) for d in HIP3_DEXS]:
        universe, ctxs = info.meta_and_ctxs(dex)
        live = [
            (float(c["dayNtlVlm"]), a["name"])
            for a, c in zip(universe, ctxs)
            if not a.get("isDelisted")
        ]
        coins += [name for _, name in sorted(live, reverse=True)[:top]]
    return coins


def snapshot_ctx():
    ts = _now().isoformat()
    rows = []
    for dex in ("",) + HIP3_DEXS:
        universe, ctxs = info.meta_and_ctxs(dex)
        rows.append({"ts": ts, "dex": dex or "main", "universe": universe, "ctxs": ctxs})
    _append("ctx", rows)


def snapshot_books(coins):
    ts = _now().isoformat()
    rows, failed = [], []
    for coin in coins:
        try:
            b = info.l2_book(coin)
            rows.append({"ts": ts, "coin": coin, "time": b["time"], "levels": b["levels"]})
        except Exception as e:  # one bad coin must not stop the rest
            failed.append(f"{coin}:{type(e).__name__}")
    _append("books", rows)
    return len(rows), failed


def main():
    coins, picked_at, ctx_at = [], 0.0, 0.0
    print(f"recording to {DATA}", flush=True)
    while True:
        start = time.time()
        try:
            if start - picked_at >= UNIVERSE_EVERY or not coins:
                coins = pick_coins()
                picked_at = start
                print(f"{_now():%H:%M:%S} coins {coins}", flush=True)
            if start - ctx_at >= CTX_EVERY:
                snapshot_ctx()
                ctx_at = start
            n, failed = snapshot_books(coins)
            if failed:
                print(f"{_now():%H:%M:%S} books {n} failed {failed}", flush=True)
        except Exception as e:  # network drop: log, wait, carry on
            print(f"{_now():%H:%M:%S} error {type(e).__name__}: {e}", flush=True)
            time.sleep(30)
        time.sleep(max(0.0, BOOK_EVERY - (time.time() - start)))


if __name__ == "__main__":
    main()
