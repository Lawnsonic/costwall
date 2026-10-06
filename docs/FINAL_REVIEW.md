# Submission review — October 6, 2026

The demonstrated prototype supports a submission with its limits stated.
Founder details, video recording/uploading and portal submission remain.

## Checked claims
- Original saved verdict: 9.90 bps, assuming eight hours.
- Entry/exit crossing and fee estimate: about 9.12 bps.
- October 3 reconciliation: 9.1175 bps / $0.009282 on approximately $10.18.
- One round trip is mechanism evidence, not broad calibration.
- APPROVE means cost-policy passed; the ledger is partial realised accounting.
- Revenue, hosted MCP and external adoption remain unverified or planned.

## Local scan inventory
Parsed 12,480 verdicts across 4 files.
Range: 2026-10-03T18:47:25Z through 2026-10-06T08:06:02Z.
These are internal observations, not independent samples, users, trades or
avoided losses. Growing local logs are not automatically uploaded by this review.

| Decision / reason | Rows |
|---|---:|
| APPROVE / cost_within_ceiling | 8632 |
| REJECT / cost_exceeds_ceiling | 28 |
| REJECT / internal_price_session | 3820 |

## Checks
The existing three Python suites passed on October 6: session/band (3 cases),
ledger (1), gateway (7). Gateway uses public quotes with a fake exchange and
sends no orders. Final JavaScript syntax and GitHub CI status are checked
before publication.

## Limits
No production security audit, nonce/replay protection or account/network
domain separation for a distributed oracle. Local keys share a host.
A privileged agent could bypass the boundary. IOC orders can partially fill
and closes may leave residual exposure. Entry price bounds do not guarantee
VWAP, exit costs or profitability. Calendar state is not live oracle health.
The ledger is limited by history, pagination, omitted unrealised PnL and
non-USDC fees. Browser/Python numerical equivalence is not established.

## Rules checked
https://colosseum.com/hackathon — checked October 6.
Presentation: 2–3 minutes. Demo: at most 3 minutes. Public repo allowed.
Disclose prior work; one product per individual/team. Public event ends
October 12; exact cutoff/timezone and authenticated form limits must be
checked in the portal. No new mainnet trade is needed for recording.
