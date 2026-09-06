"""
The override log: what happened when the cost check was overruled.

An override is the human explicitly saying: price it, show me, and place the
order anyway (e.g. "proceed anyway", "override", "force", "buy anyway", or "NCC").
This module is what makes that leave a mark. It does not decide anything and it
cannot approve a trade. It writes down that a verdict existed, what the verdict
said, and that somebody chose to trade past it.

The design rule is that the override never destroys the thing it overrides.
The full decision object goes into the record verbatim, REJECT and all, so a
reconciliation months later reads "the oracle said 51.1 bps short, the human
said go, here is the fill" rather than a gap where a refusal used to be.

WHAT THIS CANNOT DO, STATED PLAINLY
-----------------------------------
It cannot independently verify that you commanded an override.

This runs inside an MCP server launched over stdio by the agent. The only
thing it ever receives is what the agent passes it. It has no access to your
actual message, so `user_phrase` is the agent's REPORT that you gave the
instruction, not cryptographic proof of it. An agent that wanted to trade
without asking could call this with user_phrase="override" and nothing here
would know the difference.

That is the same category of limitation as "REJECT is binding" in CLAUDE.md,
and it is written into every record as `phrase_verified: false` so the log
never overstates itself. A record that claimed to prove human consent it
cannot observe would be worse than no record, because it would be believed.

Closing it needs a channel this process does not have: a harness hook that
reads the human's literal prompt and drops a single-use token the server can
check. That is the override equivalent of the credential-holding gateway described
in cost_mcp.py, and like the gateway, it is named here as unbuilt.
"""

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

OVERRIDES_PATH = os.path.join(ROOT, "evidence", "overrides.jsonl")

SCHEMA_VERSION = "1.0.0"


def _iso(dt):
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def record(symbol, side=None, notional_usdt=None, verdict=None, user_phrase="override",
           note=None, path=None):
    """
    Append one override to the log and hand the record back.

    `verdict` is the decision object the oracle returned, embedded whole. If
    it is None the override happened without pricing, which is a worse kind of
    override, and the record says so rather than leaving the field quietly
    empty.
    """
    path = path or OVERRIDES_PATH
    now = datetime.now(timezone.utc)

    priced = isinstance(verdict, dict) and "decision" in verdict
    phrase = str(user_phrase or "override").strip()
    reason = "user_override_ncc" if phrase.upper() == "NCC" else "user_override"
    rec = {
        "schema_version": SCHEMA_VERSION,
        "event": "override",
        "ts": _iso(now),
        "decision": "BYPASS",
        "reason": reason,
        "symbol": (symbol or "").upper().strip(),
        "side": (side or "").upper().strip() or None,
        "notional_usdt": float(notional_usdt) if notional_usdt is not None else None,
        # The verdict that was overridden, kept whole. This is the point of
        # the file: the refusal survives the thing that ignored it.
        "original_decision": verdict.get("decision") if priced else None,
        "original_reason": verdict.get("reason") if priced else None,
        "measured_cost_bps": (verdict.get("cost_bps", {}) or {}).get("total")
                             if priced else None,
        "shortfall_bps": verdict.get("shortfall_bps") if priced else None,
        "priced": priced,
        # See the module docstring. The agent reports the phrase; nothing here
        # can confirm the human uttered it.
        "user_phrase": phrase,
        "phrase_verified": False,
        "phrase_verification": "not_possible_in_process: the MCP server cannot "
                               "read the human's message and takes the calling "
                               "agent's word for it",
        "scope": "one_order",
        "note": note,
        "verdict": verdict if priced else None,
    }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec


def explain(rec):
    """The record as a human reads it."""
    L = [f"BYPASS  {rec['symbol']}  {rec.get('side') or ''}  "
         f"({rec['reason']})"]
    if rec["priced"]:
        L.append(f"  oracle said {rec['original_decision']} "
                 f"({rec['original_reason']}) at "
                 f"{rec['measured_cost_bps']} bps measured cost")
    else:
        L.append("  no verdict was obtained; this override is unpriced")
    L += [
        f"  phrase {rec['user_phrase']!r} reported by the agent, not verified",
        f"  authorises one order, logged {rec['ts']}",
        f"  -> {OVERRIDES_PATH}",
    ]
    return "\n".join(L)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="Record that a cost verdict was overridden.")
    ap.add_argument("symbol")
    ap.add_argument("--side", choices=["BUY", "SELL"], default=None)
    ap.add_argument("--notional", type=float, default=None)
    ap.add_argument("--verdict", default=None,
                    help="path to a JSON decision object, or - for stdin")
    ap.add_argument("--phrase", default="override")
    ap.add_argument("--note", default=None)
    a = ap.parse_args()

    v = None
    if a.verdict == "-":
        v = json.load(sys.stdin)
    elif a.verdict:
        with open(a.verdict, "r", encoding="utf-8") as fh:
            v = json.load(fh)

    print(explain(record(a.symbol, a.side, a.notional, v, a.phrase, a.note)))
