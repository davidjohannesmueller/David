"""Momentum strategy (PLACEHOLDER default — confirm your real logic).

Default implementation: fast/slow SMA crossover on the mid price.
  - fast SMA crosses ABOVE slow SMA  -> BUY
  - fast SMA crosses BELOW slow SMA  -> SELL (exit)

This is a reasonable, runnable starting point so the pipeline works end to
end. Replace the signal logic in `evaluate()` with the exact rules you have in
mind for your second (crypto) strategy.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from ..models import OrderType, Side, Signal
from .base import MarketSnapshot, Strategy

log = logging.getLogger("agent.strat.momentum")


class Momentum(Strategy):
    name = "momentum"

    def __init__(self, params: dict):
        super().__init__(params)
        self.instrument = params.get("instrument", "BTC_EUR")
        self.fast = int(params.get("fast_period", 12))
        self.slow = int(params.get("slow_period", 26))
        self.notional = Decimal(str(params.get("trade_notional_eur", 30)))
        self._last_state: str | None = None  # "long" or "flat"

    @property
    def instruments(self) -> list[str]:
        return [self.instrument]

    @staticmethod
    def _sma(prices: list[float], period: int) -> float | None:
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    async def evaluate(self, market: MarketSnapshot) -> list[Signal]:
        prices = market.price_history.get(self.instrument, [])
        fast = self._sma(prices, self.fast)
        slow = self._sma(prices, self.slow)
        if fast is None or slow is None:
            return []

        book = market.order_books.get(self.instrument)
        if book is None or book.mid is None:
            return []

        want_long = fast > slow
        signals: list[Signal] = []
        if want_long and self._last_state != "long":
            amount = (self.notional / book.mid).quantize(Decimal("0.00000001"))
            signals.append(Signal(
                instrument=self.instrument, side=Side.BUY, amount=amount,
                order_type=OrderType.MARKET,
                reason=f"SMA{self.fast}>{self.slow} cross up",
                strategy=self.name,
            ))
            self._last_state = "long"
        elif not want_long and self._last_state == "long":
            amount = (self.notional / book.mid).quantize(Decimal("0.00000001"))
            signals.append(Signal(
                instrument=self.instrument, side=Side.SELL, amount=amount,
                order_type=OrderType.MARKET,
                reason=f"SMA{self.fast}<{self.slow} cross down",
                strategy=self.name,
            ))
            self._last_state = "flat"
        return signals
