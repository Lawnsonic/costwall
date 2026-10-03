# First live round trip through the gateway, 2026-10-03

One $11 BTC long requested through `request_trade`, closed immediately with
`close_position`, on Hyperliquid mainnet, account `0x74accd81…9b54`, agent
wallet `0x84761899…aC66` (trade-only, cannot withdraw). Run by the account
owner with `python -m scripts.live_check --trade`.

## What the gateway did

1. Priced the trade against the live book: APPROVE, break-even 9.90 bps
   (8-hour hold assumed), size 0.00012 BTC after rounding down to the lot size
   ($10.18, above the $10 minimum), limit 84837.0.
2. Verified the oracle's EIP-712 signature and expiry before sending.
3. Sent one IOC limit buy at 84837.0. Filled 0.00012 at 84837.0
   (oid 564513242051).
4. Closed reduce-only with an IOC limit sell bounded at 2% through mid
   (83140). Filled 0.00012 at 84836.0 (oid 564513261195). Position after: 0.

Gateway rows: `evidence/hl/verdicts.jsonl`, `evidence/hl/trades.jsonl`
(verdict hash `0xde81f1f7…e239`).

## Reconciliation against the exchange's own fill records (userFillsByTime)

| Term | Predicted | Realised |
|---|---|---|
| Taker fee, open | 4.50 bps | 4.4998 bps ($0.004581) |
| Taker fee, close | 4.50 bps | 4.4999 bps ($0.004581) |
| Spread in + out | 0.12 bps | 0.12 bps (84837.0 in, 84836.0 out; closedPnl −$0.00012) |
| Funding | 0.78 bps for an assumed 8 h hold | none: held 2 seconds, no funding hour crossed |
| **Total for the trade actually made** | **9.12 bps** | **9.12 bps** ($0.009282 on $10.18) |

The fee was read from the account's own `userFees` (4.5 bps taker, no
referral or staking discount), not assumed.

## What this does and does not show

It shows the whole path works with real money: price, sign, verify, send at
the signed limit, fill, close reduce-only, and that the oracle's fee and
crossing terms matched the exchange's records for this trade.

It is one $10 trade on the most liquid market on the venue, where the book
is deep enough that crossing cost is a rounding error. It says nothing yet
about thin books, larger sizes, or HIP-3 markets. For contrast, the Binance
build this grew from predicted 31.77 bps on its one paired trade and paid
55.50 (see `prior/README-binance.md`); the model was rebuilt because of it.
