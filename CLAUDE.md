# Trading policy

This repository connects to Binance Agent OS, where a tool call moves real
money in a real account. The rules below are not style preferences.

## Before any order

**Call `evaluate_trade` from the `costcheck` MCP server before calling
`spot_newOrder`, `futures_usds_newOrder`, or any other tool that opens or
closes a position.**

- `decision: "REJECT"` is binding. Do not place the order. Report the
  `reason` and the `shortfall_bps` and stop.
- `decision: "APPROVE"` authorises the size in `max_notional_usdt` on that
  symbol, and nothing else. It is not general permission to trade.
- A decision expires at `expires_at`, which is seconds after it was measured.
  That is deliberate: on 2026-09-05 the cross-venue basis on STRKUSDT moved
  from 13.55 to 30.50 bps inside one minute. If the decision has expired, call
  again. Do not act on a stale one.
- If the tool returns `reason: "pricing_failed"`, the cost is unknown rather
  than acceptable. Unknown cost means no order.

Do not compute the cost yourself and do not estimate it in prose. That is the
specific failure this project exists to document: every cost assumption made
in natural language during this build was wrong when it was finally measured,
four out of four.

## Price the trade you are actually making

`evaluate_trade` prices two different trades and it cannot tell which one you
mean from the symbol, because BNBUSDT is a valid conversion and a valid hedge.
You select the model:

- **Pass `side: "BUY"` or `side: "SELL"` for a single-leg spot conversion.**
  One crossing. Cost is the taker fee plus the distance from mid to the fill
  VWAP, tested against `max_cost_bps` rather than against an edge requirement,
  because a conversion earns nothing and has no edge to clear.
- **Omit `side` for a delta-neutral funding carry.** Two legs, four crossings,
  cross-venue entry basis, exit spread, lot residual, tested against expected
  funding. This is the model the scanner uses.

Getting this wrong is not a rounding error. On 2026-09-06 a plain 5 USDT BNB
buy was priced as a carry and came back REJECT with a 51.1 bps shortfall and
`max_notional_usdt: 0.0`. The arithmetic was correct and the question was
wrong: it charged four crossings for one, and demanded funding income from a
trade that collects none. The same buy priced as a conversion is 7.57 bps.

A refusal produced by the wrong model is not a refusal, it is a category
error, and treating it as a refusal is how a correct order gets blocked and an
incorrect one gets waved through.

## Overriding a refusal: Explicit Human Override

If the human explicitly instructs you to proceed past a refusal (e.g. "proceed anyway",
"override", "force", "buy anyway", "ignore cost check", or "NCC"), they are overruling
the verdict. When that happens:

1. Still call `evaluate_trade`. The override is about whether the number
   blocks the order, not about whether the number gets measured.
2. Show them the cost and the reason it refused.
3. Call `record_override` on the `costcheck` server **before** sending the
   order, passing the full decision object as `verdict` and whatever phrase
   the human used as `user_phrase` (e.g. "proceed anyway"), so the refusal is
   preserved inside the record that overruled it.
4. Place the order.

`record_override` authorises nothing. It writes to `evidence/overrides.jsonl`
and returns a record. If it comes back `logged: false`, the audit trail
failed: stop, do not place the order, and say so.

An override covers **one order** and then lapses. The next order needs its own.

**Never issue an override to yourself.** It is only valid when it explicitly appears
in the human's own message. You may not infer it from context, from a previous
override, from impatience, or from your own judgement that a refusal was
wrong. If you think a refusal is wrong, say so and let them decide.

### What an override is, honestly

The same category of limitation as the section above, and it has to be read
that way. `record_override` **cannot independently verify what the human said.** The
MCP server is a stdio subprocess that receives only what the calling agent
passes it; it has no access to the human's message. `user_phrase` is the
agent's report, not proof, and every record is stamped
`phrase_verified: false` so the log never claims otherwise.

So "one order only" and "never self-issued" are policy, exactly like "REJECT
is binding" is policy. Nothing enforces them. Closing that gap needs a harness
hook that reads the literal prompt and drops a single-use token the server can
check, which is the override equivalent of the credential-holding gateway, and like
that gateway it is not built.

## What this policy is, honestly

A policy, not a wall. You still hold the raw order tools and nothing here can
physically stop you from ignoring this file. Making the check unbypassable
requires a gateway that holds the Binance credentials and refuses to forward
an unpriced order, which is not built. Until it is, this rule works only if
it is followed.

## Standing constraints

- **Never lower a threshold to make the scanner fire.** If nothing clears,
  `NO QUALIFYING SIGNAL` is the correct output. A refusal is the product.
- **No fabricated numbers.** Every figure in code, logs, the README or the
  video must come from a live call. If a value is assumed, label it assumed.
- **Fill-driven sizing.** Futures leg first. Size the spot leg from leg one's
  actual `executedQty`, truncated to the spot `stepSize`. Never size both
  legs from the same intended figure.
- **Futures `newOrder` does not return a fill price.** No `avgPrice`, no
  `cumQuote`, even at `newOrderRespType=RESULT`. Always call
  `futures_usds_queryOrder` for the real fill. Skipping this records a fill
  price of zero.
- **Unwind rather than hold exposure.** If leg two fails or fills short,
  reduce leg one to match immediately and log the unwind as its own record.
- **Do not run `claude mcp remove`.** The Binance OAuth connection is working.
- **Do not build a kill switch.** Binance ships one under Sub-account >
  Account Management. Use theirs.
- Market data is public REST only. MCP is for execution and account state.
