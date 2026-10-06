# Costwall — submission answers

Reviewed October 6, 2026 against the public FAQ. Match these answers to the
actual portal fields and character limits; the authenticated form was not inspected.

## Product
Costwall

## One-line description
A pre-trade cost check and local execution gateway for Hyperliquid agents,
with an itemised break-even estimate and a public realised ledger.

## Description
Costwall answers a practical question before an agent sends an order: how
much price movement would this trade need to cover its costs?

It walks the live Hyperliquid book at the requested size and combines entry
crossing, an assumed exit book, exchange and builder fees, and a funding
scenario. The result is an itemised cost estimate and policy verdict.
The local gateway verifies a signed, expiring approval before submitting
an IOC entry with a limit price. Reduce-only closes bypass the profitability gate.

The public website provides read-only pricing, a market board and an address
ledger separating realised PnL, exchange fees, builder fees and funding.
Calendar checks flag scheduled internal pricing and unknown HIP-3 schedules.

One owner-run mainnet test completed an approximately $10.18 BTC round trip.
The original eight-hour estimate was 9.90 bps. Its crossing-and-fee subtotal
was about 9.12 bps; the reported exchange reconciliation was 9.1175 bps for
the two-second trade. This demonstrates a working path, not general accuracy.

## Ecosystem and technology
Hyperliquid / HyperCore perpetuals, HIP-3 markets, public info API,
Hyperliquid Python SDK, Python, MCP, EIP-712, JavaScript and GitHub Pages.
No HyperEVM contract is claimed.

## Links and assets
- Product: https://lawnsonic.github.io/costwall/
- Repository: https://github.com/Lawnsonic/costwall
- Evidence: https://github.com/Lawnsonic/costwall/blob/main/evidence/hl/first-round-trip-2026-10-03.md
- Prior work: https://github.com/Lawnsonic/costwall/blob/main/PRIOR_WORK.md
- Pitch: [ADD VIDEO URL]
- Demo: [ADD VIDEO URL]
- Logo: docs/logo.png; vector original: docs/logo.svg

## Founder/team/location
[YOUR NAME, ROLE, CITY, COUNTRY, ALL TEAM MEMBERS]
Background starter, only if accurate:
“I build trading bots. An earlier Binance cost-model experiment showed me
how execution assumptions diverge from fills. That led me to build Costwall
around explicit costs, bounded entry prices and an audit trail.”
Add your real projects and actual experience. Describe AI assistance honestly
if asked. Do not invent users, revenue, team members or qualifications.

## Insight
Permission and position controls limit what an agent may trade. Costwall
adds an explicit economic hurdle before entry and shows its workings.
It complements those controls. We do not claim no competitor has similar
features or that a passed cost check predicts a profitable trade.

## Customer and distribution
Start with developers operating Hyperliquid agents. The free browser ledger
and cost receipt introduce the problem; local MCP/gateway integration is the
adoption path. Planned distribution includes framework integrations and
direct conversations with agent developers. Those remain plans unless
separately evidenced. We have not established a defensible market-size estimate.

## Business model
Proposed revenue is a transparent builder fee on routed orders, included in
every cost estimate. The receipt and ledger stay free for discovery.
We have not validated willingness to pay or earned revenue from the demo.

## Validation and traction
The repository contains one owner-run mainnet round trip and dated internal
market scans. These are engineering evidence, not outside customers.
No verified paid users or external adoption are claimed in this package.
[ADD ONLY VERIFIED CUSTOMER FEEDBACK OR USAGE, WITH DATES.]

## Remaining work
Broader calibration, refused-trade counterfactuals, hosted read-only MCP,
outside adoption and production execution/security hardening. The ledger
excludes unrealised PnL and does not establish total account return.

## Prior-work disclosure
Costwall builds on our Binance Agent OS Hackathon work from September 4–7,
2026. Tag prior-work-2026-09-07 identifies the earlier cost oracle, MCP wrapper,
two-leg executor, scanner and evidence. Hyperliquid development was added
during this event: venue adapter, directional model, HIP-3 fees and sessions,
signed gateway, ledger, recorder/scanner and website. US equity calendar
logic was adapted from our Stock-Hours Guard project, dated September 22.
PRIOR_WORK.md documents the history. Stock-Hours Guard is related disclosed
work; Costwall is the single product we are submitting.

## Before submitting
Fill all personal fields and video URLs, remove placeholders, and verify
the final text against your actual situation. The public FAQ permits a
2–3 minute presentation and a demo no longer than three minutes.
Every teammate must join the event; one entry per individual/team.
Public repositories are allowed; no MIT license has been selected for this repo.
The public event dates end October 12. Confirm the exact cutoff and timezone
in the portal, and save the submission receipt.

Source checked October 6: https://colosseum.com/hackathon
