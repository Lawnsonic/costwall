# Costwall — record these two videos

Target: a 2:00 founder pitch and a 2:40 product demo. The official FAQ checked
October 6 allows a 2–3 minute presentation and a demo no longer than 3 minutes.
Follow any more restrictive instruction in your actual submission portal.

## Before recording
Use 1920×1080, readable browser zoom, a microphone and Do Not Disturb.
Close wallet popups and secret files. Open the public site, README, dated
round-trip evidence and the October 3 scan log. Rehearse with a stopwatch.
No new trade is needed: show the existing trade as historical evidence.

## Pitch — narration

Hello, I'm [YOUR NAME], the builder of Costwall.

A trading agent can obey its spending limit and still make a trade whose
costs overwhelm the move it expects. Exchange fees are only part of the bill.
There is also the spread, market depth, funding and the interface's builder fee.

Costwall makes that bill explicit before an order leaves.

It reads Hyperliquid's live order book at the requested size and produces an
itemised break-even estimate. The agent can compare that estimate with its
expected move. An approval means the cost policy passed; it does not mean
the trade will make money.

The local gateway holds the trading key. It checks a signed, expiring verdict
and submits an immediate-or-cancel order at a bounded price. Reduce-only
closes bypass the profitability check.

You can try the product immediately: price a trade in the browser, or paste
an address into the ledger to separate realised PnL, fees and funding.

We also completed a small mainnet round trip. The original estimate assumed
an eight-hour hold. For the two-second trade, the crossing and fee components
estimated about 9.12 basis points, matching the recorded cost after rounding.
That proves one working path, not universal accuracy.

Our initial target customer is a developer running a Hyperliquid trading
agent. The proposed business model is a transparent routing fee included in
the same cost check.

I built this from an earlier Binance cost-model experiment; that prior work
is disclosed. Next comes broader calibration and feedback from outside builders.

Costwall: know the cost before your agent trades.

## Pitch visuals
| Time | Show |
|---|---|
| 0:00–0:20 | Your face/name and Costwall title |
| 0:20–0:55 | Cost receipt; point to the components |
| 0:55–1:20 | README gateway diagram and ledger |
| 1:20–1:40 | Dated first-round-trip evidence |
| 1:40–2:00 | Your face, target customer and product URL |

Speak naturally and adjust pauses to finish near two minutes. These timings
are editing targets, not a measured recording duration.

## Demo — exact screen sequence
| Time | Action | Narration |
|---|---|---|
| 0:00–0:12 | Open https://lawnsonic.github.io/costwall/ | “This browser demo reads public data and cannot place orders.” |
| 0:12–0:42 | BTC, $25, Long, 8h hold, builder fee 0; Price | “It walks the book at this size. Here are entry crossing, estimated exit crossing, fees and a funding scenario. This is the cost hurdle, not a price prediction.” |
| 0:42–1:00 | Change builder fee to 5 bps; Price | “This is an illustrative input, not a charge from this website. Five basis points on each leg adds ten basis points to the model. Live prices can also change.” |
| 1:00–1:20 | Run the read-only $5 command below | “Below the venue minimum, the request is refused with a reason. Nothing is sent.” |
| 1:20–1:42 | Paste your main address into the ledger, seven days | “This separates returned realised PnL, fees and funding. It excludes open-position value and is not total account return.” |
| 1:42–2:12 | Show October 3 evidence and trade rows | “The original eight-hour estimate was 9.90 bps. Crossing and fees were about 9.12; the two-second round trip cost 9.1175. Both legs filled, and the recorded terminal reported position zero.” |
| 2:12–2:30 | Show a dated October 3 weekend refusal | “This historical check refused scheduled internal pricing. Weekday results differ. Unknown schedules also refuse.” |
| 2:30–2:40 | Show prior-work link, then product URL | “The website and local gateway work. Prior work is disclosed. Hosted MCP and broader calibration are next.” |

## Read-only PowerShell commands

Use a Python environment with requirements.txt installed.

    Set-Location D:\Others\costwall
    python -m hl.oracle BTC 5 BUY --hold-hours 8

Historical fills:

    Get-Content evidence/hl/trades.jsonl |
      ForEach-Object { $_ | ConvertFrom-Json } |
      Select-Object ts,action,coin,filled_qty,avg_px,reduce_only,outcome |
      Format-Table -AutoSize

Historical weekend refusal:

    Get-Content evidence/hl/scan/2026-10-03.jsonl |
      ForEach-Object { $_ | ConvertFrom-Json } |
      Where-Object reason -eq 'internal_price_session' |
      Select-Object -First 1 ts,coin,side,decision,reason |
      Format-List

Your public main account for the ledger:
0x74accd81929adc04311ca2d5f7178eb154769b54

Use the main account, not the agent-wallet address. Choose 30 days if the
seven-day window no longer includes the October 3 trade.

## Recording fallbacks
- Read live values from the screen. Do not promise a particular approval,
  cost or stock refusal; current markets and sessions change.
- If the API is unavailable, show dated evidence and label it historical.
- Do not lower thresholds or rerun a money-moving command for a cleaner take.
- Browser and Python estimates may differ with quote timing, caching,
  rounding and account fee tiers.
- The ledger rounds to cents; the evidence file preserves the tiny trade cost.
- Never show .env, keys, terminal environment dumps or wallet recovery screens.

## Export
Export two 1080p MP4 files. Watch each end to end, check audio and duration.
Upload to a video host accepted by the portal; public or unlisted links must
work signed out. Titles: “Costwall — Founder Pitch” and “Costwall — Product Demo”.
Paste both URLs into SUBMISSION.md and the submission form.
