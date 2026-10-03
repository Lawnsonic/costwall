"""
Gateway checks against a fake exchange. The oracle is real and prices the live
mainnet book over public REST; no order is sent anywhere.

Run:  python -m tests.test_gateway
"""

import os
import sys
import tempfile
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from eth_account import Account

from gateway import gateway as gw


class FakeExchange:
    """Records orders and answers like Hyperliquid would for an IOC."""

    def __init__(self, response=None):
        self.orders, self.response = [], response

    def order(self, coin, is_buy, sz, limit_px, order_type, reduce_only=False, builder=None):
        self.orders.append(dict(coin=coin, is_buy=is_buy, sz=sz, limit_px=limit_px,
                                order_type=order_type, reduce_only=reduce_only))
        if self.response is not None:
            return self.response
        return {"status": "ok", "response": {"type": "order", "data": {"statuses": [
            {"filled": {"totalSz": str(sz), "avgPx": str(limit_px), "oid": 1}}]}}}


SIGNER = Account.create()
ACCOUNT = "0x0000000000000000000000000000000000000001"


def make(exchange, trusted=None):
    return gw.Gateway(exchange, ACCOUNT, trusted or SIGNER.address, signer_key=SIGNER.key)


def test_approved_trade_goes_out_as_ioc_at_signed_price():
    ex = FakeExchange()
    row = make(ex).request_trade("BTC", 25, "BUY")
    assert row["outcome"] == "FILLED", row
    o = ex.orders[0]
    assert o["order_type"] == {"limit": {"tif": "Ioc"}} and o["reduce_only"] is False
    assert str(Decimal(str(o["limit_px"]))) == str(Decimal(row["limit_px"]))


def test_rejected_trade_never_reaches_exchange():
    ex = FakeExchange()
    row = make(ex).request_trade("BTC", 5, "BUY")
    assert row["outcome"] == "REFUSED" and row["reason"] == "below_venue_minimum"
    assert ex.orders == []


def test_untrusted_signer_never_reaches_exchange():
    ex = FakeExchange()
    row = make(ex, trusted=Account.create().address).request_trade("BTC", 25, "BUY")
    assert row["reason"] == "authorization_untrusted_signer", row
    assert ex.orders == []


def test_off_hours_stock_refused_unless_accepted():
    ex = FakeExchange()
    g = make(ex)
    row = g.request_trade("xyz:TSLA", 25, "BUY")
    if row.get("reason") == "internal_price_session":
        assert ex.orders == []
        row = g.request_trade("xyz:TSLA", 25, "BUY", accept_internal_price=True)
    assert row["outcome"] == "FILLED", row


def test_exchange_error_is_recorded_as_no_fill():
    ex = FakeExchange({"status": "ok", "response": {"type": "order", "data": {"statuses": [
        {"error": "Order could not immediately match against any resting orders."}]}}})
    row = make(ex).request_trade("BTC", 25, "BUY")
    assert row["outcome"] == "NO_FILL" and "could not immediately match" in row["error"]


def test_close_is_reduce_only_and_never_priced_out():
    ex = FakeExchange()
    g = make(ex)
    g.position = lambda coin: Decimal("-0.0003")  # a short to close
    row = g.close_position("BTC")
    o = ex.orders[0]
    assert o["reduce_only"] is True and o["is_buy"] is True and o["sz"] == 0.0003
    assert row["outcome"] == "FILLED"


def test_close_with_no_position_sends_nothing():
    ex = FakeExchange()
    g = make(ex)
    g.position = lambda coin: Decimal(0)
    assert g.close_position("BTC")["reason"] == "no_position" and ex.orders == []


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        gw.EVIDENCE = d  # keep test rows out of the real evidence log
        for name, fn in list(globals().items()):
            if name.startswith("test_"):
                fn()
                print("ok ", name)
