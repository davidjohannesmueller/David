# Deploy the trading bot on Cloudflare Workers (browser only)

No terminal, no computer setup needed — everything below happens in the
Cloudflare dashboard. The bot runs in **paper trading** (no real money) and
starts in **DRY-RUN** (it only *simulates* orders until you flip a switch).

## 1. Create the Worker
1. In the left sidebar open **Compute** → **Workers & Pages**.
2. Click **Create** → **Create Worker**.
3. Give it a name, e.g. `trading-bot` → **Deploy** (this makes a Hello-World).

## 2. Paste the bot code
1. On the Worker page click **Edit code** (top right).
2. Delete everything in the editor and paste the full contents of `worker.js`.
3. Click **Deploy**.

## 3. Add the storage (KV namespace)
1. Left sidebar **Storage & databases** → **KV** → **Create a namespace**.
2. Name it `trading-state` → Create.
3. Back on your Worker: **Settings** → **Bindings** → **Add** → **KV namespace**.
   - Variable name: `STATE`  (exactly this)
   - KV namespace: `trading-state`
   - Save.

## 4. Add your keys (Secrets)
On your Worker: **Settings** → **Variables and Secrets** → **Add**:
| Name | Type | Value |
|------|------|-------|
| `ALPACA_API_KEY` | Secret | your Alpaca paper key id (`PK…`) |
| `ALPACA_API_SECRET` | Secret | your Alpaca paper secret |
| `DRY_RUN` | Text | `true` |

Deploy/Save after adding them.

## 5. Set the schedule (Cron Trigger)
On your Worker: **Settings** → **Triggers** → **Cron Triggers** → **Add**:
- Cron expression: `*/5 * * * *`  (every 5 minutes — safe for the free tier)

## 6. Test it
- Open your Worker's URL (shown on the Worker page) → you see a **status page**.
- Click **“Run one tick now”** (or add `/run` to the URL). It fetches live prices,
  computes the moving averages, and logs what it *would* do — still simulated,
  because `DRY_RUN=true`.
- Watch live logs: Worker → **Logs** (or **Observability**).

## 7. Go live on paper (optional, when you're confident)
Change the `DRY_RUN` variable from `true` to `false` and Deploy. Now the bot
places **paper** orders on Alpaca (still no real money). You can watch them on
the Alpaca paper dashboard under **Orders / Positions**.

---

### Notes
- **Free tier:** every-5-minutes is well within Cloudflare's free limits.
- **Market hours:** stocks only trade during US hours. Off-hours the bot logs
  the signal and waits — it does not place stock orders when the market is closed.
- **Change strategy/instruments:** edit the `CONFIG` block at the top of `worker.js`.
- **Safety:** to pause the bot, delete the Cron Trigger (or set `DRY_RUN=true`).
