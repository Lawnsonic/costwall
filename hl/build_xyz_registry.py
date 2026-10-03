"""
Builds hl/xyz_registry.json from trade.xyz's published Specification Index.

The session schedule and discovery-bound settings of each xyz market are not
in the Hyperliquid API. They are in trade.xyz's docs, in one table. This reads
that table rather than retyping it, keeps the original text next to every
parsed value, and maps each market's "External Session Hours" text onto one of
the schedules hl/sessions.py knows. A schedule it cannot recognise is stored as
"unknown", and the oracle refuses those by default: an unknown session means
an unknown price source.

Run:  python -m hl.build_xyz_registry
"""

import html
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "xyz_registry.json")
SOURCE = "https://docs.trade.xyz/perpetuals/specifications-and-schedules/specification-index.md"

# External Session Hours text -> schedule key in sessions.py. Matched after
# collapsing whitespace. Anything not listed maps to "unknown".
SCHEDULES = {
    "24/5, from Sunday 8:00 PM ET to Friday 8:00 PM ET": "us_equity_24_5",
    "From Sunday 6PM ET to Friday 5PM ET": "futures",
    "From Sunday 6:00 PM ET to Friday 5:00 PM ET": "futures",
    "From Sunday 5PM ET to Friday 5PM ET": "fx",
}

# Where the docs and the API name the same market differently. Docs name on
# the left, API name (without "xyz:") on the right. Found by diffing the two.
ALIASES = {
    "WTIOIL": "CL",
    "SAMSUNG": "SMSN",
    "SKHYNIX": "SKHX",
}


def _cells(row):
    raw = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
    return [" ".join(re.sub(r"<[^>]+>", " ", html.unescape(c)).split()) for c in raw]


def _pct(text):
    m = re.search(r"([\d.]+)\s*%", text)
    return float(m.group(1)) / 100 if m else None


def build():
    # The docs host returns 403 to urllib's default user agent.
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "costwall/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        doc = r.read().decode("utf-8").split("# Agent Instructions")[0]
    rows = re.findall(r"<tr>(.*?)</tr>", doc, re.S)
    header = _cells(rows[0])
    col = {name: i for i, name in enumerate(header)}
    markets = {}
    for row in rows[1:]:
        c = _cells(row)
        if len(c) < len(header):
            continue
        name = ALIASES.get(c[col["Instrument"]], c[col["Instrument"]])
        ext = c[col["External Session Hours"]]
        resets = c[col["Discovery Bound Resets"]]
        markets[f"xyz:{name}"] = {
            "schedule": SCHEDULES.get(ext, "unknown"),
            "max_leverage": c[col["Max Leverage"]],
            "discovery_bound": _pct(c[col["Discovery Bound"]]),
            "resets": int(resets) if resets.isdigit() else None,
            "funding_multiplier": c[col["Funding Rate Multiplier"]],
            "external_hours_text": ext,
            "internal_hours_text": c[col["Internal Session Hours"]],
        }
    return {
        "source": SOURCE,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "markets": markets,
    }


if __name__ == "__main__":
    reg = build()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=1, ensure_ascii=False)
    counts = {}
    for m in reg["markets"].values():
        counts[m["schedule"]] = counts.get(m["schedule"], 0) + 1
    print(f"{len(reg['markets'])} markets -> {OUT}  {counts}")
