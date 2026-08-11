// ─────────────────────────────────────────────────────────────────────────
// Alpaca Trend-Following Trading Bot — Cloudflare Worker (paper trading)
//
// Routes:
//   /        live dashboard (read-only, safe to open any time)
//   /run     execute one evaluation tick now
//   /api     the dashboard's data as JSON
//
// Bindings/secrets (Cloudflare dashboard → Settings → Variables and secrets):
//   ALPACA_API_KEY     Secret    Alpaca PAPER key id ("PK…")
//   ALPACA_API_SECRET  Secret    Alpaca PAPER secret
//   DRY_RUN            Plaintext "true" simulates, "false" places paper orders
//   STATE              KV namespace binding
// ─────────────────────────────────────────────────────────────────────────

const CONFIG = {
  // US stocks and ETFs — only tradable while the US market is open.
  stocks: ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
           "NFLX", "JPM", "V", "COST", "XOM", "WMT",
           "SPY", "QQQ", "IWM"],
  // Crypto trades 24/7, so the bot stays active nights and weekends.
  crypto: ["BTC/USD", "ETH/USD", "LTC/USD"],

  timeframe: "1Hour",          // bar size used for the moving averages
  bars: 60,                    // how many recent bars to keep
  lookbackDays: 20,            // how far back to ask Alpaca for bars
  maxPages: 8,                 // safety cap when paging through bar history
  fast: 10,                    // fast moving-average length
  slow: 30,                    // slow moving-average length
  trailingStopPct: 5.0,        // exit if price drops this % below its post-entry high
  tradeNotionalUsd: 1000,      // $ per entry
  maxOrderNotionalUsd: 2000,   // hard risk cap per order
  maxOpenPositions: 10,        // never hold more than this many at once
  historyLimit: 60,            // how many past events the dashboard shows
  timeZone: "Europe/Berlin",   // times are rendered in this zone
  dataUrl: "https://data.alpaca.markets",
  tradingUrl: "https://paper-api.alpaca.markets",
};

// ── helpers ────────────────────────────────────────────────────────────────
function authHeaders(env) {
  return {
    "APCA-API-KEY-ID": env.ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": env.ALPACA_API_SECRET,
    "accept": "application/json",
  };
}

function isDryRun(env) {
  return (env.DRY_RUN ?? "true").toString().toLowerCase() !== "false";
}

function sma(values, n) {
  if (values.length < n) return null;
  return values.slice(-n).reduce((a, b) => a + b, 0) / n;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function money(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString("de-DE", {
    style: "currency", currency: "USD", maximumFractionDigits: 2,
  });
}

function num(n, digits = 2) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return Number(n).toFixed(digits);
}

function localTime(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("de-DE", {
      timeZone: CONFIG.timeZone, dateStyle: "short", timeStyle: "medium",
    });
  } catch { return iso; }
}

function agoText(iso) {
  if (!iso) return "";
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `vor ${secs}s`;
  if (secs < 3600) return `vor ${Math.round(secs / 60)} Min`;
  if (secs < 86400) return `vor ${Math.round(secs / 3600)} Std`;
  return `vor ${Math.round(secs / 86400)} Tagen`;
}

// ── Alpaca calls ───────────────────────────────────────────────────────────
// All instruments the bot watches, each tagged with its asset class.
function allInstruments() {
  return [
    ...CONFIG.stocks.map((symbol) => ({ symbol, cls: "stock" })),
    ...CONFIG.crypto.map((symbol) => ({ symbol, cls: "crypto" })),
  ];
}

// Fetch closing prices for a whole list of symbols in one request (paging as
// needed). One batched call scales to dozens of instruments; one call per
// symbol would not. Returns { SYMBOL: [close, …] }, oldest → newest.
async function fetchCloses(env, symbols, cls) {
  if (!symbols.length) return {};
  // Without an explicit start, Alpaca only returns today's bars — far too few
  // for a 30-period average.
  const start = new Date(Date.now() - CONFIG.lookbackDays * 86400_000)
    .toISOString().slice(0, 10);
  const base = cls === "crypto"
    ? `${CONFIG.dataUrl}/v1beta3/crypto/us/bars`
    : `${CONFIG.dataUrl}/v2/stocks/bars`;

  const out = {};
  let pageToken = null, pages = 0;
  do {
    const p = new URLSearchParams({
      symbols: symbols.join(","), timeframe: CONFIG.timeframe,
      start, limit: "10000", sort: "asc",
    });
    if (cls === "stock") { p.set("adjustment", "raw"); p.set("feed", "iex"); }
    if (pageToken) p.set("page_token", pageToken);

    const r = await fetch(`${base}?${p}`, { headers: authHeaders(env) });
    if (!r.ok) throw new Error(`${cls} bars: ${r.status} ${await r.text()}`);
    const j = await r.json();
    for (const [sym, arr] of Object.entries(j.bars || {})) {
      (out[sym] ||= []).push(...(arr || []).map((b) => b.c));
    }
    pageToken = j.next_page_token || null;
  } while (pageToken && ++pages < CONFIG.maxPages);

  for (const sym of Object.keys(out)) out[sym] = out[sym].slice(-CONFIG.bars);
  return out;
}

async function marketOpen(env) {
  try {
    const r = await fetch(`${CONFIG.tradingUrl}/v2/clock`, { headers: authHeaders(env) });
    if (!r.ok) return false;
    return !!(await r.json()).is_open;
  } catch {
    return false; // fail closed: if unsure, do not trade
  }
}

async function getAccount(env) {
  const r = await fetch(`${CONFIG.tradingUrl}/v2/account`, { headers: authHeaders(env) });
  if (!r.ok) throw new Error(`account: ${r.status}`);
  return r.json();
}

async function getPositions(env) {
  const r = await fetch(`${CONFIG.tradingUrl}/v2/positions`, { headers: authHeaders(env) });
  if (!r.ok) throw new Error(`positions: ${r.status}`);
  return r.json();
}

async function getOrders(env, limit = 15) {
  const r = await fetch(
    `${CONFIG.tradingUrl}/v2/orders?status=all&limit=${limit}&direction=desc`,
    { headers: authHeaders(env) });
  if (!r.ok) throw new Error(`orders: ${r.status}`);
  return r.json();
}

async function enterLong(env, symbol, cls) {
  if (CONFIG.tradeNotionalUsd > CONFIG.maxOrderNotionalUsd) {
    throw new Error(`notional ${CONFIG.tradeNotionalUsd} exceeds risk cap`);
  }
  if (isDryRun(env)) return "[DRY-RUN] simuliert";
  const body = {
    symbol, notional: String(CONFIG.tradeNotionalUsd),
    side: "buy", type: "market",
    time_in_force: cls === "crypto" ? "gtc" : "day",
  };
  const r = await fetch(`${CONFIG.tradingUrl}/v2/orders`, {
    method: "POST",
    headers: { ...authHeaders(env), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`buy ${symbol}: ${r.status} ${await r.text()}`);
  return "Order platziert";
}

async function closePosition(env, symbol) {
  if (isDryRun(env)) return "[DRY-RUN] simuliert";
  // Positions are keyed without the slash for crypto (BTC/USD → BTCUSD).
  const posSymbol = symbol.replace("/", "");
  const r = await fetch(`${CONFIG.tradingUrl}/v2/positions/${encodeURIComponent(posSymbol)}`, {
    method: "DELETE", headers: authHeaders(env),
  });
  if (!r.ok && r.status !== 404) throw new Error(`close ${symbol}: ${r.status} ${await r.text()}`);
  return "Position geschlossen";
}

// ── State (Workers KV) ─────────────────────────────────────────────────────
async function loadState(env) {
  const raw = await env.STATE.get("positions");
  return raw ? JSON.parse(raw) : {};
}

async function loadHistory(env) {
  const raw = await env.STATE.get("history");
  return raw ? JSON.parse(raw) : [];
}

// ── One evaluation tick ────────────────────────────────────────────────────
async function runTick(env) {
  const dryRun = isDryRun(env);
  const state = await loadState(env);
  const history = await loadHistory(env);
  const now = new Date().toISOString();
  const rows = [];

  // Stocks only trade during US market hours; crypto trades around the clock.
  const stocksOpen = await marketOpen(env);
  const tradable = { stock: stocksOpen, crypto: true };

  // One batched price request per asset class, not one per symbol.
  const [stockBars, cryptoBars] = await Promise.all([
    fetchCloses(env, CONFIG.stocks, "stock").catch((e) => ({ __error: e.message })),
    fetchCloses(env, CONFIG.crypto, "crypto").catch((e) => ({ __error: e.message })),
  ]);

  // Respect the cap on how many positions may be open at once.
  let openCount = Object.values(state).filter((p) => p && p.long).length;

  for (const { symbol, cls } of allInstruments()) {
    const row = { symbol, cls, price: null, fast: null, slow: null,
                  long: false, high: null, action: "warte", error: null };
    const source = cls === "crypto" ? cryptoBars : stockBars;
    try {
      if (source.__error) throw new Error(source.__error);
      const closes = source[symbol] || [];
      const price = closes[closes.length - 1];
      const fast = sma(closes, CONFIG.fast);
      const slow = sma(closes, CONFIG.slow);
      if (price == null || fast == null || slow == null) {
        row.error = `zu wenig Daten (${closes.length} von ${CONFIG.slow} Kerzen)`;
        rows.push(row);
        continue;
      }

      const pos = state[symbol] || { long: false, high: 0 };
      let action = "halten";
      let event = null;

      if (!pos.long) {
        if (fast > slow) {
          if (!tradable[cls]) {
            action = "Kaufsignal — Börse zu, wartet";
          } else if (openCount >= CONFIG.maxOpenPositions) {
            action = `Kaufsignal — Limit von ${CONFIG.maxOpenPositions} Positionen erreicht`;
          } else {
            const res = await enterLong(env, symbol, cls);
            pos.long = true; pos.high = price;
            pos.entry = price; pos.since = now; pos.simulated = dryRun;
            openCount++;
            action = `KAUF — ${res}`;
            event = { time: now, symbol, kind: "BUY", price, note: res };
          }
        }
      } else {
        pos.high = Math.max(pos.high, price);
        const drawdown = (pos.high - price) / pos.high;
        const crossDown = fast < slow;
        const stopHit = drawdown >= CONFIG.trailingStopPct / 100;
        if (crossDown || stopHit) {
          if (tradable[cls]) {
            const res = await closePosition(env, symbol);
            const pl = pos.entry ? ((price - pos.entry) / pos.entry) * 100 : null;
            pos.long = false; pos.entry = null; pos.since = null;
            openCount = Math.max(0, openCount - 1);
            const why = crossDown ? "Trend gedreht" : "Trailing-Stop";
            action = `VERKAUF (${why}) — ${res}`;
            event = { time: now, symbol, kind: "SELL", price, pl,
                      note: `${why} · ${res}` };
          } else {
            action = "Verkaufssignal — Börse zu, wartet";
          }
        }
      }

      state[symbol] = pos;
      Object.assign(row, { price, fast, slow, long: pos.long, high: pos.high,
                           entry: pos.entry ?? null, since: pos.since ?? null,
                           simulated: !!pos.simulated, action });
      if (event) history.unshift(event);
    } catch (e) {
      row.error = e.message;
    }
    rows.push(row);
  }

  // Sort so anything the bot is actually holding, and any uptrend, floats up.
  const rank = (r) => (r.error ? 3 : r.long ? 0 : r.fast > r.slow ? 1 : 2);
  rows.sort((a, b) => rank(a) - rank(b) || a.symbol.localeCompare(b.symbol));

  const summary = { time: now, mode: dryRun ? "DRY-RUN" : "LIVE",
                    marketOpen: stocksOpen, openCount, rows };
  await env.STATE.put("positions", JSON.stringify(state));
  await env.STATE.put("history", JSON.stringify(history.slice(0, CONFIG.historyLimit)));
  await env.STATE.put("last_run", JSON.stringify(summary));
  console.log(JSON.stringify(summary));
  return summary;
}

// ── Dashboard data ─────────────────────────────────────────────────────────
async function collectDashboardData(env) {
  const [lastRaw, history, account, positions, orders] = await Promise.all([
    env.STATE.get("last_run"),
    loadHistory(env),
    getAccount(env).catch((e) => ({ error: e.message })),
    getPositions(env).catch(() => []),
    getOrders(env).catch(() => []),
  ]);
  return {
    lastRun: lastRaw ? JSON.parse(lastRaw) : null,
    history,
    account,
    positions: Array.isArray(positions) ? positions : [],
    orders: Array.isArray(orders) ? orders : [],
    dryRun: isDryRun(env),
    config: CONFIG,
  };
}

// ── Dashboard rendering ────────────────────────────────────────────────────
function renderDashboard(d) {
  const acct = d.account && !d.account.error ? d.account : null;
  const equity = acct ? Number(acct.equity) : null;
  const lastEquity = acct ? Number(acct.last_equity) : null;
  const dayPl = equity != null && lastEquity ? equity - lastEquity : null;
  const dayPlPct = dayPl != null && lastEquity ? (dayPl / lastEquity) * 100 : null;

  const openPl = d.positions.reduce((s, p) => s + Number(p.unrealized_pl || 0), 0);

  // In DRY-RUN nothing is really bought — the bot only books entries on paper.
  // Track those separately so the dashboard never implies positions that
  // do not exist at the broker.
  const simLongs = (d.lastRun?.rows || []).filter((r) => r.long && !r.error);
  const simPl = simLongs.reduce((s, r) => (
    r.entry ? s + ((r.price - r.entry) / r.entry) * CONFIG.tradeNotionalUsd : s
  ), 0);
  const simTracked = simLongs.some((r) => r.entry);

  const modeBadge = d.dryRun
    ? '<span class="badge badge-sim">🛡️ DRY-RUN · simuliert nur</span>'
    : '<span class="badge badge-live">⚡ LIVE · platziert Paper-Orders</span>';

  const marketBadge = (d.lastRun?.marketOpen
    ? '<span class="badge badge-open">● Aktien: Börse offen</span>'
    : '<span class="badge badge-closed">● Aktien: Börse zu</span>')
    + ' <span class="badge badge-open">● Krypto: 24/7</span>';

  const sign = (v) => (v == null ? "" : v >= 0 ? "pos" : "neg");
  const withSign = (v, fmt) => (v == null ? "—" : (v >= 0 ? "+" : "") + fmt(v));

  // KPI cards
  const kpis = `
    <div class="kpis">
      <div class="card">
        <div class="k-label">Depotwert</div>
        <div class="k-value">${esc(money(equity))}</div>
        <div class="k-sub">Cash: ${esc(money(acct?.cash))}</div>
      </div>
      <div class="card">
        <div class="k-label">Heute</div>
        <div class="k-value ${sign(dayPl)}">${esc(withSign(dayPl, money))}</div>
        <div class="k-sub ${sign(dayPlPct)}">${dayPlPct == null ? "—"
          : esc(withSign(dayPlPct, (v) => num(v) + " %"))}</div>
      </div>
      <div class="card">
        <div class="k-label">${d.dryRun ? "Positionen (simuliert)" : "Offene Positionen"}</div>
        <div class="k-value">${d.dryRun ? simLongs.length : d.positions.length}</div>
        <div class="k-sub ${d.dryRun ? (simTracked ? sign(simPl) : "") : sign(openPl)}">${
          d.dryRun
            ? (simLongs.length
                ? (simTracked ? esc(withSign(simPl, money)) + " auf dem Papier"
                              : "kein Einstiegskurs erfasst")
                : "keine")
            : (d.positions.length ? esc(withSign(openPl, money)) + " unrealisiert" : "keine")
        }</div>
      </div>
      <div class="card">
        <div class="k-label">Letzter Check</div>
        <div class="k-value small">${esc(agoText(d.lastRun?.time) || "—")}</div>
        <div class="k-sub">${esc(localTime(d.lastRun?.time))}</div>
      </div>
    </div>`;

  // Positions table
  const posRows = d.positions.length ? d.positions.map((p) => {
    const pl = Number(p.unrealized_pl);
    const plPct = Number(p.unrealized_plpc) * 100;
    return `<tr>
      <td class="sym">${esc(p.symbol)}</td>
      <td>${esc(num(p.qty, 4))}</td>
      <td>${esc(money(p.avg_entry_price))}</td>
      <td>${esc(money(p.current_price))}</td>
      <td>${esc(money(p.market_value))}</td>
      <td class="${sign(pl)}">${esc(withSign(pl, money))}</td>
      <td class="${sign(plPct)}">${esc(withSign(plPct, (v) => num(v) + " %"))}</td>
    </tr>`;
  }).join("") : `<tr><td colspan="7" class="empty">Aktuell keine offenen Positionen.</td></tr>`;

  // Signals table
  const sigRows = (d.lastRun?.rows || []).map((r) => {
    if (r.error) {
      return `<tr><td class="sym">${esc(r.symbol)}</td>
        <td colspan="6" class="err">⚠️ ${esc(r.error)}</td></tr>`;
    }
    const up = r.fast > r.slow;
    const trend = up
      ? '<span class="trend up">▲ Aufwärts</span>'
      : '<span class="trend down">▼ Abwärts</span>';
    const held = r.long
      ? `<span class="pill pill-in">im Markt${d.dryRun ? " (simuliert)" : ""}</span>`
      : '<span class="pill">nicht investiert</span>';
    let entryCell = "—";
    if (r.long) {
      if (r.entry) {
        const pct = ((r.price - r.entry) / r.entry) * 100;
        entryCell = `${esc(money(r.entry))}<br>`
          + `<span class="${sign(pct)}">${esc(withSign(pct, (v) => num(v) + " %"))}</span>`;
      } else {
        entryCell = '<span class="muted">nicht erfasst</span>';
      }
    }
    const tag = r.cls === "crypto" ? ' <span class="tag">Krypto</span>' : "";
    return `<tr>
      <td class="sym">${esc(r.symbol)}${tag}</td>
      <td>${esc(money(r.price))}</td>
      <td>${esc(num(r.fast))}</td>
      <td>${esc(num(r.slow))}</td>
      <td>${trend}</td>
      <td>${entryCell}</td>
      <td>${held} <span class="action">${esc(r.action)}</span></td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" class="empty">Noch kein Durchlauf.</td></tr>`;

  // Activity: bot events + broker orders
  const evRows = d.history.length ? d.history.map((h) => `
    <tr>
      <td class="mono">${esc(localTime(h.time))}</td>
      <td><span class="pill ${h.kind === "BUY" ? "pill-buy" : "pill-sell"}">${esc(h.kind)}</span></td>
      <td class="sym">${esc(h.symbol)}</td>
      <td>${esc(money(h.price))}</td>
      <td class="muted">${esc(h.note)}${h.pl != null
        ? ` · <span class="${sign(h.pl)}">${esc(withSign(h.pl, (v) => num(v) + " %"))}</span>`
        : ""}</td>
    </tr>`).join("")
    : `<tr><td colspan="5" class="empty">Noch keine Handelsentscheidung getroffen.</td></tr>`;

  const orderRows = d.orders.length ? d.orders.slice(0, 10).map((o) => `
    <tr>
      <td class="mono">${esc(localTime(o.submitted_at))}</td>
      <td><span class="pill ${o.side === "buy" ? "pill-buy" : "pill-sell"}">${esc(o.side?.toUpperCase())}</span></td>
      <td class="sym">${esc(o.symbol)}</td>
      <td>${esc(o.filled_qty && Number(o.filled_qty) ? num(o.filled_qty, 4) : (o.notional ? "$" + o.notional : "—"))}</td>
      <td>${esc(o.filled_avg_price ? money(o.filled_avg_price) : "—")}</td>
      <td class="muted">${esc(o.status)}</td>
    </tr>`).join("")
    : `<tr><td colspan="6" class="empty">Noch keine Orders beim Broker.</td></tr>`;

  const acctError = d.account?.error
    ? `<div class="warn">⚠️ Kein Zugriff auf das Alpaca-Konto: ${esc(d.account.error)}
       — prüfe ALPACA_API_KEY / ALPACA_API_SECRET in den Worker-Secrets.</div>` : "";

  return `<!doctype html>
<html lang="de"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trading Bot Dashboard</title>
<style>
  :root{
    --bg:#f5f6f8; --panel:#fff; --ink:#15181d; --muted:#6b7280; --line:#e5e7eb;
    --pos:#0f9d58; --neg:#d93025; --accent:#2563eb; --chip:#eef2ff;
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#0f1115; --panel:#171a21; --ink:#e8eaed; --muted:#9aa0a6;
           --line:#262a33; --chip:#1e2233; }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:24px 16px 64px}
  .wrap{max-width:1100px;margin:0 auto}
  header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-bottom:20px}
  h1{font-size:22px;margin:0;flex:1 1 auto}
  h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;
     color:var(--muted);margin:28px 0 10px}
  .badge{display:inline-block;padding:4px 10px;border-radius:999px;font-size:12.5px;font-weight:600}
  .badge-sim{background:#e7f5ec;color:#0f7a43}
  .badge-live{background:#fdeaea;color:#b3261e}
  .badge-open{background:#e8f0fe;color:#1a56db}
  .badge-closed{background:#eceff1;color:#5f6368}
  @media (prefers-color-scheme: dark){
    .badge-sim{background:#10321f;color:#6ee7a8}
    .badge-live{background:#3a1414;color:#ff9a94}
    .badge-open{background:#152346;color:#9dbbff}
    .badge-closed{background:#22262e;color:#9aa0a6}
  }
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
  .k-label{font-size:12.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
  .k-value{font-size:26px;font-weight:650;margin-top:4px}
  .k-value.small{font-size:19px}
  .k-sub{font-size:13px;color:var(--muted);margin-top:2px}
  .pos{color:var(--pos)} .neg{color:var(--neg)}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  .scroll{overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:14px;min-width:640px}
  th{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.04em;
     color:var(--muted);font-weight:600;padding:10px 14px;border-bottom:1px solid var(--line)}
  td{padding:11px 14px;border-bottom:1px solid var(--line)}
  tr:last-child td{border-bottom:none}
  .sym{font-weight:650}
  .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px;color:var(--muted)}
  .muted{color:var(--muted)}
  .empty{text-align:center;color:var(--muted);padding:22px}
  .err{color:var(--neg)}
  .trend.up{color:var(--pos);font-weight:600}
  .trend.down{color:var(--neg);font-weight:600}
  .pill{display:inline-block;padding:2px 9px;border-radius:999px;background:var(--chip);
        font-size:12px;font-weight:600;color:var(--muted)}
  .pill-in{background:#e8f0fe;color:#1a56db}
  .pill-buy{background:#e7f5ec;color:#0f7a43}
  .pill-sell{background:#fdeaea;color:#b3261e}
  .action{font-size:12.5px;color:var(--muted);margin-left:6px}
  .tag{display:inline-block;padding:1px 7px;border-radius:5px;background:var(--chip);
       font-size:10.5px;font-weight:600;color:var(--muted);vertical-align:middle;margin-left:5px}
  .warn{background:#fdeaea;color:#b3261e;padding:12px 14px;border-radius:10px;margin-bottom:16px}
  .note{background:var(--chip);color:var(--muted);padding:10px 14px;border-radius:10px;
        font-size:13px;margin-bottom:10px}
  .foot{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin-top:24px;
        font-size:13px;color:var(--muted)}
  .btn{display:inline-block;background:var(--accent);color:#fff;text-decoration:none;
       padding:8px 14px;border-radius:8px;font-weight:600;font-size:13.5px}
  .strategy{font-size:13px;color:var(--muted);margin-top:6px}
</style>
</head><body><div class="wrap">

<header>
  <h1>📈 Trading Bot</h1>
  ${modeBadge} ${marketBadge}
</header>

${acctError}
${kpis}

<h2>Aktuelle Signale</h2>
<div class="panel scroll"><table>
  <thead><tr><th>Wert</th><th>Kurs</th><th>Schnitt ${CONFIG.fast}</th>
    <th>Schnitt ${CONFIG.slow}</th><th>Trend</th><th>Einstieg / G&nbsp;V</th>
    <th>Status des Bots</th></tr></thead>
  <tbody>${sigRows}</tbody>
</table></div>
<div class="strategy">Regel: Kauf wenn Schnitt&nbsp;${CONFIG.fast} über Schnitt&nbsp;${CONFIG.slow}
  steigt · Verkauf bei Trendwechsel oder ${num(CONFIG.trailingStopPct, 1)}&nbsp;% Trailing-Stop ·
  ${money(CONFIG.tradeNotionalUsd)} pro Einstieg · höchstens
  ${CONFIG.maxOpenPositions} Positionen gleichzeitig ·
  beobachtet ${CONFIG.stocks.length} Aktien/ETFs und ${CONFIG.crypto.length} Kryptowerte</div>

<h2>Offene Positionen beim Broker</h2>
${d.dryRun ? `<div class="note">Im DRY-RUN wird <b>nichts wirklich gekauft</b>. Die Tabelle
  unten zeigt nur echte Positionen bei Alpaca — im Simulationsmodus bleibt sie leer.
  Was der Bot <i>täte</i>, steht oben unter „Einstieg / G&nbsp;V".</div>` : ""}
<div class="panel scroll"><table>
  <thead><tr><th>Wert</th><th>Stück</th><th>Einstieg</th><th>Kurs</th>
    <th>Wert</th><th>G/V</th><th>G/V %</th></tr></thead>
  <tbody>${posRows}</tbody>
</table></div>

<h2>Entscheidungen des Bots</h2>
<div class="panel scroll"><table>
  <thead><tr><th>Zeit</th><th>Aktion</th><th>Wert</th><th>Kurs</th><th>Grund</th></tr></thead>
  <tbody>${evRows}</tbody>
</table></div>

<h2>Orders beim Broker</h2>
<div class="panel scroll"><table>
  <thead><tr><th>Zeit</th><th>Seite</th><th>Wert</th><th>Menge</th>
    <th>Ausgeführt zu</th><th>Status</th></tr></thead>
  <tbody>${orderRows}</tbody>
</table></div>

<div class="foot">
  <a class="btn" href="/run">▶ Jetzt einmal prüfen</a>
  <span>Automatisch alle 5 Minuten · Seite aktualisiert sich alle 30 s</span>
  <a href="/api" class="muted">JSON</a>
  <a href="/reset?confirm=yes" class="muted"
     onclick="return confirm('Simulierte Positionen und Protokoll zurücksetzen? Echte Broker-Positionen bleiben unberührt.')"
     >Simulation zurücksetzen</a>
</div>

</div>
<script>setTimeout(() => location.reload(), 30000);</script>
</body></html>`;
}

// ── Entry points ───────────────────────────────────────────────────────────
export default {
  // Cloudflare fires this on the Cron schedule.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runTick(env));
  },

  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/run") {
      if (env.RUN_TOKEN && url.searchParams.get("key") !== env.RUN_TOKEN) {
        return new Response("forbidden", { status: 403 });
      }
      await runTick(env);
      // Back to the dashboard so the result is readable.
      return Response.redirect(new URL("/", request.url).toString(), 303);
    }

    if (url.pathname === "/api") {
      return Response.json(await collectDashboardData(env));
    }

    // Clears the bot's own bookkeeping only — it never touches broker positions.
    if (url.pathname === "/reset" && url.searchParams.get("confirm") === "yes") {
      await Promise.all([
        env.STATE.delete("positions"),
        env.STATE.delete("history"),
        env.STATE.delete("last_run"),
      ]);
      return Response.redirect(new URL("/", request.url).toString(), 303);
    }

    const data = await collectDashboardData(env);
    return new Response(renderDashboard(data), {
      headers: { "content-type": "text/html; charset=utf-8" },
    });
  },
};
