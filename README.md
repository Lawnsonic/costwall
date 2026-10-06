# Costwall

**A pre-trade cost wall for Hyperliquid trading agents.** Before an agent's
order leaves, Costwall prices it against the live order book at its real size
and answers one question: how far does the price have to move before this
trade has paid for itself? If the answer is unreasonable, the order never goes
out.

**Try it in your browser:** https://lawnsonic.github.io/costwall/
(price a trade, paste any address into the net ledger, see the live board)

Built for Colosseum Crypto World's Fair, Hyperliquid track.
Prior work is disclosed in [PRIOR_WORK.md](PRIOR_WORK.md).

---

## The problem

Trading costs can consume a strategy's expected move. Costwall makes the
estimated hurdle explicit before entry and records the gateway's decisions.
A cost-policy approval is not a forecast that price will move favourably.

[Recording and submission kit](docs/START_HERE.md) includes a spoken pitch,
timed demo, submission answers and judge Q&A.

Historical exploratory wallet aggregates are not used as headline proof:
their exact raw sample and query window were not preserved in this repository.

---

## What it does

### The break-even move

```
break-even move = spread in + spread out
                + taker fee x 2 + builder fee x 2
                + funding over the hold, when it runs against you
```

- **Spread in and out** come from walking the live order book for the exact
  size, not from the top of the book.
- **Taker fee** is read from the account's own fee tier and scaled for HIP-3
  markets exactly as Hyperliquid's docs compute it (x2 deployer share, x0.1 in
  growth mode).
- **Builder fee** is what the agent's framework charges per fill, or the
  approved maximum read from the exchange.
- **Funding** is hourly on Hyperliquid. It is charged when it runs against the
  position and never credited when it runs for it, because the rate can flip
  within the hold.

The verdict is `APPROVE` or `REJECT` with the full breakdown. If the agent
states the move it expects, the trade must clear break-even plus 10 bps;
otherwise it is held to a 50 bps ceiling that catches broken books.

### The gateway: the agent never holds the key

```
agent ──request_trade──▶ gateway ──▶ oracle (live book, real size)
                            │              │
                            │     APPROVE, signed (EIP-712), expires in 10 s
                            │     or REJECT with the reason
                            ▼
              one immediate-or-cancel limit order at the signed price,
              sent with an agent wallet that can trade but cannot withdraw
```

- The oracle signs every approval over the order itself (market, side, size,
  limit price), its expiry, and a hash of the full verdict. The gateway
  rejects anything unsigned, tampered with, signed by another key, or expired.
- The order is a limit at the deepest price the verdict priced, so fills respect that limit. IOC orders may fill partially; the limit does
  not guarantee the estimated VWAP or the future exit cost.
- close_position bypasses the profitability gate and is sent reduce-only so a "close" can never
  open or flip a position. Exchange errors, limited liquidity or the 2% close
  bound can leave residual size. Its cost is still measured and logged.

### Stock markets after hours

For trade.xyz markets, Costwall knows each market's schedule (US 24/5, futures,
FX), read from trade.xyz's published specification table and holiday list.
When the real exchange is closed, it refuses by default, because what the
position is worth at reopen cannot be measured. The agent can pass
`accept_internal_price=true` to trade anyway, and the verdict records that it
did. Where the recorder has the last external price, the verdict also shows
where the price sits inside trade.xyz's discovery band.

### The net ledger

Paste any address. It shows the sum of `closedPnl`, the same minus exchange
fees, and net of recorded costs after builder fees and funding, broken down by market.
No key needed; it is all public. The ledger excludes unrealised PnL and
transfers, does not convert non-USDC fees, and is subject to API history limits.
It is not total account return.

---

## Use it

**In a browser:** https://lawnsonic.github.io/costwall/

**From an agent (MCP):** read-only pricing, no keys needed.

```bash
git clone https://github.com/Lawnsonic/costwall && cd costwall
pip install -r requirements.txt
claude mcp add costwall -- python "$(pwd)/gateway/mcp_server.py"
```

The agent gets `evaluate_trade`. To make it the gateway, copy `.env.example`
to `.env` and fill in an agent wallet created at app.hyperliquid.xyz/API. The
server then also offers `request_trade`, `close_position` and `get_position`,
and the agent gets no other way to place an order. The trading tools are never
served over HTTP.

**From the command line:**

```bash
python -m hl.oracle xyz:TSLA 25 BUY --hold-hours 8
python -m hl.ledger 0xADDRESS --days 7
python -m scripts.live_check            # gateway pre-flight, sends nothing
```

---

## Evidence produced during the hackathon

| What | Where |
|---|---|
| Order books every 15 s and market state every minute, busiest 16 markets, since 2026-10-03 | `hl/recorder.py` (data kept locally; too large for git) |
| Live refusal log: $25 long and short on 20 markets every 5 minutes | `evidence/hl/scan/` |
| Gateway verdicts, orders and fills | `evidence/hl/` |
| Tests: session calendar, trade.xyz's published discovery-band example, gateway against a fake exchange, ledger arithmetic | `tests/` |

**First live round trip, 2026-10-03.** An $11 BTC long through
`request_trade`, closed at once through `close_position`, on mainnet with a
trade-only agent wallet. Reconciled against the exchange's own fill records:

| | Predicted | Realised |
|---|---|---|
| Taker fees, both ways | 9.00 bps | 9.00 bps |
| Spread in and out | 0.12 bps | 0.12 bps |
| Total for the trade made (no funding hour crossed) | **9.12 bps** | **9.12 bps** ($0.0093 on $10.18) |

The original recorded forecast was **9.90 bps for an eight-hour hold**.
The 9.12 bps comparison covers its crossing-and-fee subtotal; no funding
hour was crossed during the two-second actual hold. This is a component
comparison, not a full forecast match.

One small trade on the deepest book on the venue, so it proves the path works
end to end with real money, not that the model holds on thin books. Full
record: [evidence/hl/first-round-trip-2026-10-03.md](evidence/hl/first-round-trip-2026-10-03.md).

---

## Measured, assumed, and not done

Recorded figures are historical observations. Estimates contain assumptions. Where something is assumed, the
verdict says so:

- **Exit spread** assumes the exit book will look like the current one.
- **Hold time** defaults to 8 hours when the agent doesn't say.
- **Discovery-band trigger** is assumed to be 90% for every market (trade.xyz
  publishes it only as an example), and the band is replayed from one-minute
  snapshots.
- **Fee tier** on the public page is Hyperliquid's base tier; the gateway reads
  the account's own.

Known limits:

- trade.xyz's own docs disagree with themselves for four markets (the band is
  described as 1/max leverage, but the table differs for XYZ100, COST, UNITREE
  and SHEIN). Costwall uses the table and reports the gap.
- 14 xyz markets (mostly Asian sessions) have schedules Costwall does not parse;
  they are refused as "schedule unknown" rather than guessed.
- Other HIP-3 deployers publish no schedule Costwall can read, so their markets
  are treated the same way.
- The gateway's signing key and trading key sit on the same machine when run
  locally. The design allows the oracle to be hosted separately; that
  deployment is not done yet.

---

## Business model

The cost check and the ledger are free. Proposed revenue comes from a builder code on
orders the gateway sends: Hyperliquid's builder codes are the only fee route
for an order router, capped at 0.1% on perps. Costwall's own pitch obliges it
to charge far below that cap and to show its own fee in every verdict, like
everyone else's. The ledger is how builders find out they need it.

---

## Repository

```
hl/          Hyperliquid: info client, venue rules, oracle, sessions,
             discovery band, ledger, recorder, scanner, xyz registry
gateway/     signed approvals (authz), the gateway, the MCP server
docs/        the web page (GitHub Pages) and the build plan
tests/       offline tests (gateway tests price the live book, send nothing)
scripts/     live_check: gateway pre-flight and first round trip
cost/, execution/, strategy/, reporting/
             prior work: the Binance build this grew from (see PRIOR_WORK.md)
prior/       the Binance-era README, context and agent policy
```

## Submission scope and deployment limits

The public website and local MCP gateway are implemented. Hosted read-only
MCP, broader calibration, refused-trade counterfactuals and outside adoption
remain pending. Internal scanner observations are not customer traction.
No paid adoption or external customer count is verified in this package.

The boundary assumes the agent cannot access host secrets, a shell or raw
exchange tools. Local keys share a host. The signature prototype lacks
production nonce/replay protection and account/network-specific domain
binding. A trade-only wallet can lose trading capital even without withdrawal
permission. The gateway has not been security-audited.

Calendar state estimates scheduled external-price availability; it is not
a live oracle-health or trading-halt feed. Browser and Python estimates may
differ with quote timing, caching, rounding and account fee tiers.

Source is public; no project-wide open-source license has been selected.
Current recording and submission instructions: [Start here](docs/START_HERE.md).
