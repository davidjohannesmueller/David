# Multi-Asset Trading Agent

An automated trading agent that runs the **same strategy across stocks, crypto
and forex**. Each asset class is reached through a pluggable exchange adapter,
so adding or switching venues never touches the strategy code.

> ⚠️ **Real money warning.** In live mode this software places real orders.
> It ships in **dry-run mode by default** (simulated orders only) and the
> recommended venue is **paper trading**. Do not switch to live until you have
> read the code, tested thoroughly, and understand the risk. Not financial advice.

## Why these venues

| Asset class | Adapter | Notes |
|-------------|---------|-------|
| US stocks / ETFs | **Alpaca** | Free paper trading, best-documented. **Start here.** |
| Crypto | **Alpaca** (or **Bitpanda/One Trading** for EU live) | Alpaca paper works EU-wide. Bitpanda = EU crypto live. |
| Forex | **OANDA** | Alpaca has no forex. Free practice account. |

Recommendation (matches earlier planning): **develop on Alpaca paper trading
with one trend-following strategy**, prove the mechanics with zero real risk,
then turn on more asset classes and, later, live trading in the EU via Bitpanda.

## Architecture

```
main.py                       CLI entry (--once / continuous, --config)
src/
  config.py                   .env (secrets) + YAML (venues, strategies, risk)
  models.py                   typed Signal / Order / OrderBook / Balance
  risk.py                     hard guardrails — checked before every order
  executor.py                 dry-run-aware; routes orders to the owning venue
  agent.py                    main loop: snapshot -> strategies -> execute
  client.py                   low-level One Trading REST client
  exchanges/                  ← the pluggable venue layer
    base.py                   Exchange interface (implement this to add a venue)
    alpaca.py                 stocks + crypto
    bitpanda.py               EU crypto (One Trading) — wraps client.py
    oanda.py                  forex
    mock.py                   in-memory venue for offline tests
  strategies/
    base.py                   Strategy interface + MarketSnapshot
    trend_following.py        ✅ primary strategy (asset-agnostic, trailing stop)
    triangular_arbitrage.py   optional (single-venue arb)
    momentum.py / mean_reversion.py   optional extras
tests/                        offline tests (no keys / no network)
```

The agent builds one router: **instrument → exchange**. When a strategy asks to
trade `AAPL` it goes to Alpaca; `EUR_USD` goes to OANDA; `BTC_EUR` to Bitpanda —
automatically. One trend-following strategy therefore trades all three at once.

## Setup

```bash
cd bitpanda-agent
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt

cp .env.example .env                  # add your paper-trading keys
cp config.example.yaml config.yaml    # choose venues, instruments, params
```

Get free paper keys: **Alpaca** (https://alpaca.markets/, Paper account) and,
for forex, **OANDA** (https://www.oanda.com/, fxTrade Practice). `.env` is
git-ignored — never commit it.

## Running

```bash
python main.py --once      # single evaluation tick (great for testing)
python main.py             # run continuously on the poll interval
```

`DRY_RUN=true` (default) simulates and logs intended orders. `DRY_RUN=false`
sends real orders to whatever venue owns each instrument — with Alpaca/OANDA
pointed at their **paper** endpoints, that is still risk-free.

## Safety guardrails (`config.yaml` → `risk`)

Every signal must pass the risk manager before it becomes an order:
`max_order_notional_eur`, `max_total_exposure_eur`, `max_daily_loss_eur`
(halts the day when hit), plus an instrument allow-list.

## Tests

```bash
python tests/test_trend_following.py   # full engine via a mock venue
python tests/test_arbitrage.py         # arbitrage detection + risk checks
```

## Status & next steps

- [x] Pluggable exchange layer + instrument routing (stocks / crypto / forex)
- [x] Alpaca adapter (stocks + crypto), Bitpanda adapter, OANDA adapter
- [x] Trend-following strategy (asset-agnostic, trailing stop) — engine-tested
- [x] Dry-run-by-default executor; risk manager guardrails
- [ ] Validate Alpaca/OANDA adapters against real paper keys (live smoke test)
- [ ] Market-hours awareness per asset class (stocks closed nights/weekends)
- [ ] WebSocket price feeds (currently REST quote polling)
- [ ] Add your second strategy once trend-following is proven in paper
