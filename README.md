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

## The problem, in three measurements

All three were measured from Hyperliquid's public API on 2026-10-03.

**1. Agents report profit before the costs that matter.** One address, seven
days of trading:

| What the agent could report | Amount |
|---|---|
| Sum of `closedPnl` | −$26.76 |
| …minus exchange fees | −$57.33 |
| **True net**, after builder fees and funding | **−$674.16** |

Builder fees were 95% of everything it paid. Across 81,645 fills from 68
addresses seen in recent trades, the 18 addresses using builder codes paid 83%
of their fees to builders, not to the exchange ($9,378 of $11,289 over three
days). On HIP-3 stock perps, the median taker builder fee was 10 bps, the
maximum allowed, against 0.77 bps to the exchange. (A small, unrandomised
sample: an illustration, not a market statistic.)

**2. The same kind of trade can cost ten times more one market over.** A $25
round trip on trade.xyz's TSLA perp needs a 2.07 bps move to break even; on
its GOLD perp, 18.74 bps. Both are HIP-3 markets on the same deployer; TSLA has
"growth mode" fees switched on and GOLD does not.

**3. Stock perps keep trading when the stock market doesn't.** On weekends
trade.xyz prices its 82 US-equity markets from its own order book, inside a
band around Friday's close. A fill then is priced against whoever is trading
on Saturday, not against the stock.

Spending caps (Coinbase Agentic Wallets, Reins, namixai) and liquidation
guards (nightling) limit how much an agent can lose. None of them decide
whether a particular trade is worth making. That decision is Costwall.

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
- The order is a limit at the deepest price the verdict priced, so it fills
  inside the priced depth or not at all.
- `close_position` is never refused (a cost check that can trap you in a
  position is worse than none), and is sent reduce-only so a "close" can never
  open or flip a position. Its cost is still measured and logged.

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
fees, and the true net after builder fees and funding, broken down by market.
No key needed; it is all public.

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

The first live round trip through the gateway (an $11 BTC long, closed
immediately) is run with `python -m scripts.live_check --trade`; its rows
appear in `evidence/hl/trades.jsonl`.

---

## Measured, assumed, and not done

Every figure above comes from a live call. Where something is assumed, the
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

The cost check and the ledger are free. Revenue comes from a builder code on
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
