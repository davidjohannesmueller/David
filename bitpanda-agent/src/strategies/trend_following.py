"""Trend-following strategy — the recommended first strategy.

Asset-agnostic: it only reads prices, so the same logic runs on stocks, crypto
or forex. Rules per instrument:
  - ENTER long when fast SMA crosses ABOVE slow SMA (uptrend confirmed).
  - Track the highest price seen while in the position.
  - EXIT when either the fast SMA crosses back BELOW the slow SMA, OR price
    falls more than `trailing_stop_pct` below the tracked high (protect gains).

Sizing is by notional (`trade_notional` in the quote currency) divided by price.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from ..models import OrderType, Side, Signal
from .base import MarketSnapshot, Strategy

log = logging.getLogger("agent.strat.trend")


class TrendFollowing(Strategy):
    name = "trend_following"

    def __init__(self, params: dict):
        super().__init__(params)
        self._instruments = list(params.get("instruments", []))
        self.fast = int(params.get("fast_period", 20))
        self.slow = int(params.get("slow_period", 50))
        self.trailing_stop = float(params.get("trailing_stop_pct", 3.0)) / 100
        self.notional = Decimal(str(params.get("trade_notional", 1000)))
        # Per-instrument position state.
        self._long: dict[str, bool] = {}
        self._high: dict[str, float] = {}

    @property
    def instruments(self) -> list[str]:
        return self._instruments

    @staticmethod
    def _sma(prices: list[float], period: int) -> float | None:
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    async def evaluate(self, market: MarketSnapshot) -> list[Signal]:
        signals: list[Signal] = []
        for instrument in self._instruments:
            sig = self._eval_one(instrument, market)
            if sig is not None:
                signals.append(sig)
        return signals

    def _eval_one(self, instrument: str, market: MarketSnapshot) -> Signal | None:
        prices = market.price_history.get(instrument, [])
        fast = self._sma(prices, self.fast)
        slow = self._sma(prices, self.slow)
        book = market.order_books.get(instrument)
        if fast is None or slow is None or book is None or book.mid is None:
            return None

        price = float(book.mid)
        in_long = self._long.get(instrument, False)
        amount = (self.notional / book.mid).quantize(Decimal("0.00000001"))

        if not in_long:
            if fast > slow:  # uptrend confirmed -> enter
                self._long[instrument] = True
                self._high[instrument] = price
                return Signal(
                    instrument=instrument, side=Side.BUY, amount=amount,
                    order_type=OrderType.MARKET,
                    reason=f"trend entry SMA{self.fast}>{self.slow}",
                    strategy=self.name,
                )
            return None

        # In a position: update trailing high, check exits.
        self._high[instrument] = max(self._high.get(instrument, price), price)
        drawdown = (self._high[instrument] - price) / self._high[instrument]
        cross_down = fast < slow
        stop_hit = drawdown >= self.trailing_stop
        if cross_down or stop_hit:
            self._long[instrument] = False
            reason = "trend exit (SMA cross down)" if cross_down else \
                     f"trailing stop {self.trailing_stop*100:.1f}%"
            return Signal(
                instrument=instrument, side=Side.SELL, amount=amount,
                order_type=OrderType.MARKET, reason=reason, strategy=self.name,
            )
        return None
