# Costwall: build plan (Colosseum Crypto World's Fair, Hyperliquid track)

## The product in one paragraph

A trading agent can stay inside its spending limits and still lose money on
every trade: fees, crossing the spread, thin books, funding, builder fees.
Spending caps (Coinbase, Reins, namixai) and liquidation guards (nightling)
limit how much an agent can lose. None of them decide whether a given trade is
worth making. Costwall does that. The agent asks to trade, Costwall prices the
trade against the live Hyperliquid order book at the real size, and either
places it or refuses it with the reason written down. The agent never holds the
trading key, so it cannot skip the check.

## The loop everything serves

    agent ──request_trade──▶ gateway ──▶ cost oracle (live book, real size)
                               │                │
                               │         APPROVE (signed, expires in seconds)
                               │         or REJECT (reason, shortfall)
                               ▼
                      places IOC limit order with the agent key
                      (agent key can trade, cannot withdraw)

Plus one proof tool: **net ledger**. Paste any Hyperliquid address and see the
profit it claims next to the profit it made after fees, builder fees, funding
and crossing cost.

## Build order

| Step | What | Status |
|---|---|---|
| N1 | Book and market-state recorder (in-window evidence) | running since 2026-10-03 |
| E1 | New repo, prior-work tag, PRIOR_WORK.md | done |
| A1 | Hyperliquid venue: books, size rules, $10 minimum, fees incl. HIP-3 formula, dex list from `perpDexs`, delisted/isolated flags | done: `hl/venue.py` |
| A2 | `perp_entry` model: one-direction perp trade, returns break-even move | done: `hl/oracle.py` |
| A3 | Builder and referral fees in the breakdown | done: declared or read via `maxBuilderFee` |
| A4 | Hourly funding, HIP-3 funding multiplier | done: multiplier is already inside the API's `funding` |
| A5 | HIP-3 stock markets: off-hours price and price-band refusals | done: `hl/sessions.py`, `hl/band.py`, `hl/xyz_registry.json` |
| N4 | Venue interface: Binance and Hyperliquid behind one `evaluate` | |
| B1+B2 | Gateway holds agent key; signed, expiring approvals; reduce-only closes always pass | built, offline-tested: `gateway/` (live testnet run pending keys) |
| C1 | Net ledger | done: `hl/ledger.py` |
| D1 | Hosted MCP server | server built (`gateway/mcp_server.py --http`), not yet deployed |
| D4 | Web page: refusal board and ledger | |
| C4 | Fresh refusal log on Hyperliquid | |
| E2 | Replay tests on recorded books | started: `tests/test_sessions_band.py` (calendar + docs' WTIOIL example) |
| E3 | Testnet, then one ~$25 mainnet trade | |
| D6 | 3 to 5 outside agent builders run the ledger | |
| E4 | 2-minute pitch, 3-minute demo, go-to-market write-up | |

## Left out, and why

| Item | Reason |
|---|---|
| Liquidation checks, loss caps | Reins, namixai and nightling already do this |
| Contract on HyperEVM | Contract orders can be dropped silently and carry no builder fee |
| Telegram override, Telegram alerts | Not part of the core loop |
| Cross-venue funding arbitrage | A second product |
| Robinhood Chain | A second chain |

## Facts checked against the live API (2026-10-03)

- `l2Book` returns 20 levels a side, on main dex and on xyz.
- Base fees: 4.5 bps perp taker, 7 bps spot taker (`userFees`).
- Funding settles hourly on Hyperliquid (`predictedFundings`).
- HIP-3 fees are base x2 when `deployerFeeScale` is 1.0; growth mode cuts all-in
  fees by 90% or more. 118 of 129 xyz markets have growth mode on.
- xyz markets carry `isDelisted` (19), `onlyIsolated` (109) and a per-asset
  funding multiplier (0.5).
- trade.xyz off-hours: internal EWMA oracle, mark held within +/-1/maxLeverage
  of a reference price. The API does not say whether the market is open or
  where the band is; Costwall derives both. Session calendar is ported from
  Stock-Hours Guard; the band reference comes from the recorder's oracle prices.
- Builder fee cap is 0.1% on perps, 1% on spot; the `f` field is tenths of a bp.
  Approval (`ApproveBuilderFee`) must be signed by the main wallet, not the agent.
- Minimum order value is $10 (`MinTradeNtl`).
- trade.xyz schedules (Specification Index, 109 markets): 82 US 24/5
  (Sun 20:00 to Fri 20:00 ET), 10 futures (Sun 18:00 to Fri 17:00, daily break),
  3 FX, 14 unknown (Asian sessions, irregular text). HO and OURA trade but are
  not in the docs yet.
- The docs say the band is 1/maxLeverage, but their own table differs for
  XYZ100, COST, UNITREE and SHEIN. Costwall uses the table and reports the gap.

- Fill `fee` INCLUDES `builderFee`: true on all 5,910 builder-coded fills out of
  81,645 scanned (68 addresses seen in recent trades, 3 days). For the 18
  addresses using builder codes, builders took 83.1% of all fees ($9,378 of
  $11,289). Median taker builder fee was 10 bps (the cap) against 0.77 bps to
  the exchange on HIP-3. Small, unrandomised sample: an illustration, not a
  market statistic.

## First ledger reading (2026-10-03, one address, 3 days)

closedPnl only -$12.95; minus exchange fees -$26.36; true net -$293.13.
Builder fees $266.74 were 95% of its fees.

## First live readings (2026-10-03, $25, 8h hold, base fee tier)

| Trade | Break-even move | Mostly |
|---|---|---|
| BTC long | 9.9 bps | 9.0 fees |
| xyz:TSLA short (growth mode) | 2.07 bps | 1.8 fees |
| xyz:GOLD long (no growth mode) | 18.74 bps | 18.0 fees |
| BTC long, 5 bps builder fee | 19.9 bps | builder fee doubles it |
