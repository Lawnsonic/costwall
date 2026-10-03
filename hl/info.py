"""
Public Hyperliquid info endpoint. No keys, no signing, cannot place an order.

Every read in this package goes through q(), so rate limiting and retries
live in one place. Hyperliquid meters the info endpoint by weight per IP
(1200 per minute); l2Book costs 2, metaAndAssetCtxs costs 20.
"""

import os
import time

import requests

# Testnet and mainnet have different books. The oracle must price against the
# network the gateway trades on, so both read the same switch.
NETWORK = os.environ.get("HL_NETWORK", "mainnet")
API_URL = ("https://api.hyperliquid-testnet.xyz" if NETWORK == "testnet"
           else "https://api.hyperliquid.xyz")
INFO_URL = API_URL + "/info"
TIMEOUT = 15

# One kept-alive connection. A fresh TLS handshake per call cost ~0.9 s each
# from Lagos, which ate most of a 10-second verdict lifetime.
_session = requests.Session()


def q(body, retries=3):
    for attempt in range(retries):
        try:
            r = _session.post(INFO_URL, json=body, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def l2_book(coin):
    return q({"type": "l2Book", "coin": coin})


def meta_and_ctxs(dex=""):
    """(universe, ctxs) for one perp dex. "" is the validator-run main dex."""
    body = {"type": "metaAndAssetCtxs"}
    if dex:
        body["dex"] = dex
    meta, ctxs = q(body)
    return meta["universe"], ctxs


def perp_dexs():
    """Names of every builder-deployed (HIP-3) dex. The main dex is listed as null."""
    return [d["name"] for d in q({"type": "perpDexs"}) if d]


def predicted_fundings():
    return q({"type": "predictedFundings"})
