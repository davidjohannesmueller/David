// ─────────────────────────────────────────────────────────────────────────
// Alpaca Trend-Following Trading Bot — Cloudflare Worker (paper trading)
//
// Single self-contained file. Paste it into the Cloudflare dashboard editor
// (Workers → your worker → Edit code) and click Deploy.
//
// REQUIRED — set in the dashboard (Settings → Variables and Secrets):
//   ALPACA_API_KEY     (Secret)  your Alpaca PAPER key id, starts with "PK"
//   ALPACA_API_SECRET  (Secret)  your Alpaca PAPER secret
//   DRY_RUN            (Text)    "true" = simulate only (default). "false" = place paper orders.
//
// REQUIRED — a KV namespace bound as STATE (Settings → Bindings → KV namespace).
//
// REQUIRED — a Cron Trigger, recommended "*/5 * * * *" (every 5 minutes).
// ─────────────────────────────────────────────────────────────────────────

const CONFIG = {
  // Stocks to trade (start simple; crypto/forex can be added later).
  instruments: ["AAPL", "MSFT", "SPY"],
  timeframe: "1Hour",          // bar size used for the moving averages
  bars: 60,                    // how many recent bars to keep
  lookbackDays: 45,            // how far back to ask Alpaca for bars
  fast: 10,                    // fast moving-average length
  slow: 30,                    // slow moving-average length
  trailingStopPct: 5.0,        // exit if price drops this % below its post-entry high
  tradeNotionalUsd: 1000,      // $ per entry
  maxOrderNotionalUsd: 2000,   // hard risk cap per order
  dataUrl: "https://data.alpaca.markets",
  tradingUrl: "https://paper-api.alpaca.markets",
};

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
  const slice = values.slice(-n);
  return slice.reduce((a, b) => a + b, 0) / n;
}

// ── Alpaca calls ───────────────────────────────────────────────────────────
async function getCloses(env, symbol) {
  // Without an explicit start, Alpaca only returns today's bars — far too few
  // for a 30-period average. Look back far enough to cover the slow window.
  const start = new Date(Date.now() - CONFIG.lookbackDays * 86400_000)
    .toISOString().slice(0, 10);
  const url = `${CONFIG.dataUrl}/v2/stocks/${encodeURIComponent(symbol)}/bars`
    + `?timeframe=${CONFIG.timeframe}&start=${start}&limit=1000`
    + `&adjustment=raw&sort=asc&feed=iex`;
  const r = await fetch(url, { headers: authHeaders(env) });
  if (!r.ok) throw new Error(`bars ${symbol}: ${r.status} ${await r.text()}`);
  const j = await r.json();
  // Oldest → newest; keep only the most recent bars we actually need.
  return (j.bars || []).map((b) => b.c).slice(-CONFIG.bars);
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

async function enterLong(env, symbol) {
  if (CONFIG.tradeNotionalUsd > CONFIG.maxOrderNotionalUsd) {
    throw new Error(`notional ${CONFIG.tradeNotionalUsd} exceeds risk cap`);
  }
  if (isDryRun(env)) return "[DRY-RUN] would BUY";
  const body = {
    symbol, notional: String(CONFIG.tradeNotionalUsd),
    side: "buy", type: "market", time_in_force: "day",
  };
  const r = await fetch(`${CONFIG.tradingUrl}/v2/orders`, {
    method: "POST",
    headers: { ...authHeaders(env), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`buy ${symbol}: ${r.status} ${await r.text()}`);
  return "BUY placed";
}

async function closePosition(env, symbol) {
  if (isDryRun(env)) return "[DRY-RUN] would CLOSE";
  const r = await fetch(`${CONFIG.tradingUrl}/v2/positions/${encodeURIComponent(symbol)}`, {
    method: "DELETE", headers: authHeaders(env),
  });
  if (!r.ok && r.status !== 404) throw new Error(`close ${symbol}: ${r.status} ${await r.text()}`);
  return "CLOSE placed";
}

// ── State (Workers KV) ─────────────────────────────────────────────────────
async function loadState(env) {
  const raw = await env.STATE.get("positions");
  return raw ? JSON.parse(raw) : {};
}

// ── One evaluation tick ────────────────────────────────────────────────────
async function runTick(env) {
  const dryRun = isDryRun(env);
  const open = await marketOpen(env);
  const state = await loadState(env);
  const report = [];

  for (const symbol of CONFIG.instruments) {
    try {
      const closes = await getCloses(env, symbol);
      const price = closes[closes.length - 1];
      const fast = sma(closes, CONFIG.fast);
      const slow = sma(closes, CONFIG.slow);
      if (price == null || fast == null || slow == null) {
        report.push(`${symbol}: not enough data yet `
          + `(${closes.length} bars, need ${CONFIG.slow})`);
        continue;
      }

      const pos = state[symbol] || { long: false, high: 0 };
      let action = "hold";

      if (!pos.long) {
        if (fast > slow) {
          if (open) {
            const res = await enterLong(env, symbol);
            pos.long = true; pos.high = price; action = `BUY (${res})`;
          } else {
            action = "BUY signal — market closed, waiting";
          }
        }
      } else {
        pos.high = Math.max(pos.high, price);
        const drawdown = (pos.high - price) / pos.high;
        const crossDown = fast < slow;
        const stopHit = drawdown >= CONFIG.trailingStopPct / 100;
        if (crossDown || stopHit) {
          if (open) {
            const res = await closePosition(env, symbol);
            pos.long = false;
            action = `${crossDown ? "SELL cross-down" : "SELL trailing-stop"} (${res})`;
          } else {
            action = "SELL signal — market closed, waiting";
          }
        }
      }

      state[symbol] = pos;
      report.push(
        `${symbol}: px=${price.toFixed(2)} fast=${fast.toFixed(2)} `
        + `slow=${slow.toFixed(2)} long=${pos.long} → ${action}`);
    } catch (e) {
      report.push(`${symbol}: ERROR ${e.message}`);
    }
  }

  await env.STATE.put("positions", JSON.stringify(state));
  const summary = {
    time: new Date().toISOString(),
    mode: dryRun ? "DRY-RUN (simulated)" : "LIVE paper orders",
    marketOpen: open,
    report,
  };
  await env.STATE.put("last_run", JSON.stringify(summary));
  console.log(JSON.stringify(summary));
  return summary;
}

// ── Entry points ───────────────────────────────────────────────────────────
export default {
  // Cloudflare fires this on the Cron schedule.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runTick(env));
  },

  // Visiting the Worker URL shows a status page; /run triggers a tick now.
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/run") {
      // Optional guard: if RUN_TOKEN is set, require ?key=<token>.
      if (env.RUN_TOKEN && url.searchParams.get("key") !== env.RUN_TOKEN) {
        return new Response("forbidden", { status: 403 });
      }
      const summary = await runTick(env);
      return Response.json(summary);
    }

    const last = await env.STATE.get("last_run");
    const parsed = last ? JSON.parse(last) : null;
    const rows = parsed
      ? parsed.report.map((r) => `<li>${r}</li>`).join("")
      : "<li>No run yet — trigger one at <code>/run</code> or wait for the schedule.</li>";
    const html = `<!doctype html><meta charset="utf-8">
      <title>Trading Bot Status</title>
      <style>body{font-family:system-ui;max-width:680px;margin:40px auto;padding:0 16px;color:#222}
      h1{font-size:20px}code{background:#f2f2f2;padding:1px 5px;border-radius:4px}
      .mode{display:inline-block;padding:2px 8px;border-radius:6px;background:#eef;font-size:13px}
      li{margin:6px 0;font-family:ui-monospace,monospace;font-size:13px}</style>
      <h1>📈 Alpaca Trend-Following Bot</h1>
      <p>Last run: <b>${parsed ? parsed.time : "—"}</b><br>
      Mode: <span class="mode">${parsed ? parsed.mode : "unknown"}</span> ·
      Market open: <b>${parsed ? parsed.marketOpen : "—"}</b></p>
      <ul>${rows}</ul>
      <p><a href="/run">▶ Run one tick now</a></p>`;
    return new Response(html, { headers: { "content-type": "text/html; charset=utf-8" } });
  },
};
