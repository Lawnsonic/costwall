# Prior work disclosure

Colosseum Crypto World's Fair ran from 2026-09-14 to 2026-10-12. This file
lists what existed before it opened, so judges can tell the two apart.

## What existed before 2026-09-14

Everything at git tag **`prior-work-2026-09-07`** (commit `d364117`) was built
for the Binance Agent OS Hackathon between 2026-09-04 and 2026-09-07. The full
commit history is preserved in this repository with its original dates.

| Area | Files | What it did |
|---|---|---|
| Cost oracle | `cost/cost_oracle.py` | Priced a Binance spot/perp funding carry and a single-leg spot conversion against live order books at size; returned APPROVE/REJECT with the cost breakdown |
| MCP server | `cost/cost_mcp.py`, `cost/override.py` | Exposed the oracle to an agent as `evaluate_trade`; logged human overrides |
| Execution | `execution/executor.py`, `execution/venue.py` | Two-leg Binance hedge state machine; lot-size rules and fees |
| Strategy | `strategy/` | Funding-rate scanner over Binance perps |
| Evidence and reporting | `evidence/`, `reporting/`, `refusal_log.py` | Binance trade and refusal logs, HTML report |

The Binance refusal logs and the one Binance paired trade are **prior work**.
They are not presented as hackathon results.

## Code reused from another project by the same author

`hl/sessions.py` ports the US equity session logic from the author's
**Stock-Hours Guard** (`keeper/src/session.ts`, written 2026-09-22, inside
the window), translated from TypeScript to Python and extended with
trade.xyz's futures and FX schedules and holiday lists.

## What was built during the hackathon

Everything committed after the tag. The Hyperliquid work starts in `hl/`.
`git diff prior-work-2026-09-07..HEAD` shows the in-window work exactly.
