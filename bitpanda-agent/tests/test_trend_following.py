"""Offline end-to-end test of the multi-asset engine using MockExchange.

No network, no API keys. Proves: exchange routing, price-history build-up,
trend-following entry + exit, and order execution through the executor.

Run:  python tests/test_trend_following.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import TradingAgent
from src.config import AppConfig, RiskConfig
from src.exchanges.mock import MockExchange


def _rise_then_fall() -> list[float]:
    up = [100 + i * 1.5 for i in range(30)]      # 100 -> ~143 (uptrend)
    down = [up[-1] - i * 1.5 for i in range(15)]  # fall ~20 (triggers exit)
    return up + down


def _make_agent(exchanges, instruments) -> TradingAgent:
    cfg = AppConfig(
        dry_run=False,            # route to the (safe) mock exchange
        poll_interval_seconds=0,
        exchanges=[],
        strategies={"trend_following": {
            "enabled": True,
            "instruments": instruments,
            "fast_period": 5,
            "slow_period": 10,
            "trailing_stop_pct": 3.0,
            "trade_notional": 1000,
        }},
        risk=RiskConfig(max_order_notional_eur=100000,
                        max_total_exposure_eur=1_000_000,
                        max_daily_loss_eur=1_000_000),
        allowed_instruments=instruments,
    )
    return TradingAgent(cfg, exchanges)


def test_trend_entry_and_exit():
    mock = MockExchange({"AAPL": _rise_then_fall()}, asset_class="stocks")
    agent = _make_agent([mock], ["AAPL"])

    async def run():
        for _ in range(45):
            await agent.tick()

    asyncio.run(run())
    sides = [o["side"] for o in mock.orders]
    assert "BUY" in sides, f"expected an entry, got {sides}"
    assert "SELL" in sides, f"expected an exit, got {sides}"
    assert sides.index("BUY") < sides.index("SELL"), "BUY must precede SELL"
    print(f"  ✓ trend entry+exit executed: {sides}")


def test_multi_asset_routing():
    stocks = MockExchange({"AAPL": _rise_then_fall()}, asset_class="stocks")
    crypto = MockExchange({"BTC/USD": _rise_then_fall()}, asset_class="crypto")
    agent = _make_agent([stocks, crypto], ["AAPL", "BTC/USD"])

    # Routing sends each instrument to the correct venue.
    assert agent.router["AAPL"].asset_class == "stocks"
    assert agent.router["BTC/USD"].asset_class == "crypto"

    async def run():
        for _ in range(45):
            await agent.tick()

    asyncio.run(run())
    assert all(o["instrument"] == "AAPL" for o in stocks.orders)
    assert all(o["instrument"] == "BTC/USD" for o in crypto.orders)
    assert stocks.orders and crypto.orders
    print(f"  ✓ routed {len(stocks.orders)} stock + {len(crypto.orders)} crypto orders")


if __name__ == "__main__":
    for fn in [test_trend_entry_and_exit, test_multi_asset_routing]:
        print(f"• {fn.__name__}")
        fn()
    print("\nAll checks passed.")
