"""
Public Hyperliquid info endpoint. No keys, no signing, cannot place an order.

Every read in this package goes through q(), so rate limiting and retries
live in one place. Hyperliquid meters the info endpoint by weight per IP
(1200 per minute); l2Book costs 2, metaAndAssetCtxs costs 20.
"""

import json
import time
import urllib.error
import urllib.request

INFO_URL = "https://api.hyperliquid.xyz/info"
TIMEOUT = 15


def q(body, retries=3):
    data = json.dumps(body).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                INFO_URL, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
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
