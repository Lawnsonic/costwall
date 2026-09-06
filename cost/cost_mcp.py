"""
costcheck: an MCP server that prices a proposed trade before it is placed.

    python cost_mcp.py

Launched by the client over stdio. Registration is a command and an args
pair in whatever config file the client reads; see the MCP server section
of the README. Nothing here is specific to one agent harness.

One tool, stdio transport, no port, no OAuth, no credentials. It reads public
order books and does arithmetic. It cannot place an order, cannot move funds,
and holds no keys, so the worst a compromised copy of it can do is quote you
a bad number, which is also the reason it is safe to leave connected.

WHAT IT IS FOR
--------------
An agent connected to Binance Agent OS can place real orders. It reasons in
sentences, and the loss lives in basis points. This gives it the number.

The tool returns a decision object rather than prose, because prose is the
failure mode: a paragraph explaining that a trade is expensive is something a
model can talk itself past, whereas `"decision": "REJECT", "shortfall_bps":
30.29` is not. The arithmetic arrives in the context as a value, not as
something the model was supposed to remember or derive.

WHAT IT IS NOT
--------------
It is not a security boundary, and pretending otherwise would be the most
dangerous claim in this repository. The agent still holds `spot_newOrder`. It
can call this tool, read REJECT, and place the order anyway; nothing here can
stop it. This is an advisory layer enforced by policy, and the policy is a
line in CLAUDE.md that a model can ignore.

Making it non-bypassable means the agent never holding the raw order tool at
all: it calls a gateway, the gateway prices the trade, and only the gateway
can reach Binance. That is a different piece of software from this one and it
is not built here. What is built here is the arithmetic such a gateway would
have to run, which is the part that has to be right first.

WHY EVERY FAILURE RETURNS A REFUSAL
-----------------------------------
An exception reaching the agent is worse than useless, because a model that
asked for a cost and got an error will often shrug and continue. So every
path out of this file is a decision object, and every path that could not
finish the arithmetic is a REJECT. Fail closed. The one thing this tool must
never do is stay silent and let the order through.
"""

import os
import sys
import traceback
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from mcp.server.mcpserver import MCPServer

try:
    from cost import cost_oracle, override
except ImportError:
    import cost_oracle
    import override

# stdio transport puts the JSON-RPC stream on stdout, so anything else printed
# there corrupts the protocol. Nothing in this project prints on import, but a
# future dependency might, so stdout is pointed at stderr for the duration of
# the import-time work and restored for the server itself.
_real_stdout = sys.stdout
sys.stdout = sys.stderr

server = MCPServer(
    name="costcheck",
    version="1.0.0",
    instructions=(
        "Pre-trade cost oracle for Binance spot and USD-M futures. Call "
        "evaluate_trade before placing any order. It prices two different "
        "trades and you must tell it which one you mean: pass side=BUY or "
        "side=SELL for a single-leg spot conversion, or omit side for a "
        "delta-neutral funding carry (long spot, short perp). Pricing a plain "
        "conversion as a carry produces a large and meaningless refusal, "
        "because a conversion earns no funding and has no second leg. "
        "It returns a structured verdict with the cost breakdown measured "
        "against live order books at the requested size. Treat "
        "decision=REJECT as binding and do not place the order. A decision is "
        "only valid until its expires_at timestamp, which is seconds away by "
        "design: if it has expired, call again rather than acting on it. "
        "If a human explicitly overrides a refusal, call record_override "
        "before sending the order so the decision that was overruled is "
        "preserved. Never invoke that override on your own initiative."
    ),
)


def _refusal(symbol, reason, detail):
    """A decision object for the cases where there is no arithmetic to show."""
    now = datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    expiry = (now + timedelta(seconds=cost_oracle.TTL_SECONDS)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    return {
        "schema_version": cost_oracle.SCHEMA_VERSION,
        "decision": "REJECT",
        "reason": reason,
        "detail": detail,
        "symbol": symbol,
        "measured_at": stamp,
        "expires_at": expiry,
        "ttl_seconds": cost_oracle.TTL_SECONDS,
        "max_notional_usdt": 0.0,
    }


@server.tool(
    name="evaluate_trade",
    title="Price a proposed trade against live books",
    description=(
        "Price a proposed Binance trade at the size actually being traded, "
        "against order books read at the moment of the call. Prices two "
        "different trades, selected by whether you pass a side.\n\n"
        "side=BUY or side=SELL prices a SINGLE-LEG SPOT CONVERSION: one "
        "crossing, cost = taker fee + distance from mid to the fill VWAP, "
        "checked against a cost ceiling. Use this for a plain buy or sell.\n\n"
        "Omitting side prices a DELTA-NEUTRAL FUNDING CARRY (long spot, short "
        "USD-M perp): four crossings, cross-venue entry basis measured at "
        "size, exit spread, lot-step residual, checked against expected "
        "funding. Use this only when actually hedging.\n\n"
        "Returns a decision object: APPROVE or REJECT, the cost stack in "
        "basis points, and an expiry a few seconds out. REJECT is binding."
    ),
)
def evaluate_trade(
    symbol: str,
    notional_usdt: float = 5.0,
    side: str = None,
    strategy: str = "auto",
    hold_periods: int = 3,
    min_edge_bps: float = 10.0,
    max_cost_bps: float = 50.0,
) -> dict:
    """
    Args:
        symbol: Binance symbol, e.g. BNBUSDT. A carry additionally requires a
            USD-M listing; a conversion needs only the spot pair.
        notional_usdt: Intended size. Sized up to the venue minimum if it is
            below it, and the object says when that happened, because a quote
            for a size the venue will not accept is not a quote.
        side: BUY or SELL for a single-leg spot conversion. Omit for a hedge.
            This is what selects the model, so passing it when you mean a
            hedge, or omitting it when you mean a plain buy, prices the wrong
            trade.
        strategy: "auto" (default) infers from side, "conversion" or "carry"
            to be explicit. "conversion" without a side is refused rather than
            guessed.
        hold_periods: Carry only. 8h funding settlements underwritten.
        min_edge_bps: Carry only. Profit required above all costs to APPROVE.
        max_cost_bps: Conversion only. Cost ceiling above which the fill is
            refused as a bad price. A conversion earns nothing, so it is
            tested against this rather than against an edge requirement.
    """
    try:
        return cost_oracle.evaluate(
            symbol=symbol,
            notional_usdt=notional_usdt,
            side=side,
            strategy=strategy,
            hold_periods=hold_periods,
            min_edge_bps=min_edge_bps,
            max_cost_bps=max_cost_bps,
        )
    except Exception as exc:                          # noqa: BLE001
        # Deliberately broad. A network timeout, a delisted symbol and a bug
        # in this file all mean the same thing to the caller: the cost of this
        # trade is currently unknown, and an unknown cost is not a green light.
        traceback.print_exc(file=sys.stderr)
        return _refusal(
            symbol.upper().strip() if isinstance(symbol, str) else str(symbol),
            "pricing_failed",
            f"{type(exc).__name__}: {exc}. The cost of this trade could not be "
            f"established, so it is refused. This is not a signal that the "
            f"trade is bad, only that it is unpriced.",
        )


@server.tool(
    name="record_override",
    title="Record that a cost verdict was overridden by a human",
    description=(
        "Append one override to the audit log, embedding the decision object "
        "that was overruled so the refusal survives the thing that ignored "
        "it. Call this ONLY when a human has explicitly overridden a cost "
        "check in their own message (e.g. 'proceed anyway', 'override', 'force', "
        "or 'NCC'), and call it BEFORE sending the order, not after. It authorises nothing: "
        "it cannot approve a trade, cannot place an order, and returns no "
        "permission. It is a record.\n\n"
        "IMPORTANT AND DELIBERATE LIMITATION: this server cannot see the "
        "human's message and therefore cannot verify the phrase was said. It "
        "takes the calling agent's word for it and stamps every record "
        "phrase_verified=false. Do not describe this as an enforced control. "
        "Never invoke it on your own initiative."
    ),
)
def record_override(
    symbol: str,
    side: str = None,
    notional_usdt: float = None,
    verdict: dict = None,
    user_phrase: str = "override",
    note: str = None,
) -> dict:
    """
    Args:
        symbol: Symbol the override applies to, e.g. BNBUSDT.
        side: BUY or SELL, if the overridden trade had a direction.
        notional_usdt: Size the human authorised.
        verdict: The full decision object evaluate_trade returned, passed
            through unchanged. Omitting it records an unpriced override, which
            is a worse kind, and the record says so.
        user_phrase: The literal phrase the human used. Reported, not verified.
        note: Anything else worth having in the log.
    """
    try:
        rec = override.record(
            symbol=symbol,
            side=side,
            notional_usdt=notional_usdt,
            verdict=verdict,
            user_phrase=user_phrase,
            note=note,
        )
        rec["logged"] = True
        return rec
    except Exception as exc:                          # noqa: BLE001
        # An override that could not be written down must not read as a
        # success. The caller is told the audit trail failed, so it can stop
        # rather than trade with no record.
        traceback.print_exc(file=sys.stderr)
        return {
            "schema_version": override.SCHEMA_VERSION,
            "event": "override",
            "logged": False,
            "decision": "LOG_FAILED",
            "reason": "override_not_recorded",
            "symbol": symbol,
            "detail": f"{type(exc).__name__}: {exc}. The override could not be "
                      f"written to the audit log. Do not treat this as "
                      f"authorisation.",
        }


if __name__ == "__main__":
    sys.stdout = _real_stdout
    server.run("stdio")
