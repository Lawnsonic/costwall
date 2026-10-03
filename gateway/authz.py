"""
Signed, expiring trade authorizations (EIP-712).

WHY SIGN AT ALL
---------------
On Binance the oracle returned an authorization block and nothing checked it:
anyone holding the order tools could ignore it. Here the oracle signs every
APPROVE with its own key and the gateway, which holds the trading key, will
only place an order that carries a valid signature from the oracle address it
trusts. That splits the two jobs so they can run in different places: the
oracle can be hosted and shared, the gateway runs next to the user's agent
key, and neither has to trust the agent.

What is signed is the order itself (coin, asset id, side, size, limit price),
the expiry, and a hash of the full verdict, so the cost breakdown that
justified the order is bound to it and can be checked after the fact.

EIP-712 rather than a bare hash so the same authorization could later be
verified onchain by a contract, without changing its format.
"""

import json
from datetime import datetime, timezone

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak

DOMAIN = {"name": "Costwall", "version": "1", "chainId": 1337}

TYPES = {
    "Authorization": [
        {"name": "venue", "type": "string"},
        {"name": "coin", "type": "string"},
        {"name": "assetId", "type": "uint32"},
        {"name": "isBuy", "type": "bool"},
        {"name": "qty", "type": "string"},
        {"name": "limitPx", "type": "string"},
        {"name": "expiresAt", "type": "uint64"},
        {"name": "verdictHash", "type": "bytes32"},
    ]
}

SIGNED_KEYS = ("signature", "signer")


def verdict_hash(verdict):
    """keccak256 of the verdict as canonical JSON, without the signature fields."""
    v = json.loads(json.dumps(verdict))
    for k in SIGNED_KEYS:
        v.get("authorization", {}).pop(k, None)
    return keccak(json.dumps(v, sort_keys=True, separators=(",", ":")).encode())


def _epoch(iso):
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _message(verdict):
    a = verdict["authorization"]
    return {
        "venue": a["venue"],
        "coin": a["coin"],
        "assetId": a["asset_id"],
        "isBuy": a["is_buy"],
        "qty": a["qty"],
        "limitPx": a["limit_px"],
        "expiresAt": _epoch(a["expires_at"]),
        "verdictHash": verdict_hash(verdict),
    }


def _typed(verdict):
    return encode_typed_data(full_message={
        "types": {"EIP712Domain": [{"name": "name", "type": "string"},
                                   {"name": "version", "type": "string"},
                                   {"name": "chainId", "type": "uint256"}], **TYPES},
        "primaryType": "Authorization",
        "domain": DOMAIN,
        "message": _message(verdict),
    })


def sign(verdict, private_key):
    """Attach signature and signer to an APPROVE verdict's authorization, in place."""
    if verdict.get("decision") != "APPROVE" or "authorization" not in verdict:
        return verdict
    acct = Account.from_key(private_key)
    sig = acct.sign_message(_typed(verdict)).signature.hex()
    verdict["authorization"]["signature"] = sig if sig.startswith("0x") else "0x" + sig
    verdict["authorization"]["signer"] = acct.address
    return verdict


def verify(verdict, trusted_signer, now=None):
    """(ok, reason). Checks signer, signature over the order and verdict, and expiry."""
    a = verdict.get("authorization")
    if verdict.get("decision") != "APPROVE" or not a:
        return False, "not_an_approval"
    if not a.get("signature"):
        return False, "unsigned"
    try:
        recovered = Account.recover_message(_typed(verdict), signature=a["signature"])
    except Exception as e:  # malformed signature or fields
        return False, f"signature_unreadable: {type(e).__name__}"
    if recovered.lower() != str(trusted_signer).lower():
        return False, "untrusted_signer"
    now = now or datetime.now(timezone.utc)
    if now.timestamp() > _epoch(a["expires_at"]):
        return False, "expired"
    return True, "ok"
