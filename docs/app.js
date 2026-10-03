// Costwall in the browser: a port of hl/oracle.py, hl/sessions.py and
// hl/ledger.py. The Python files are the reference; this copy exists so a
// visitor can price a trade without installing anything. Public data only.

const API = "https://api.hyperliquid.xyz/info";
const REGISTRY_URL = "https://raw.githubusercontent.com/Lawnsonic/costwall/main/hl/xyz_registry.json";
const ZERO_ADDRESS = "0x0000000000000000000000000000000000000000";
const MIN_NOTIONAL = 10;
const MAX_COST_BPS = 50;
const MIN_EDGE_BPS = 10;
const MAX_BUILDER_BPS = 10;

async function q(body) {
  const r = await fetch(API, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`Hyperliquid answered ${r.status}`);
  return r.json();
}

const cache = new Map();
async function cached(key, ttlMs, fn) {
  const hit = cache.get(key);
  if (hit && Date.now() - hit.t < ttlMs) return hit.v;
  const v = await fn();
  cache.set(key, { t: Date.now(), v });
  return v;
}

const dexIndex = () => cached("dexs", 60e3, async () => {
  const raw = await q({ type: "perpDexs" });
  return Object.fromEntries(raw.map((d, i) => [d ? d.name : "", i]));
});
const meta = (dex) => cached(`meta:${dex}`, 30e3, async () => {
  const body = { type: "metaAndAssetCtxs" };
  if (dex) body.dex = dex;
  const [m, ctxs] = await q(body);
  return { universe: m.universe, ctxs };
});
const baseFees = () => cached("fees", 3600e3, () => q({ type: "userFees", user: ZERO_ADDRESS }));
let registry = null;
const loadRegistry = () => cached("registry", 3600e3, async () => {
  try { const r = await fetch(REGISTRY_URL); registry = r.ok ? await r.json() : null; }
  catch { registry = null; }
  return registry;
});

async function market(coin) {
  const dex = coin.includes(":") ? coin.split(":")[0] : "";
  const dexs = await dexIndex();
  if (!(dex in dexs)) throw Object.assign(new Error(`No dex called "${dex}"`), { reason: "unknown_market" });
  const { universe, ctxs } = await meta(dex);
  const i = universe.findIndex((a) => a.name === coin);
  if (i < 0) throw Object.assign(new Error(`No market called "${coin}"`), { reason: "unknown_market" });
  const a = universe[i], c = ctxs[i];
  return {
    coin, dex: dex || "main", hip3: !!dex, szDecimals: a.szDecimals, maxLeverage: a.maxLeverage,
    growthMode: a.growthMode === "enabled", feeScale: parseFloat(a.deployerFeeScale ?? "1"),
    delisted: !!a.isDelisted, funding: parseFloat(c.funding), markPx: parseFloat(c.markPx),
  };
}

async function takerBps(spec) {
  const f = await baseFees();
  let hip3 = 1, growth = 1;
  if (spec.hip3) {
    hip3 = spec.feeScale < 1 ? spec.feeScale + 1 : spec.feeScale * 2;
    growth = spec.growthMode ? 0.1 : 1;
  }
  const ref = 1 - parseFloat(f.activeReferralDiscount || "0");
  return { bps: parseFloat(f.userCrossRate) * hip3 * growth * ref * 1e4, hip3, growth };
}

async function book(coin) {
  const b = await q({ type: "l2Book", coin });
  const side = (lv) => lv.map((l) => [parseFloat(l.px), parseFloat(l.sz)]);
  return { bids: side(b.levels[0]), asks: side(b.levels[1]) };
}

function walk(levels, qty) {
  let need = qty, spend = 0, got = 0, total = 0;
  for (const [px, sz] of levels) {
    total += sz;
    if (need > 0) { const take = Math.min(need, sz); spend += take * px; got += take; need -= take; }
  }
  return { vwap: need > 1e-12 || got <= 0 ? null : spend / got, cover: total / qty };
}

// ---- sessions (hl/sessions.py) ----
const EQUITY_CLOSED = new Set(["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25"]);
const EQUITY_EARLY = new Set(["2026-11-27", "2026-12-24"]);
const OVERNIGHT_CLOSED = new Set(["2026-01-18", "2026-02-15", "2026-04-02", "2026-05-24", "2026-06-18", "2026-07-02", "2026-09-06", "2026-11-25", "2026-12-24"]);
const FUTURES_HOLIDAYS = new Set(["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-02", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-11-27", "2026-12-24", "2026-12-25", "2026-12-31"]);

function nthSunday(y, month, n) {
  const first = new Date(Date.UTC(y, month - 1, 1)).getUTCDay();
  return Date.UTC(y, month - 1, 1 + ((7 - first) % 7) + 7 * (n - 1));
}
function eastern(t) {
  const y = new Date(t).getUTCFullYear();
  const dst = t >= nthSunday(y, 3, 2) + 7 * 3600e3 && t < nthSunday(y, 11, 1) + 6 * 3600e3;
  const e = new Date(t - (dst ? 4 : 5) * 3600e3);
  const ymd = e.toISOString().slice(0, 10);
  const prev = new Date(e.getTime() - 86400e3).toISOString().slice(0, 10);
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return { wd: (e.getUTCDay() + 6) % 7, mins: e.getUTCHours() * 60 + e.getUTCMinutes(), ymd, prev,
           label: `${days[e.getUTCDay()]} ${e.toISOString().slice(11, 16)} ET` };
}
function session(schedule, t = Date.now()) {
  const e = eastern(t), { wd, mins: m } = e;
  const weekend = (openSun, closeFri) => wd === 5 || (wd === 6 && m < openSun) || (wd === 4 && m >= closeFri);
  let s;
  if (schedule === "us_equity_24_5") {
    if (weekend(1200, 1200)) s = ["internal", "weekend"];
    else if (m >= 1200) s = OVERNIGHT_CLOSED.has(e.ymd) ? ["internal", "overnight holiday closure"] : ["external", "overnight"];
    else if (m < 240) s = OVERNIGHT_CLOSED.has(e.prev) ? ["internal", "overnight holiday closure"] : ["external", "overnight"];
    else if (EQUITY_CLOSED.has(e.ymd)) s = ["internal", "equity holiday"];
    else if (EQUITY_EARLY.has(e.ymd) && m >= 780) s = ["internal", "early close"];
    else s = ["external", m < 570 ? "pre-market" : m < 960 ? "regular" : "post-market"];
  } else if (schedule === "futures") {
    if (FUTURES_HOLIDAYS.has(e.ymd)) s = ["internal", "futures holiday"];
    else if (weekend(1080, 1020)) s = ["internal", "weekend"];
    else if (wd <= 3 && m >= 1020 && m < 1080) s = ["internal", "daily maintenance break"];
    else s = ["external", "open"];
  } else if (schedule === "fx") {
    s = weekend(1020, 1020) ? ["internal", "weekend"] : ["external", "open"];
  } else s = ["internal", "schedule unknown"];
  return { state: s[0], why: s[1], eastern: e.label, schedule };
}

async function priceSource(spec) {
  if (!spec.hip3) return null;
  const reg = spec.dex === "xyz" ? await loadRegistry() : null;
  const entry = reg && reg.markets[spec.coin];
  return session(entry ? entry.schedule : "unknown");
}

// ---- the oracle (hl/oracle.py evaluate_perp) ----
async function evaluate({ coin, notional, side, hold = 8, builderBps = 0, expectedMove = null, acceptInternal = false, preBook = null }) {
  const isBuy = side === "BUY";
  const out = { coin, side, notional };
  const refuse = (reason, detail, extra = {}) => ({ ...out, decision: "REJECT", reason, detail, ...extra });
  let spec;
  try { spec = await market(coin); }
  catch (e) { return refuse(e.reason || "pricing_failed", e.message); }
  if (spec.delisted) return refuse("delisted", "This market is delisted.");
  if (builderBps > MAX_BUILDER_BPS) return refuse("builder_fee_above_cap", `Hyperliquid caps builder fees on perps at ${MAX_BUILDER_BPS} bps.`);
  const source = await priceSource(spec);
  if (source && source.state === "internal" && !acceptInternal)
    return refuse("internal_price_session", `${source.why[0].toUpperCase() + source.why.slice(1)} (${source.eastern}). The real exchange is closed, so this market is priced by its own order book. What the position is worth at reopen can't be measured.`, { source });

  let b, fee;
  try { [b, fee] = await Promise.all([preBook || book(coin), takerBps(spec)]); }
  catch (e) { return refuse("pricing_failed", e.message); }
  if (!b.bids.length || !b.asks.length) return refuse("empty_book", "The order book is empty.");
  const mid = (b.bids[0][0] + b.asks[0][0]) / 2;
  const step = 10 ** spec.szDecimals;
  const qty = Math.floor((notional / mid) * step + 1e-9) / step;
  const priced = qty * mid;
  if (priced < MIN_NOTIONAL) return refuse("below_venue_minimum", `$${priced.toFixed(2)} after rounding the size; Hyperliquid's minimum order is $${MIN_NOTIONAL}.`);
  const entry = walk(isBuy ? b.asks : b.bids, qty), exit = walk(isBuy ? b.bids : b.asks, qty);
  if (entry.vwap === null || exit.vwap === null) return refuse("insufficient_depth", `The visible book covers ${entry.cover.toFixed(2)}× this order.`);

  const cost = {
    entry: Math.abs(entry.vwap - mid) / mid * 1e4,
    exit: Math.abs(exit.vwap - mid) / mid * 1e4,
    fees: 2 * fee.bps,
    builder: 2 * builderBps,
  };
  const fundingSigned = spec.funding * hold * 1e4 * (isBuy ? 1 : -1);
  cost.funding = Math.max(0, fundingSigned);
  const total = cost.entry + cost.exit + cost.fees + cost.builder + cost.funding;
  let approved, reason, shortfall, test;
  if (expectedMove !== null && expectedMove !== "") {
    const need = total + MIN_EDGE_BPS;
    approved = expectedMove >= need; shortfall = need - expectedMove;
    reason = approved ? "edge_clears_cost" : "edge_below_cost"; test = `your expected move must clear ${need.toFixed(2)} bps`;
  } else {
    approved = total <= MAX_COST_BPS; shortfall = total - MAX_COST_BPS;
    reason = approved ? "cost_within_ceiling" : "cost_exceeds_ceiling"; test = `cost ceiling ${MAX_COST_BPS} bps`;
  }
  return { ...out, decision: approved ? "APPROVE" : "REJECT", reason, shortfall, test, cost, total, fundingSigned,
           qty, priced, mid, takerBps: fee.bps, hip3Scale: fee.hip3, growthScale: fee.growth, hold, source };
}

// ---- receipt ----
const fmt = (x, d = 2) => (Math.round(x * 10 ** d) / 10 ** d).toFixed(d);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const REASONS = {
  internal_price_session: "Real exchange closed",
  below_venue_minimum: "Below the $10 minimum",
  insufficient_depth: "Book too thin for this size",
  unknown_market: "No such market",
  cost_exceeds_ceiling: "Costs more than 50 bps",
  edge_below_cost: "Expected move too small",
  builder_fee_above_cap: "Builder fee over the cap",
  delisted: "Delisted",
  pricing_failed: "Couldn't price it",
  empty_book: "Empty book",
};

function renderReceipt(v) {
  const el = document.getElementById("receipt");
  const ok = v.decision === "APPROVE";
  const now = new Date().toISOString().slice(0, 19).replace("T", " ");
  const line = (k, val, dim = false) => `<div class="r-line${dim ? " dim" : ""}"><span>${k}</span><span class="v">${val}</span></div>`;
  let body = `<p class="r-head">COSTWALL<br><span>pre-trade receipt</span></p>
    <p class="r-meta">${esc(v.coin)} ${v.side === "BUY" ? "long" : "short"}<br>$${fmt(v.notional, 0)} requested<br>${now} UTC</p>
    <span class="stamp ${ok ? "ok" : "no"}">${ok ? "APPROVED" : "REFUSED"}</span><hr class="r-rule">`;
  if (v.cost) {
    body += line("Spread in", `${fmt(v.cost.entry)} bps`) + line("Spread out", `${fmt(v.cost.exit)} bps`)
      + line(`Taker fee ×2`, `${fmt(v.cost.fees)} bps`) + line("Builder fee ×2", `${fmt(v.cost.builder)} bps`, v.cost.builder === 0)
      + line(`Funding, ${v.hold}h`, `${fmt(v.cost.funding)} bps`, v.cost.funding === 0)
      + `<hr class="r-rule"><div class="r-line r-total"><span>Price must move</span><span></span></div>
         <p class="r-big">${fmt(v.total)} bps</p><p class="r-line dim"><span>in your favour to break even</span></p>
         <hr class="r-rule">${line("Size", `${v.qty} ${esc(v.coin.replace(/^.*:/, ""))}`)}${line("Value", `$${fmt(v.priced)}`)}${line("Mid", fmt(v.mid, v.mid < 1 ? 6 : 2))}`
      + `<p class="r-note">Taker ${fmt(v.takerBps, 3)} bps (base tier${v.hip3Scale !== 1 ? `, HIP-3 ×${v.hip3Scale}` : ""}${v.growthScale !== 1 ? `, growth mode ×${v.growthScale}` : ""}). ${v.fundingSigned < 0 ? `Funding runs your way (${fmt(-v.fundingSigned)} bps) but isn't counted.` : ""} ${ok ? "" : `Over by ${fmt(v.shortfall)} bps: ${esc(v.test)}.`}</p>`;
  } else {
    body += `<p class="r-why"><b>${esc(REASONS[v.reason] || v.reason)}</b></p><p class="r-note">${esc(v.detail || "")}</p>`;
  }
  el.innerHTML = body;
  el.dataset.state = ok ? "ok" : "no";
  el.classList.remove("printing"); void el.offsetWidth; el.classList.add("printing");
}

document.getElementById("price-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("price-btn");
  btn.disabled = true; btn.textContent = "Reading the book…";
  try {
    const v = await evaluate({
      coin: document.getElementById("coin").value.trim(),
      notional: parseFloat(document.getElementById("notional").value),
      side: document.querySelector("input[name=side]:checked").value,
      hold: parseFloat(document.getElementById("hold").value || "0"),
      builderBps: parseFloat(document.getElementById("builder").value || "0"),
      acceptInternal: document.getElementById("accept-internal").checked,
    });
    renderReceipt(v);
  } catch (err) {
    renderReceipt({ coin: "?", side: "BUY", notional: 0, decision: "REJECT", reason: "pricing_failed", detail: err.message });
  } finally { btn.disabled = false; btn.textContent = "Price this trade"; }
});

// ---- ledger (hl/ledger.py) ----
async function paged(type, user, start, end) {
  let rows = [], cursor = start;
  for (let i = 0; i < 30 && cursor < end; i++) {
    const page = await q({ type, user, startTime: cursor, endTime: end });
    if (!page.length) break;
    rows = rows.concat(page);
    const last = Math.max(...page.map((r) => r.time));
    if (last < cursor || page.length < 500) break;
    cursor = last + 1;
  }
  const seen = new Set();
  return rows.filter((r) => { const k = `${r.tid}|${r.hash}|${r.time}|${JSON.stringify(r.delta || "")}`; if (seen.has(k)) return false; seen.add(k); return true; });
}

const money = (x) => `${x < 0 ? "−" : ""}$${Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function waterfall(steps) {
  let run = 0;
  const pts = steps.map((s) => { const from = s.total ? 0 : run; const to = s.total ? s.value : run + s.value; if (!s.total) run = to; return { ...s, from, to }; });
  const lo = Math.min(0, ...pts.flatMap((p) => [p.from, p.to])), hi = Math.max(0, ...pts.flatMap((p) => [p.from, p.to]));
  const span = hi - lo || 1, x = (v) => ((v - lo) / span) * 100;
  return `<div class="fall" role="img" aria-label="${esc(steps.map((s) => `${s.label} ${money(s.value)}`).join(", "))}">` + pts.map((p) => {
    const l = x(Math.min(p.from, p.to)), w = Math.abs(x(p.to) - x(p.from));
    const cls = p.total ? "total" : p.value < 0 ? "neg" : "pos";
    return `<div class="fall-row"><span>${p.label}</span><div class="fall-track"><span class="fall-zero" style="left:${x(0)}%"></span><span class="fall-bar ${cls}" style="left:${l}%;width:${w}%"></span></div><span class="fall-val">${money(p.value)}</span></div>`;
  }).join("") + "</div>";
}

document.getElementById("ledger-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const out = document.getElementById("ledger-out"), btn = document.getElementById("ledger-btn");
  const user = document.getElementById("address").value.trim().toLowerCase();
  const days = parseFloat(document.getElementById("days").value);
  btn.disabled = true; btn.textContent = "Reading fills…";
  out.innerHTML = `<p class="muted">Reading fills and funding for ${esc(user.slice(0, 6))}…${esc(user.slice(-4))}.</p>`;
  try {
    const end = Date.now(), start = end - days * 86400e3;
    const [fills, funding] = await Promise.all([paged("userFillsByTime", user, start, end), paged("userFunding", user, start, end)]);
    const by = {};
    const get = (c) => (by[c] ||= { fills: 0, volume: 0, closed: 0, exch: 0, builder: 0, funding: 0 });
    let otherFees = 0;
    for (const f of fills) {
      const c = get(f.coin), builder = parseFloat(f.builderFee || "0");
      c.fills++; c.volume += parseFloat(f.px) * parseFloat(f.sz); c.closed += parseFloat(f.closedPnl);
      if ((f.feeToken || "USDC") === "USDC") { c.exch += parseFloat(f.fee) - builder; c.builder += builder; }
      else otherFees++;
    }
    for (const r of funding) get(r.delta.coin).funding += parseFloat(r.delta.usdc);
    const t = Object.values(by).reduce((a, c) => { for (const k in c) a[k] = (a[k] || 0) + c[k]; return a; }, {});
    if (!fills.length && !funding.length) {
      out.innerHTML = `<p>No fills or funding for this address in the last ${days} day${days === 1 ? "" : "s"}. Try a longer window, or check the address.</p>`;
      return;
    }
    const naive = t.closed || 0, minusExch = naive - (t.exch || 0), net = minusExch - (t.builder || 0) + (t.funding || 0);
    const allFees = (t.exch || 0) + (t.builder || 0);
    const rows = Object.entries(by).sort((a, b) => b[1].volume - a[1].volume).slice(0, 15);
    out.innerHTML = `
      <div class="trio">
        <div><div class="k">Adding up closedPnl</div><div class="n">${money(naive)}</div></div>
        <div><div class="k">Minus exchange fees</div><div class="n">${money(minusExch)}</div></div>
        <div class="truth"><div class="k">True net</div><div class="n">${money(net)}</div></div>
      </div>
      ${waterfall([
        { label: "closedPnl", value: naive },
        { label: "Exchange fees", value: -(t.exch || 0) },
        { label: "Builder fees", value: -(t.builder || 0) },
        { label: "Funding", value: t.funding || 0 },
        { label: "True net", value: net, total: true },
      ])}
      <p class="muted">${fills.length.toLocaleString()} fills, ${money(t.volume || 0).replace("$", "$")} traded over ${days} day${days === 1 ? "" : "s"}.${allFees > 0 ? ` Builder fees were ${Math.round(((t.builder || 0) / allFees) * 100)}% of all fees paid.` : ""}${fills.length >= 10000 ? " Hyperliquid limits history to 10,000 fills, so totals may be incomplete." : ""}${otherFees ? ` ${otherFees} fills paid fees in another token and aren't counted.` : ""}</p>
      <details class="coins"><summary>By market</summary><div class="table-scroll"><table>
        <thead><tr><th>Market</th><th class="num">Fills</th><th class="num">closedPnl</th><th class="num">Exchange fees</th><th class="num">Builder fees</th><th class="num">Funding</th></tr></thead>
        <tbody>${rows.map(([c, r]) => `<tr><td>${esc(c)}</td><td class="num">${r.fills}</td><td class="num">${money(r.closed)}</td><td class="num">${money(-r.exch)}</td><td class="num">${money(-r.builder)}</td><td class="num">${money(r.funding)}</td></tr>`).join("")}</tbody>
      </table></div></details>`;
  } catch (err) {
    out.innerHTML = `<p class="error">Couldn't read this address: ${esc(err.message)}. Check it is a 0x address with 40 hex characters.</p>`;
  } finally { btn.disabled = false; btn.textContent = "Show the ledger"; }
});

// ---- board ----
async function topMarkets() {
  const pick = async (dex, n) => {
    const { universe, ctxs } = await meta(dex);
    return universe.map((a, i) => ({ name: a.name, vol: parseFloat(ctxs[i].dayNtlVlm), dead: a.isDelisted }))
      .filter((m) => !m.dead).sort((a, b) => b.vol - a.vol).slice(0, n).map((m) => m.name);
  };
  return [...(await pick("", 8)), ...(await pick("xyz", 8))];
}

function cell(v) {
  if (v.decision === "APPROVE") return `<span class="cell-ok"><b>${fmt(v.total)} bps</b><span class="sub">approved</span></span>`;
  const extra = v.cost ? `, ${fmt(v.total)} bps` : "";
  return `<span class="cell-no">${esc(REASONS[v.reason] || v.reason)}${extra}<span class="sub">refused</span></span>`;
}

async function runBoard() {
  const out = document.getElementById("board-out"), btn = document.getElementById("board-btn");
  btn.disabled = true;
  try {
    const coins = await topMarkets();
    const results = await Promise.all(coins.map(async (coin) => {
      let pre = null;
      try { pre = await book(coin); } catch { /* evaluate reports it */ }
      const [l, s] = await Promise.all(["BUY", "SELL"].map((side) => evaluate({ coin, notional: 25, side, hold: 8, preBook: pre })));
      return { coin, l, s };
    }));
    const all = results.flatMap((r) => [r.l, r.s]);
    const ok = all.filter((v) => v.decision === "APPROVE").length;
    const counts = {};
    all.filter((v) => v.decision !== "APPROVE").forEach((v) => { counts[v.reason] = (counts[v.reason] || 0) + 1; });
    const why = Object.entries(counts).map(([r, n]) => `${n} ${(REASONS[r] || r).toLowerCase()}`).join(", ");
    out.innerHTML = `<p class="summary">${ok} of ${all.length} approved${why ? `; refused: ${why}` : ""}. Priced at ${new Date().toLocaleTimeString()}.</p>
      <div class="table-scroll"><table><thead><tr><th>Market</th><th>Long</th><th>Short</th></tr></thead>
      <tbody>${results.map((r) => `<tr><td>${esc(r.coin)}</td><td>${cell(r.l)}</td><td>${cell(r.s)}</td></tr>`).join("")}</tbody></table></div>`;
    const list = document.getElementById("coins");
    if (!list.children.length) list.innerHTML = coins.map((c) => `<option value="${esc(c)}">`).join("");
  } catch (err) {
    out.innerHTML = `<p class="error">Couldn't reach Hyperliquid: ${esc(err.message)}. Press Refresh to try again.</p>`;
  } finally { btn.disabled = false; }
}

document.getElementById("board-btn").addEventListener("click", runBoard);
loadRegistry();
runBoard();
