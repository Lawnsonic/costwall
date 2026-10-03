"""
The gateway: the only thing that holds the trading key.

WHY IT EXISTS
-------------
The Binance build ended with this sentence in its README: "Making the check
unbypassable requires a gateway that holds the credentials and refuses to
forward an unpriced order, which is not built." This is that gateway. The
agent never sees a key. It can ask for two things, and nothing else:

  request_trade   open or add to a position. Priced by the oracle first. The
                  order goes out only with a valid, unexpired oracle signature
                  matching the request, as one IOC limit at the signed price,
                  so it fills inside the priced depth or not at all.
  close_position  reduce a position. Never blocked: a cost check that could
                  trap you in a position would be more dangerous than none.
                  Sent reduce-only, so a "close" can never open or flip
                  anything. Its cost is still measured and logged.

The key it holds is a Hyperliquid API (agent) wallet. Hyperliquid lets agent
wallets trade on the account's behalf but not withdraw, so even a compromised
gateway cannot move funds out.

Every verdict, order and fill is appended to evidence/hl/ as JSONL.
"""

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import envfile  # noqa: F401  (loads .env before hl.info reads HL_NETWORK)
from gateway import authz
from hl import info, venue
from hl.oracle import evaluate_perp

EVIDENCE = os.path.join(ROOT, "evidence", "hl")
BPS = Decimal("10000")

# How far through the book a close may reach. A close is never refused, but an
# unbounded market order on a thin book is how a close becomes a disaster; this
# caps the damage and leaves the rest of the position open if it is hit.
CLOSE_MAX_SLIPPAGE = Decimal("0.02")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _log(name, row):
    os.makedirs(EVIDENCE, exist_ok=True)
    with open(os.path.join(EVIDENCE, f"{name}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")


def parse_order_response(resp):
    """Hyperliquid order response -> (filled_sz, avg_px, oid, error)."""
    if not isinstance(resp, dict) or resp.get("status") != "ok":
        return Decimal(0), None, None, f"exchange_error: {resp}"
    statuses = resp["response"]["data"]["statuses"]
    st = statuses[0] if statuses else {}
    if "filled" in st:
        f = st["filled"]
        return Decimal(f["totalSz"]), Decimal(f["avgPx"]), f.get("oid"), None
    if "error" in st:
        return Decimal(0), None, None, st["error"]
    if "resting" in st:  # cannot happen for IOC; recorded if it ever does
        return Decimal(0), None, st["resting"].get("oid"), "unexpected_resting_order"
    return Decimal(0), None, None, f"unrecognised_status: {st}"


class Gateway:
    def __init__(self, exchange, account_address, trusted_signer, signer_key=None,
                 evaluate=evaluate_perp, builder=None):
        """
        exchange        hyperliquid.exchange.Exchange built with the AGENT key
        account_address the main account the agent trades for
        trusted_signer  oracle address whose signatures this gateway accepts
        signer_key      oracle signing key, only when the oracle runs in-process
        evaluate        oracle callable; swap for an HTTP client when hosted
        builder         optional {"b": address, "f": tenths_of_bp} builder code
        """
        self.exchange = exchange
        self.account = account_address
        self.trusted_signer = trusted_signer
        self.signer_key = signer_key
        self.evaluate = evaluate
        self.builder = builder

    def _refuse(self, request, reason, verdict=None, **extra):
        row = {"ts": _now(), "request": request, "outcome": "REFUSED", "reason": reason,
               "verdict": verdict, **extra}
        _log("refusals", row)
        return row

    def request_trade(self, coin, notional_usd, side, **oracle_kwargs):
        request = {"action": "request_trade", "coin": coin, "notional_usd": notional_usd,
                   "side": side, **oracle_kwargs}
        if self.builder:
            # The builder fee this gateway will charge is part of the cost.
            oracle_kwargs.setdefault("builder_fee", Decimal(self.builder["f"]) / 10)
        verdict = self.evaluate(coin, notional_usd, side, user=self.account, **oracle_kwargs)
        if self.signer_key:
            authz.sign(verdict, self.signer_key)
        _log("verdicts", verdict)

        if verdict.get("decision") != "APPROVE":
            return self._refuse(request, verdict.get("reason"), verdict,
                                shortfall_bps=verdict.get("shortfall_bps"))
        ok, why = authz.verify(verdict, self.trusted_signer)
        if not ok:
            return self._refuse(request, f"authorization_{why}", verdict)
        a = verdict["authorization"]
        if a["coin"] != coin or a["is_buy"] != (str(side).upper() == "BUY"):
            return self._refuse(request, "authorization_mismatch", verdict)

        resp = self.exchange.order(coin, a["is_buy"], float(a["qty"]), float(a["limit_px"]),
                                   {"limit": {"tif": "Ioc"}}, reduce_only=False,
                                   builder=self.builder)
        filled, avg_px, oid, err = parse_order_response(resp)
        mid = Decimal(verdict["evidence"]["mid"])
        row = {
            "ts": _now(), "action": "open", "coin": coin, "side": side,
            "requested_qty": a["qty"], "limit_px": a["limit_px"],
            "filled_qty": str(filled), "avg_px": str(avg_px) if avg_px else None,
            "oid": oid, "error": err,
            "predicted_entry_crossing_bps": verdict["cost_bps"]["entry_crossing"],
            "realised_entry_crossing_bps": (float(round(abs(avg_px - mid) / mid * BPS, 2))
                                            if avg_px else None),
            "verdict_hash": "0x" + authz.verdict_hash(verdict).hex(),
            "exchange_response": resp,
        }
        row["outcome"] = ("FILLED" if filled == Decimal(a["qty"]) else
                          "PARTIAL" if filled > 0 else "NO_FILL")
        _log("trades", row)
        return row

    def position(self, coin):
        """Signed size of the account's position in coin (negative = short)."""
        dex, _ = venue.split_coin(coin)
        body = {"type": "clearinghouseState", "user": self.account}
        if dex:
            body["dex"] = dex
        for p in info.q(body).get("assetPositions", []):
            if p["position"]["coin"] == coin:
                return Decimal(p["position"]["szi"])
        return Decimal(0)

    def close_position(self, coin, fraction=1.0):
        request = {"action": "close_position", "coin": coin, "fraction": fraction}
        szi = self.position(coin)
        if szi == 0:
            return self._refuse(request, "no_position")
        spec = venue.market(coin)
        frac = min(max(Decimal(str(fraction)), Decimal(0)), Decimal(1))
        qty = venue.round_size(spec, abs(szi) * frac)
        if qty == 0:
            return self._refuse(request, "size_rounds_to_zero")
        is_buy = szi < 0
        mid = spec["mid_px"] or spec["mark_px"]
        bound = mid * (1 + CLOSE_MAX_SLIPPAGE) if is_buy else mid * (1 - CLOSE_MAX_SLIPPAGE)
        limit_px = venue.round_price(spec, bound, is_buy)
        resp = self.exchange.order(coin, is_buy, float(qty), float(limit_px),
                                   {"limit": {"tif": "Ioc"}}, reduce_only=True,
                                   builder=self.builder)
        filled, avg_px, oid, err = parse_order_response(resp)
        row = {
            "ts": _now(), "action": "close", "coin": coin, "position_before": str(szi),
            "requested_qty": str(qty), "limit_px": str(limit_px), "reduce_only": True,
            "filled_qty": str(filled), "avg_px": str(avg_px) if avg_px else None,
            "oid": oid, "error": err,
            "realised_crossing_bps": (float(round(abs(avg_px - mid) / mid * BPS, 2))
                                      if avg_px else None),
            "note": "closes are never refused by the cost check; cost is measured, not gated",
            "exchange_response": resp,
        }
        row["outcome"] = ("FILLED" if filled == qty else "PARTIAL" if filled > 0 else "NO_FILL")
        _log("trades", row)
        return row


def from_env():
    """Build a live gateway from environment variables.

    HL_NETWORK               testnet or mainnet, required
    HL_ADDRESS               main account address
    HL_AGENT_KEY             agent (API) wallet private key: can trade, cannot withdraw
    COSTWALL_SIGNER_KEY      oracle signing key (in-process oracle)
    COSTWALL_SIGNER_ADDRESS  oracle address to trust (defaults to the signer key's)
    """
    from eth_account import Account
    from hyperliquid.exchange import Exchange

    # No default here, unlike the read-only oracle: a gateway that can trade
    # must be told which network, so it never reaches mainnet by omission.
    if os.environ.get("HL_NETWORK") not in ("testnet", "mainnet"):
        raise SystemExit("set HL_NETWORK=testnet or HL_NETWORK=mainnet explicitly")
    agent = Account.from_key(os.environ["HL_AGENT_KEY"])
    signer_key = os.environ.get("COSTWALL_SIGNER_KEY")
    trusted = os.environ.get("COSTWALL_SIGNER_ADDRESS") or (
        Account.from_key(signer_key).address if signer_key else None)
    if not trusted:
        raise SystemExit("set COSTWALL_SIGNER_ADDRESS or COSTWALL_SIGNER_KEY")
    ex = Exchange(agent, info.API_URL, account_address=os.environ["HL_ADDRESS"],
                  perp_dexs=["", "xyz"])
    return Gateway(ex, os.environ["HL_ADDRESS"], trusted, signer_key=signer_key)
