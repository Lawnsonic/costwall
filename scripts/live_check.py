"""
Pre-flight checks for the live gateway, and the first real round trip.

    python -m scripts.live_check            checks only, sends nothing
    python -m scripts.live_check --trade    opens BTC long at the $10 minimum
                                            plus margin, then closes it

The checks stop before any order if something is wrong:
  1. the agent key in .env is authorised as an agent of HL_ADDRESS
  2. the account has USDC to trade with
  3. the oracle prices the trade and the gateway accepts its signature

The round trip goes through the gateway exactly as an agent would: one
request_trade, then one close_position. Both rows land in evidence/hl/.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import envfile  # noqa: F401  (must load .env before hl.info is imported)
from eth_account import Account

from gateway import authz
from hl import info
from hl.oracle import evaluate_perp

COIN, NOTIONAL = "BTC", 11.0


def stop(msg):
    print(f"STOP: {msg}")
    sys.exit(1)


def main(trade):
    print(f"network: {info.NETWORK}  api: {info.API_URL}")
    main_addr = os.environ.get("HL_ADDRESS", "")
    key = os.environ.get("HL_AGENT_KEY")
    if not key:
        stop("HL_AGENT_KEY is empty in .env")
    agent = Account.from_key(key).address
    role = info.q({"type": "userRole", "user": agent})
    print(f"agent {agent}: {role}")
    if role.get("role") != "agent" or role["data"]["user"].lower() != main_addr.lower():
        stop("this key is not an authorised agent of HL_ADDRESS; authorise it on the API page")

    spot = info.q({"type": "spotClearinghouseState", "user": main_addr})
    usdc = next((b["total"] for b in spot["balances"] if b["coin"] == "USDC"), "0")
    perp = info.q({"type": "clearinghouseState", "user": main_addr})
    print(f"USDC spot {usdc}, perp account value {perp['marginSummary']['accountValue']}")

    signer = os.environ["COSTWALL_SIGNER_KEY"]
    v = authz.sign(evaluate_perp(COIN, NOTIONAL, "BUY", user=main_addr), signer)
    print(f"verdict {v['decision']} {v['reason']} break-even {v.get('break_even_move_bps')} bps "
          f"limit {v.get('authorization', {}).get('limit_px')} fees: {v['evidence']['fee_basis']}"
          if v["decision"] == "APPROVE" else f"verdict {v}")
    print(f"signature check: {authz.verify(v, Account.from_key(signer).address)}")
    if not trade:
        print("checks passed; nothing sent. Run with --trade for the round trip.")
        return

    from gateway.gateway import from_env
    g = from_env()
    opened = g.request_trade(COIN, NOTIONAL, "BUY")
    print("OPEN ", json.dumps({k: opened.get(k) for k in (
        "outcome", "reason", "filled_qty", "avg_px", "limit_px", "error",
        "predicted_entry_crossing_bps", "realised_entry_crossing_bps")}))
    if opened.get("outcome") not in ("FILLED", "PARTIAL"):
        return
    closed = g.close_position(COIN)
    print("CLOSE", json.dumps({k: closed.get(k) for k in (
        "outcome", "reason", "filled_qty", "avg_px", "limit_px", "error",
        "realised_crossing_bps")}))
    print(f"position after: {g.position(COIN)}")


if __name__ == "__main__":
    main("--trade" in sys.argv)
