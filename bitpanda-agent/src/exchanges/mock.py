"""In-memory mock exchange for offline tests — no network, no API keys.

You feed it a price series per instrument; get_order_book() walks through it on
each call and returns a tight book around the current price. Orders are recorded
so tests can assert on them."""
from __future__ import annotations

from decimal import Decimal

from ..models import Balance, OrderBook, OrderType, PriceLevel, Side
from .base import Exchange


class MockExchange(Exchange):
    name = "mock"

    def __init__(self, prices: dict[str, list[float]], asset_class: str = "stocks",
                 spread: float = 0.001):
        super().__init__(list(prices.keys()))
        self.asset_class = asset_class
        self._prices = {k: list(v) for k, v in prices.items()}
        self._idx = {k: 0 for k in prices}
        self._spread = spread
        self.orders: list[dict] = []

    async def get_order_book(self, instrument: str) -> OrderBook:
        series = self._prices.get(instrument, [])
        if not series:
            return OrderBook(instrument=instrument)
        i = min(self._idx[instrument], len(series) - 1)
        self._idx[instrument] = i + 1
        mid = Decimal(str(series[i]))
        half = mid * Decimal(str(self._spread)) / 2
        return OrderBook(
            instrument=instrument,
            bids=[PriceLevel(mid - half, Decimal("100"))],
            asks=[PriceLevel(mid + half, Decimal("100"))],
        )

    async def get_balances(self) -> list[Balance]:
        return [Balance(currency="USD", available=Decimal("100000"))]

    async def create_order(self, instrument: str, side: Side, amount: Decimal,
                           order_type: OrderType = OrderType.MARKET,
                           price: Decimal | None = None) -> dict:
        rec = {"instrument": instrument, "side": side.value, "amount": str(amount),
               "type": order_type.value, "id": f"mock-{len(self.orders)}"}
        self.orders.append(rec)
        return {"order_id": rec["id"], **rec}

    async def cancel_order(self, order_id: str) -> None:
        return None
