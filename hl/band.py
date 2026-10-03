"""
Where an xyz market sits inside its discovery band, rebuilt from recorded prices.

During an internal session trade.xyz holds the mark within +/- bound of a
reference price. The reference starts at the last external oracle price (the
Friday close for weekday markets) and re-anchors one bound outward each time
the oracle reaches a trigger, up to a per-market number of resets, after which
the bound is a hard cap until external pricing resumes. None of this is in the
API, so it is rebuilt here from the recorder's per-minute oracle prices:

    reference  = last oracle price recorded during an external session
    triggers   = reference x (1 +/- bound x threshold)
    re-anchor  = reference moves to the bound it triggered; counter +1

LIMITS, STATED RATHER THAN HIDDEN
---------------------------------
- Replayed from 60-second snapshots. A trigger touched and left between two
  snapshots is missed, so the reconstructed reference can lag the real one.
- The trigger threshold is published only as an example (90% for WTIOIL). It
  is ASSUMED to be 90% for every market.
- If the recorder was not running when the external session ended, there is no
  reference and the band is reported unavailable, never guessed.
"""

import glob
import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hl import sessions

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ORACLE_DIR = os.path.join(ROOT, "data", "oracle")

THRESHOLD = Decimal("0.9")  # ASSUMED for all markets; see module docstring
LOOKBACK_DAYS = 5           # long enough to reach back over a holiday weekend
BPS = Decimal("10000")


def _series(coin, dex, now):
    """[(ts, oracle_px)] for one coin, oldest first, from recorded files."""
    out = []
    first = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    for path in sorted(glob.glob(os.path.join(ORACLE_DIR, "*.jsonl.gz"))):
        if os.path.basename(path)[:10] < first:
            continue
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row["dex"] == dex and coin in row["px"]:
                    out.append((datetime.fromisoformat(row["ts"]), Decimal(row["px"][coin])))
    out.sort(key=lambda x: x[0])
    return [p for p in out if p[0] <= now]


def discovery_band(coin, entry, mark_px, now=None):
    """Band state for an xyz coin in an internal session. entry is its registry row."""
    now = now or datetime.now(timezone.utc)
    bound, resets = entry.get("discovery_bound"), entry.get("resets")
    if bound is None or resets is None:
        return {"available": False, "why": "bound or reset count not published for this market"}
    bound = Decimal(str(bound))
    series = _series(coin, "xyz", now)

    last_ext = None
    for i, (ts, _) in enumerate(series):
        if sessions.session(entry["schedule"], ts)[0] == sessions.EXTERNAL:
            last_ext = i
    if last_ext is None:
        since = series[0][0].isoformat(timespec="minutes") if series else "never"
        return {"available": False,
                "why": "no oracle price recorded during the last external session "
                       f"(recording for this coin starts {since})"}

    ref_ts, origin = series[last_ext]
    ref, up, down = origin, 0, 0
    for _, px in series[last_ext + 1:]:
        while up < resets and px >= ref * (1 + bound * THRESHOLD):
            ref, up = ref * (1 + bound), up + 1
        while down < resets and px <= ref * (1 - bound * THRESHOLD):
            ref, down = ref * (1 - bound), down + 1

    lower, upper = ref * (1 - bound), ref * (1 + bound)
    mark = Decimal(mark_px)
    return {
        "available": True,
        "reference_px": str(round(ref, 6)),
        "origin_external_px": str(origin),
        "origin_recorded_at": ref_ts.isoformat(timespec="seconds"),
        "bound": float(bound),
        "lower_px": str(round(lower, 6)),
        "upper_px": str(round(upper, 6)),
        "resets_used_up": up,
        "resets_used_down": down,
        "resets_allowed_each_way": resets,
        "hard_cap_up": up >= resets,
        "hard_cap_down": down >= resets,
        "mark_to_upper_bps": float(round((upper - mark) / mark * BPS, 1)),
        "mark_to_lower_bps": float(round((mark - lower) / mark * BPS, 1)),
        "method": "replayed from 60s recorded oracle prices; trigger threshold ASSUMED 90%",
    }
