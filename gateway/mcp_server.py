"""
costwall: the MCP server an agent connects to.

    python -m gateway.mcp_server                     stdio, for a local agent
    python -m gateway.mcp_server --http --port 8000  hosted, read-only

TWO MODES, DECIDED BY WHAT KEYS ARE PRESENT
-------------------------------------------
Read-only (no HL_AGENT_KEY): one tool, evaluate_trade. Prices a trade, holds
no keys, cannot place an order. This is what a hosted copy runs, so anyone
can add it by URL and the worst a compromised copy can do is quote a bad
number.

Gateway (HL_AGENT_KEY and HL_NETWORK set): adds request_trade,
close_position and get_position. The agent connected to this server gets no
raw order tool. The only way it can open a position is request_trade, which
prices first and sends only a signed, unexpired approval. That is the
difference from the Binance build, where the same check was advice the agent
could read and ignore.

Every failure is returned as a refusal object, never an exception, because a
model that gets an error tends to carry on, and a model that gets
"decision": "REJECT" does not.
"""

import argparse
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import envfile  # noqa: F401  (loads .env before hl.info reads HL_NETWORK)
from mcp.server.mcpserver import MCPServer

# stdio carries JSON-RPC on stdout; keep import-time output off it.
_real_stdout = sys.stdout
sys.stdout = sys.stderr

from hl.oracle import evaluate_perp

GATEWAY_MODE = bool(os.environ.get("HL_AGENT_KEY"))

INSTRUCTIONS = (
    "Pre-trade cost wall for Hyperliquid perps, including HIP-3 stock, index and "
    "commodity markets (coin names like 'xyz:TSLA'). evaluate_trade prices a "
    "one-direction trade against the live order book at the real size and returns "
    "break_even_move_bps: how far price must move in your favour before the trade "
    "has paid its crossing, fees, builder fee and funding. decision=REJECT is "
    "binding. A verdict expires in seconds; call again rather than act on an old one. "
    "Stock perps priced by their own book while the real exchange is closed are "
    "refused unless you pass accept_internal_price=true deliberately."
)
if GATEWAY_MODE:
    INSTRUCTIONS += (
        " This server is the gateway: request_trade is the only way to open a "
        "position and close_position the only way to reduce one. Closes are never "
        "refused."
    )

server = MCPServer(name="costwall", version="2.0.0", instructions=INSTRUCTIONS)


def _fail(reason, exc):
    traceback.print_exc(file=sys.stderr)
    return {"decision": "REJECT", "outcome": "REFUSED", "reason": reason,
            "detail": f"{type(exc).__name__}: {exc}"}


@server.tool(
    name="evaluate_trade",
    title="Price a Hyperliquid perp trade against the live book",
    description=(
        "Price opening a long (side=BUY) or short (side=SELL) on a Hyperliquid perp "
        "at notional_usd, against the order book read now. Returns APPROVE or REJECT, "
        "the cost stack in bps, and break_even_move_bps. Pass expected_move_bps to "
        "test the trade against the move you expect (it must clear cost plus 10 bps); "
        "otherwise it is held to a 50 bps cost ceiling. hold_hours defaults to 8 "
        "(funding is hourly). builder_fee_bps is what your framework charges per fill."
    ),
)
def evaluate_trade(coin: str, notional_usd: float, side: str, hold_hours: float = None,
                   expected_move_bps: float = None, builder_fee_bps: float = None,
                   accept_internal_price: bool = False) -> dict:
    try:
        return evaluate_perp(coin, notional_usd, side, hold_hours, expected_move_bps,
                             builder_fee_bps, accept_internal_price=accept_internal_price)
    except Exception as exc:
        return _fail("pricing_failed", exc)


if GATEWAY_MODE:
    from gateway.gateway import from_env

    _gateway = from_env()

    @server.tool(
        name="request_trade",
        title="Open or add to a position, if it clears its cost",
        description=(
            "Ask the gateway to open a long (BUY) or short (SELL). The gateway prices "
            "it, and only if the verdict is APPROVE and validly signed sends one "
            "immediate-or-cancel limit order at the approved price. Returns the "
            "outcome (FILLED, PARTIAL, NO_FILL or REFUSED) with the verdict or fill."
        ),
    )
    def request_trade(coin: str, notional_usd: float, side: str, hold_hours: float = None,
                      expected_move_bps: float = None,
                      accept_internal_price: bool = False) -> dict:
        try:
            return _gateway.request_trade(coin, notional_usd, side, hold_hours=hold_hours,
                                          expected_move_bps=expected_move_bps,
                                          accept_internal_price=accept_internal_price)
        except Exception as exc:
            return _fail("gateway_failed", exc)

    @server.tool(
        name="close_position",
        title="Reduce or close a position (never refused)",
        description=(
            "Close fraction (0-1, default 1) of the position in coin with a reduce-only "
            "immediate-or-cancel order, at most 2% through the mid. Never blocked by "
            "the cost check; the cost is measured and logged."
        ),
    )
    def close_position(coin: str, fraction: float = 1.0) -> dict:
        try:
            return _gateway.close_position(coin, fraction)
        except Exception as exc:
            return _fail("gateway_failed", exc)

    @server.tool(name="get_position", title="Current position size",
                 description="Signed position size in coin; negative is short.")
    def get_position(coin: str) -> dict:
        try:
            return {"coin": coin, "size": str(_gateway.position(coin))}
        except Exception as exc:
            return _fail("position_failed", exc)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--http", action="store_true", help="serve streamable HTTP (read-only)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    sys.stdout = _real_stdout
    if a.http:
        if GATEWAY_MODE:
            raise SystemExit("refusing to serve the trading gateway over HTTP; "
                             "unset HL_AGENT_KEY for a hosted read-only server")
        server.run("streamable-http", host=a.host, port=a.port, stateless_http=True)
    else:
        server.run("stdio")
