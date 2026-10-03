"""
Live refusal log: price a standard trade across Hyperliquid every few minutes.

WHY
---
"It refuses everything" and "it approves everything" are both failures, and
only a log of real verdicts can show which this is. Every SCAN_EVERY seconds
this prices a $25 long and a $25 short, held 8 hours, on the busiest main-dex
and xyz markets, and appends one compact row per verdict. Nothing is sent to
the exchange; it only reads books. The rows are in-window evidence: they were
produced during the hackathon, by the code in this repository, from live data.

Fixed size and hold so rows are comparable across markets and over time.
The oracle is called exactly as an agent would call it, with no special flags,
so off-hours stock perps show up as internal_price_session refusals.

Run:  python -m hl.scan        (writes evidence/hl/scan/YYYY-MM-DD.jsonl)
"""

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
from hl.oracle import evaluate_perp

OUT = os.path.join(ROOT, "evidence", "hl", "scan")
SCAN_EVERY = 300
NOTIONAL = 25
HOLD_HOURS = 8
TOP_MAIN, TOP_XYZ = 10, 10


def markets():
    out = []
    for dex, top in (("", TOP_MAIN), ("xyz", TOP_XYZ)):
        universe, ctxs = info.meta_and_ctxs(dex)
        live = sorted(((float(c["dayNtlVlm"]), a["name"]) for a, c in zip(universe, ctxs)
                       if not a.get("isDelisted")), reverse=True)
        out += [name for _, name in live[:top]]
    return out


def row(v):
    c = v.get("cost_bps", {})
    src = v.get("price_source") or v.get("evidence", {}).get("price_source") or {}
    return {
        "ts": v["measured_at"], "coin": v["coin"], "side": v.get("side"),
        "decision": v["decision"], "reason": v["reason"],
        "total_bps": c.get("total"), "fees_bps": c.get("fees_round_trip"),
        "crossing_bps": (c["entry_crossing"] + c["exit_crossing"]) if c else None,
        "funding_bps": c.get("funding_over_hold"),
        "shortfall_bps": v.get("shortfall_bps"),
        "session": src.get("session"), "session_why": src.get("why"),
        "taker_fee_bps": v.get("evidence", {}).get("taker_fee_bps"),
    }


def scan_once():
    rows = []
    for coin in markets():
        for side in ("BUY", "SELL"):
            try:
                rows.append(row(evaluate_perp(coin, NOTIONAL, side, hold_hours=HOLD_HOURS)))
            except Exception as e:  # one market failing must not end the scan
                rows.append({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "coin": coin, "side": side, "decision": "ERROR",
                             "reason": f"{type(e).__name__}: {e}"})
    os.makedirs(OUT, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with open(os.path.join(OUT, f"{day}.jsonl"), "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    return rows


def main():
    while True:
        start = time.time()
        try:
            rows = scan_once()
            n_ok = sum(r["decision"] == "APPROVE" for r in rows)
            print(f"{datetime.now(timezone.utc):%H:%M:%S} {len(rows)} verdicts, "
                  f"{n_ok} approve", flush=True)
        except Exception as e:
            print(f"scan error {type(e).__name__}: {e}", flush=True)
        time.sleep(max(0.0, SCAN_EVERY - (time.time() - start)))


if __name__ == "__main__":
    if "--once" in sys.argv:
        for r in scan_once():
            print(r)
    else:
        main()
