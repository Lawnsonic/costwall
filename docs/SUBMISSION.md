# Colosseum submission draft

Field-by-field answers for the Crypto World's Fair form. Anything in
[brackets] is yours to fill in; nothing about you is guessed here.

---

**Product name**
Costwall

**One-line description**
A pre-trade cost wall for Hyperliquid trading agents: it prices every order
against the live book at its real size and refuses the ones that can't pay
for themselves.

**Longer description**
Trading agents can stay inside their spending limits and still lose money on
every trade, through fees, spreads, funding and builder fees. Costwall tells
an agent how far the price has to move before a trade breaks even, measured
against the live Hyperliquid order book at the exact size. Too expensive, and
the order never leaves.

It runs as a gateway that holds a trade-only agent wallet: the agent can only
ask to trade, and only an approval signed by the cost oracle and still
unexpired becomes an order, sent as a limit at the approved price. Closing a
position is never blocked. It knows when trade.xyz's stock perps are priced by
their own order book because the real exchange is closed, and refuses those by
default. A free net ledger shows any address its sum of closedPnl next to its
true net after builder fees and funding.

**Blockchains and tools**
Hyperliquid (HyperCore perps, including HIP-3 builder-deployed markets on
trade.xyz), Hyperliquid info and exchange APIs, hyperliquid-python-sdk,
EIP-712 signing (eth-account), Model Context Protocol (MCP), GitHub Pages.

**Team**
[Your name], [role]. [Your background, in two or three sentences. Worth
naming the trading bots you have built and run, since that is the
founder-market fit judges look for.]

**Location**
[City, country]

**Logo**
`docs/logo.svg` (also exported as `docs/logo.png`).

**Repository**
https://github.com/Lawnsonic/costwall (public; [choose a license before submitting, e.g. MIT];
tests run in CI on every push)

**Live product**
https://lawnsonic.github.io/costwall/

**Presentation video** (2 minutes; script in `docs/VIDEO.md`)
[link]

**Demo video** (3 minutes or less; script in `docs/VIDEO.md`)
[link]

---

**Go-to-market strategy**

Who it is for: developers running trading agents on Hyperliquid, first the
ones building on agent frameworks with skill or plugin systems (Senpi skills,
MCP-capable agents), then copy-trading and vault operators who report
performance to depositors.

How they find it: the net ledger. Anyone can paste an address and see the
gap between the profit their agent reports and what it made. That gap is the
reason to install the gateway, and it is shareable. Distribution through MCP
server listings, a Senpi skill wrapping `evaluate_trade`, and posts that show
the ledger on public addresses (with consent, or anonymised).

How it makes money: a builder code on orders the gateway sends. Builder codes
are Hyperliquid's native fee route for order routers, capped at 0.1% on perps.
Costwall's own pitch obliges it to charge far below the cap and show its fee
in every verdict. The cost check and the ledger stay free.

**Demand validation**
- A live review of a Senpi trading skill (senpi-skills PR #800, merged
  2026-09-30) found a +$410.14 headline that was +$256.61 by its own net
  calculation, because closedPnl is gross and the builder fee was never read.
  The failure Costwall prevents is already being found by hand, and getting
  it right is subtle: that fix adds builderFee on top of fee, but Hyperliquid
  documents fee as already inclusive of builderFee, so the builder leg is now
  counted twice.
- On 2026-10-03, across 81,645 fills from 68 active addresses, the 18 using
  builder codes paid 83% of their fees to builders ($9,378 of $11,289 in three
  days). One address showed −$26.76 summed closedPnl and −$674.16 true net
  over seven days.
- [Add any conversations with agent builders here, with what they said. Only
  real ones.]

**Traction**
[Fill in honestly at submission: number of builders who ran the ledger or
installed the MCP server, verdicts served, gateway trades. As of 2026-10-03:
one live mainnet round trip through the gateway, reconciled to the exchange's
fill records (9.12 bps predicted, 9.12 realised); a refusal log running every
five minutes since 2026-10-03.]

**Prior work disclosure**
Costwall grew from a cost oracle built for the Binance Agent OS Hackathon on
2026-09-04 to 2026-09-07, before this hackathon opened. Everything up to git
tag `prior-work-2026-09-07` is that prior work: a Binance spot/perp cost
model, an MCP server around it, and a two-leg executor. All Hyperliquid work
(venue rules, HIP-3 fees, the directional model, the session calendar and
discovery band, the gateway and signed approvals, the ledger, the web page,
the recorder and scanner) was built during the hackathon; `git diff
prior-work-2026-09-07..HEAD` shows it exactly. The US equity session logic
was ported from the author's Stock-Hours Guard, written 2026-09-22. Full
detail: PRIOR_WORK.md.
