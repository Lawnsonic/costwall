"""
Ledger arithmetic on hand-made fills, no network.

The fill below is shaped like a real one seen on 2026-10-03 (xyz:AMZN, maker,
builder code at the 10 bps cap): fee 0.025428 includes builderFee 0.024796.

Run:  python -m tests.test_ledger
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hl import ledger

FILLS = [
    {"coin": "xyz:AMZN", "px": "250.47", "sz": "0.099", "time": 1790000001000, "closedPnl": "0.07722",
     "crossed": False, "fee": "0.025428", "builderFee": "0.024796", "feeToken": "USDC", "tid": 1},
    {"coin": "BTC", "px": "100000", "sz": "0.001", "time": 1790000002000, "closedPnl": "-1.5",
     "crossed": True, "fee": "0.045", "feeToken": "USDC", "tid": 2},
]
FUNDING = [{"time": 1790000003000, "hash": "0x0", "delta": {"coin": "BTC", "usdc": "-0.2"}}]


def test_three_headlines():
    ledger.fills = lambda *a: FILLS
    ledger.funding = lambda *a: FUNDING
    ledger.BOOKS_DIR = os.path.join(ROOT, "no-such-dir")
    s = ledger.summarize("0xabc", days=1, now_ms=1790000010000)
    h, c = s["headline"], s["costs"]
    assert h["closed_pnl_only"] == round(0.07722 - 1.5, 2)
    exchange = (0.025428 - 0.024796) + 0.045
    assert c["exchange_fees"] == round(exchange, 2)
    assert c["builder_fees"] == round(0.024796, 2)
    assert h["minus_exchange_fees"] == round(0.07722 - 1.5 - exchange, 2)
    assert h["true_net"] == round(0.07722 - 1.5 - exchange - 0.024796 - 0.2, 2)
    assert s["crossing"]["taker_fills"] == 1 and s["crossing"]["measured_against_recorded_book"] == 0


if __name__ == "__main__":
    test_three_headlines()
    print("ok  test_three_headlines")
