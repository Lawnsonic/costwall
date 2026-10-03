"""
Offline checks for the session calendar and the discovery-band replay.

The band test replays trade.xyz's own worked WTIOIL example (Discovery Bounds
page): reference 100, bound 5%, threshold 90%, two resets. The published path
is 100 -> 105 -> 110.25, after which the upper bound 115.7625 is a hard cap.

Run:  python -m tests.test_sessions_band
"""

import gzip
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from hl import band
from hl.sessions import EXTERNAL, INTERNAL, session


def U(*a):
    return datetime(*a, tzinfo=timezone.utc)


SESSION_CASES = [
    ("Sat afternoon", U(2026, 10, 3, 18, 0), "us_equity_24_5", INTERNAL),
    ("Mon 10:00 EDT", U(2026, 10, 5, 14, 0), "us_equity_24_5", EXTERNAL),
    ("Mon 03:00 EDT overnight", U(2026, 10, 5, 7, 0), "us_equity_24_5", EXTERNAL),
    ("Fri 20:30 EDT", U(2026, 10, 10, 0, 30), "us_equity_24_5", INTERNAL),
    ("Sun 19:59 EDT", U(2026, 10, 4, 23, 59), "us_equity_24_5", INTERNAL),
    ("Sun 20:01 EDT", U(2026, 10, 5, 0, 1), "us_equity_24_5", EXTERNAL),
    ("Thanksgiving 10:00 EST", U(2026, 11, 26, 15, 0), "us_equity_24_5", INTERNAL),
    ("Wed before Thanksgiving 21:00", U(2026, 11, 26, 2, 0), "us_equity_24_5", INTERNAL),
    ("Fri after Thanksgiving 14:00", U(2026, 11, 27, 19, 0), "us_equity_24_5", INTERNAL),
    ("Mon Nov 2 10:00 EST (after DST)", U(2026, 11, 2, 15, 0), "us_equity_24_5", EXTERNAL),
    ("futures Tue 17:30 break", U(2026, 10, 6, 21, 30), "futures", INTERNAL),
    ("futures Tue 18:30", U(2026, 10, 6, 22, 30), "futures", EXTERNAL),
    ("fx Fri 16:59", U(2026, 10, 9, 20, 59), "fx", EXTERNAL),
    ("fx Fri 17:00", U(2026, 10, 9, 21, 0), "fx", INTERNAL),
    ("unknown schedule", U(2026, 10, 5, 14, 0), "unknown", INTERNAL),
]


def test_sessions():
    for name, t, schedule, want in SESSION_CASES:
        got = session(schedule, t)[0]
        assert got == want, f"{name}: {got} != {want}"


def test_band_matches_published_wtioil_example():
    # Fri 2026-10-09 16:59 EDT is the last external minute for a futures market.
    close = U(2026, 10, 9, 20, 59)
    path = [(close, "100")] + [
        (close + timedelta(hours=h), px)
        for h, px in [(2, "103"), (5, "104.6"), (9, "107"), (14, "109.8"), (20, "115")]
    ]
    entry = {"schedule": "futures", "discovery_bound": 0.05, "resets": 2}
    with tempfile.TemporaryDirectory() as d:
        with gzip.open(os.path.join(d, "2026-10-09.jsonl.gz"), "wt", encoding="utf-8") as f:
            for ts, px in path:
                f.write(json.dumps({"ts": ts.isoformat(), "dex": "xyz", "px": {"xyz:CL": px}}) + "\n")
        old = band.ORACLE_DIR
        band.ORACLE_DIR = d
        try:
            out = band.discovery_band("xyz:CL", entry, "115", now=close + timedelta(hours=21))
        finally:
            band.ORACLE_DIR = old
    assert out["available"], out
    assert out["origin_external_px"] == "100"
    assert out["reference_px"] == "110.250000", out["reference_px"]
    assert out["upper_px"] == "115.762500", out["upper_px"]
    assert out["lower_px"] == "104.737500", out["lower_px"]
    assert out["resets_used_up"] == 2 and out["hard_cap_up"] is True
    assert out["resets_used_down"] == 0 and out["hard_cap_down"] is False


def test_band_unavailable_without_external_reference():
    with tempfile.TemporaryDirectory() as d:
        old = band.ORACLE_DIR
        band.ORACLE_DIR = d
        try:
            out = band.discovery_band("xyz:CL", {"schedule": "futures", "discovery_bound": 0.05,
                                                 "resets": 2}, "100", now=U(2026, 10, 10, 12, 0))
        finally:
            band.ORACLE_DIR = old
    assert out["available"] is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
