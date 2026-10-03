# Working in this repository

Costwall prices Hyperliquid trades and, through `gateway/`, can place real
orders with real money. The rules below are not style preferences.

## Orders

- Orders go through the gateway (`request_trade`, `close_position`) and
  nowhere else. Never call the Hyperliquid SDK's order methods directly.
- `decision: "REJECT"` is binding. Report the `reason` and `shortfall_bps`
  and stop.
- A verdict expires at `expires_at`. Price again rather than act on an old one.
- `reason: "pricing_failed"` means the cost is unknown, not acceptable.
- Never pass `accept_internal_price=true` on your own initiative. Only when
  the human asked for an off-hours stock trade in this conversation.
- Never send a mainnet order without the human's explicit go-ahead for that
  order.

## Code

- **Measured, not assumed.** Every number in code, logs, the README or the
  page comes from a live call or a cited doc. If a value is assumed, label it
  assumed in the output.
- **Fail closed.** Anything that cannot finish the arithmetic returns a
  REJECT, never an exception the agent might shrug off.
- **Never lower a threshold to make something approve.**
- Run the offline tests before committing:
  `python -m tests.test_sessions_band`, `python -m tests.test_gateway`,
  `python -m tests.test_ledger`.
- `.env` holds the agent key and the oracle signing key. Never print, commit
  or paste either.
- `hl/` modules read `HL_NETWORK` at import; load `envfile` first in any
  entry point that trades.

## Prior work

`cost/`, `execution/`, `strategy/`, `reporting/` and `prior/` are the
Binance build from before 2026-09-14. Do not present them as hackathon work.
