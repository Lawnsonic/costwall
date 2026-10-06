# Judge Q&A

**What does APPROVE mean?**
The configured cost test passed. It does not predict direction, profit,
liquidation safety or future execution conditions.

**What is the difference from a spending cap?**
A cap limits permitted exposure or expenditure. Costwall estimates the
economic hurdle of a particular trade. These controls can work together.

**What is measured?**
Visible entry depth and current metadata. Exit liquidity and future funding
are assumptions. Calendar state is an inference, not live oracle-health data.

**What does the signature guarantee?**
Integrity and expiry checks within the gateway. The deployment assumes the
agent lacks secrets, host shell access and raw exchange tools. Local keys
share a host. Production replay protection and stronger account/network
domain binding remain work; this is not an audited security boundary.

**Can a trade exceed its estimate?**
Yes. The limit bounds entry price, not future exit costs or PnL. IOC can
partially fill. A reduce-only close can also fail or leave a residual position.

**Is the ledger total account return?**
No. It totals returned realised PnL minus USDC fill fees plus funding for a
window. Unrealised PnL, transfers, other-token fees and history completeness
limit the result.

**Are builder fees counted twice?**
No. Hyperliquid documents fee as inclusive of builderFee. The ledger splits
exchange and builder portions and subtracts the total only once.

**What traction is proven?**
One owner-run mainnet round trip and internal scans. No external customer
count or revenue is verified in this package.

**Why 9.90 versus 9.12 bps?**
The original estimate included eight hours of projected funding. The trade
lasted about two seconds. Only its crossing-and-fee subtotal matched after
rounding; it is not a full forecast match.

**How will you make money?**
A proposed builder fee on routed orders, included in the same estimate.
Willingness to pay still needs validation.

**What comes next?**
Calibration across sizes/markets, execution and security hardening, then
feedback and adoption from external agent developers.

**What existed before the event?**
The Binance predecessor is tagged and disclosed. Related Stock-Hours Guard
calendar code is also disclosed. The Hyperliquid work was added in the event.
AI assistance was used during development; explain your own role accurately.
