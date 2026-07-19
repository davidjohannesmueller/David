"""Mean-reversion strategy (PLACEHOLDER default — confirm your real logic).

Default implementation: z-score of the mid price vs a rolling mean.
  - price falls to  <= -entry_z  standard deviations -> BUY  (expect bounce up)
  - price returns toward the mean (|z| <= exit_z)      -> SELL (close long)

Runnable starting point so the pipeline works end to end. Replace the signal
logic in `evaluate()` with the exact rules for your third (crypto) strategy.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from statistics import mean, pstdev

from ..models import OrderType, Side, Signal
from .base import MarketSnapshot, Strategy

log = logging.getLogger("agent.strat.meanrev")


class MeanReversion(Strategy):
    name = "mean_reversion"

    def __init__(self, params: dict):
        super().__init__(params)
        self.instrument = params.get("instrument", "ETH_EUR")
        self.lookback = int(params.get("lookback", 50))
        self.entry_z = float(params.get("entry_z", 2.0))
        self.exit_z = float(params.get("exit_z", 0.5))
        self.notional = Decimal(str(params.get("trade_notional_eur", 30)))
        self._in_position = False

    @property
    def instruments(self) -> list[str]:
        return [self.instrument]

    async def evaluate(self, market: MarketSnapshot) -> list[Signal]:
        prices = market.price_history.get(self.instrument, [])
        if len(prices) < self.lookback:
            return []
        window = prices[-self.lookback:]
        mu = mean(window)
        sigma = pstdev(window)
        if sigma == 0:
            return []
        z = (prices[-1] - mu) / sigma

        book = market.order_books.get(self.instrument)
        if book is None or book.mid is None:
            return []
        amount = (self.notional / book.mid).quantize(Decimal("0.00000001"))

        signals: list[Signal] = []
        if not self._in_position and z <= -self.entry_z:
            signals.append(Signal(
                instrument=self.instrument, side=Side.BUY, amount=amount,
                order_type=OrderType.MARKET,
                reason=f"mean-reversion entry z={z:.2f}",
                strategy=self.name,
            ))
            self._in_position = True
        elif self._in_position and abs(z) <= self.exit_z:
            signals.append(Signal(
                instrument=self.instrument, side=Side.SELL, amount=amount,
                order_type=OrderType.MARKET,
                reason=f"mean-reversion exit z={z:.2f}",
                strategy=self.name,
            ))
            self._in_position = False
        return signals
