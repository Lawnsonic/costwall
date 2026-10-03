# Video scripts

Two videos. Keep the pitch to 2:00 (Colosseum posted a 2-minute limit on
Sept 25; the form says 2 to 3, so 2:00 satisfies both). The demo must be
3:00 or less. Times are targets, roughly 140 spoken words a minute.

Record the screen at 1920x1080 with the browser zoomed to 125%. Every number
on screen should be live, not pasted.

---

## Pitch (2:00)

**0:00 to 0:20. The problem.** Face to camera, or voice over the ledger.

> Trading agents on Hyperliquid report their profit by adding up closed PnL.
> That number is before fees. I pasted one real address into our ledger: it
> reported a loss of twenty-six dollars over a week. Its real loss was six
> hundred and seventy-four. Ninety-five percent of the gap was builder fees
> its own front-end charged, which nothing in its loop ever read.

**0:20 to 0:45. Why existing tools miss it.**

> Spending caps and liquidation guards limit how much an agent can lose. None
> of them ask whether a particular trade is worth making. On Hyperliquid the
> same kind of trade can need a two basis point move on one stock perp and an
> eighteen point move on the next, and on weekends those stock perps are
> priced by their own order book while the real exchange is closed.

**0:45 to 1:20. What Costwall is.** Show the receipt on the web page.

> Costwall prices every trade against the live book at its real size and
> answers one question: how far does price have to move before this trade
> pays for itself? Agents connect over MCP. The gateway holds a trade-only
> key, so the agent can only ask. An approval is signed and expires in ten
> seconds; only that becomes an order, as a limit at the approved price.
> Closing is never blocked.

**1:20 to 1:40. Proof.**

> It is live. On October third our first mainnet trade went through the
> gateway: the oracle predicted 9.12 basis points, the exchange's own records
> say 9.12. A refusal log has priced the busiest markets every five minutes
> since.

**1:40 to 2:00. Who and how.**

> [One sentence on who you are and why you built it: the bots you run.]
> The ledger is free and shows builders the gap; the gateway earns a builder
> fee far below the cap, shown in every verdict. Costwall: know what a trade
> costs before your agent makes it.

---

## Demo (3:00 or less)

**0:00 to 0:30. Ledger.** Web page, ledger section. Paste an address with
builder-fee activity (anonymise it on screen or use one you have permission
to show). Show the three numbers and the step-down chart. Open "By market".

**0:30 to 1:10. Price a trade.** Hero section.
1. BTC, $25, long: approved, about 10 bps, read the receipt lines aloud.
2. Same with builder fee 5: break-even roughly doubles.
3. xyz:GOLD versus xyz:TSLA (on a weekday): the 10x fee gap from growth mode.
4. On a weekend, xyz:TSLA: refused, real exchange closed. Tick the box: it
   prices, and the receipt notes the internal price was accepted.

**1:10 to 1:50. The agent's side.** Terminal or Claude Code with the MCP
server added.
1. Show the tool list: `evaluate_trade`, `request_trade`, `close_position`,
   `get_position`, and no raw order tool.
2. Ask the agent for a trade below $10 or with too small an expected move:
   REJECT with the reason, nothing sent.

**1:50 to 2:30. A real trade.** `python -m scripts.live_check --trade`
(or replay the recorded run): approval, signature check, IOC fill at the
signed limit, reduce-only close, position zero. Then show
`evidence/hl/first-round-trip-2026-10-03.md`: predicted 9.12, realised 9.12.

**2:30 to 3:00. Under the hood.** README's "Measured, assumed, and not done"
section, the green CI badge, the refusal log in `evidence/hl/scan/`. Close on
the page URL.
