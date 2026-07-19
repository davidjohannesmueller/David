"""Offline tests for the arbitrage strategy and the dry-run executor.

Run:  python -m pytest tests/         (if pytest installed)
  or: python tests/test_arbitrage.py  (plain, no dependencies)
"""
from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import RiskConfig
from src.executor import OrderExecutor
from src.models import OrderBook, PriceLevel
from src.risk import RiskManager
from src.strategies.base import MarketSnapshot
from src.strategies.triangular_arbitrage import TriangularArbitrage


def _book(instr: str, bid: str, ask: str) -> OrderBook:
    return OrderBook(
        instrument=instr,
        bids=[PriceLevel(Decimal(bid), Decimal("10"))],
        asks=[PriceLevel(Decimal(ask), Decimal("10"))],
    )


def _market_with_arb() -> MarketSnapshot:
    # Construct prices with a deliberate cross-rate mispricing.
    # EUR -> BTC (buy@60000) -> ETH (buy 1 ETH per 0.04 BTC) -> sell ETH@2600 EUR.
    return MarketSnapshot(order_books={
        "BTC_EUR": _book("BTC_EUR", bid="59990", ask="60000"),
        "ETH_BTC": _book("ETH_BTC", bid="0.0398", ask="0.0400"),
        "ETH_EUR": _book("ETH_EUR", bid="2600", ask="2601"),
    })


def _market_no_arb() -> MarketSnapshot:
    return MarketSnapshot(order_books={
        "BTC_EUR": _book("BTC_EUR", bid="59990", ask="60000"),
        "ETH_BTC": _book("ETH_BTC", bid="0.0433", ask="0.0434"),
        "ETH_EUR": _book("ETH_EUR", bid="2600", ask="2601"),
    })


def test_arb_detected():
    strat = TriangularArbitrage({
        "enabled": True,
        "cycle": ["BTC_EUR", "ETH_BTC", "ETH_EUR"],
        "start_currency": "EUR",
        "min_profit_pct": 0.3,
        "taker_fee_pct": 0.15,
        "trade_notional_eur": 30,
    })
    signals = asyncio.run(strat.evaluate(_market_with_arb()))
    assert len(signals) == 3, f"expected 3 legs, got {len(signals)}"
    assert signals[0].strategy == "triangular_arbitrage"
    print(f"  ✓ arb detected, {len(signals)} legs:")
    for s in signals:
        print(f"      {s.side.value:4} {s.amount} {s.instrument}  ({s.reason})")


def test_no_false_positive():
    strat = TriangularArbitrage({
        "enabled": True,
        "cycle": ["BTC_EUR", "ETH_BTC", "ETH_EUR"],
        "start_currency": "EUR",
        "min_profit_pct": 0.3,
        "taker_fee_pct": 0.15,
        "trade_notional_eur": 30,
    })
    signals = asyncio.run(strat.evaluate(_market_no_arb()))
    assert signals == [], f"expected no arb, got {len(signals)} signals"
    print("  ✓ no false positive on balanced market")


def test_dry_run_executor_and_risk():
    risk = RiskManager(RiskConfig(max_order_notional_eur=50,
                                  max_total_exposure_eur=200),
                       allowed_instruments=["BTC_EUR", "ETH_BTC", "ETH_EUR"])
    execu = OrderExecutor(resolve_exchange=lambda _i: None, risk=risk, dry_run=True)
    market = _market_with_arb()
    strat = TriangularArbitrage({
        "enabled": True, "cycle": ["BTC_EUR", "ETH_BTC", "ETH_EUR"],
        "start_currency": "EUR", "min_profit_pct": 0.3,
        "taker_fee_pct": 0.15, "trade_notional_eur": 30,
    })
    signals = asyncio.run(strat.evaluate(market))

    async def run():
        return [await execu.execute(s, market.order_books.get(s.instrument))
                for s in signals]

    results = asyncio.run(run())
    assert all(r.accepted and r.dry_run for r in results)
    print(f"  ✓ dry-run executor accepted {len(results)} simulated orders")


def test_risk_rejects_disallowed_instrument():
    risk = RiskManager(RiskConfig(), allowed_instruments=["BTC_EUR"])
    from src.models import Side, Signal
    sig = Signal(instrument="DOGE_EUR", side=Side.BUY, amount=Decimal("1"))
    ok, reason = risk.check(sig, _book("DOGE_EUR", "0.1", "0.1"))
    assert not ok and "allow-list" in reason
    print(f"  ✓ risk rejects disallowed instrument ({reason})")


if __name__ == "__main__":
    for fn in [test_arb_detected, test_no_false_positive,
               test_dry_run_executor_and_risk,
               test_risk_rejects_disallowed_instrument]:
        print(f"• {fn.__name__}")
        fn()
    print("\nAll checks passed.")
