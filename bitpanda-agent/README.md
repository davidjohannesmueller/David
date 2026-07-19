# Bitpanda Trading Agent

An automated trading agent for the **One Trading** exchange (formerly
**Bitpanda Pro**), which offers the full REST + WebSocket trading API needed
for order placement and arbitrage. The retail Bitpanda app API is read-only
for this purpose and is **not** used here.

> ⚠️ **Real money warning.** In live mode this software places real orders.
> It ships in **dry-run mode by default** (simulated orders only). Do not
> switch to live trading until you have read the code, tested thoroughly, and
> understand the risk. Nothing here is financial advice.

## Architecture

```
main.py                  CLI entry point (--once / continuous, --config)
src/
  config.py              loads .env (secrets) + YAML (trading params)
  client.py              async REST client (One Trading / Bitpanda Pro)
  models.py              typed Signal / Order / OrderBook / Balance
  risk.py                hard guardrails — checked before every order
  executor.py            dry-run-aware order execution
  agent.py               main loop: snapshot -> strategies -> execute
  strategies/
    base.py              Strategy interface + MarketSnapshot
    triangular_arbitrage.py   ✅ implemented (the arbitrage strategy)
    momentum.py               🟡 placeholder default (crypto strategy #2)
    mean_reversion.py         🟡 placeholder default (crypto strategy #3)
tests/test_arbitrage.py  offline tests (no network / no API key needed)
```

The three strategies map to what we discussed: one **arbitrage** strategy
(triangular arbitrage within the exchange) plus **two crypto strategies**.
The two crypto strategies currently contain sensible *placeholder* logic
(SMA crossover and z-score mean-reversion) so the pipeline runs end to end —
**replace their `evaluate()` bodies with your exact rules.**

## Setup

```bash
cd bitpanda-agent
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt

cp .env.example .env          # then add your API key
cp config.example.yaml config.yaml   # optional; tune params
```

### Getting an API key
Create an API key inside your One Trading / Bitpanda Pro account and put it in
`.env` as `ONETRADING_API_KEY`. Grant it only the scopes you need. `.env` is
git-ignored — **never commit it.**

## Running

```bash
python main.py --once      # single evaluation tick (great for testing)
python main.py             # run continuously on the poll interval
```

Dry-run vs live is controlled by `DRY_RUN` in `.env`:
- `DRY_RUN=true`  → simulate only, log intended orders (default)
- `DRY_RUN=false` → send **real** orders (requires a valid API key)

## Safety guardrails (`config.yaml` → `risk`)

Every signal must pass the risk manager before it can become an order:
- `max_order_notional_eur` — cap on a single order's size
- `max_total_exposure_eur` — cap on total deployed capital
- `max_daily_loss_eur` — halts all trading for the day when hit
- `allowed_instruments` — an allow-list; anything else is rejected

## Tests

```bash
python tests/test_arbitrage.py     # no API key / network needed
```

## Status & next steps

- [x] Project scaffold, config, REST client, risk manager, dry-run executor
- [x] Triangular arbitrage strategy (implemented + tested offline)
- [x] Momentum + mean-reversion **placeholders** (runnable, need your rules)
- [ ] Fill in the exact logic for the two crypto strategies
- [ ] Live WebSocket price feed (currently REST order-book polling)
- [ ] Chain arbitrage legs on real fills (currently bundled from expected fills)
- [ ] Validate order payloads against a real API key in dry-run first
