"""Bitpanda / One Trading adapter — wraps the existing REST client so it plugs
into the common Exchange interface. Kept available for EU crypto live trading."""
from __future__ import annotations

import os
from decimal import Decimal

from ..client import OneTradingClient
from ..models import Balance, OrderBook, OrderType, Side
from .base import Exchange


class BitpandaExchange(Exchange):
    name = "bitpanda"
    asset_class = "crypto"

    def __init__(self, instruments: list[str]):
        super().__init__(instruments)
        self._client = OneTradingClient(
            rest_url=os.getenv(
                "ONETRADING_REST_URL", "https://api.exchange.bitpanda.com/public/v1"
            ),
            api_key=os.getenv("ONETRADING_API_KEY", ""),
        )

    async def close(self) -> None:
        await self._client.close()

    async def get_order_book(self, instrument: str) -> OrderBook:
        return await self._client.get_order_book(instrument)

    async def get_balances(self) -> list[Balance]:
        return await self._client.get_balances()

    async def create_order(self, instrument: str, side: Side, amount: Decimal,
                           order_type: OrderType = OrderType.MARKET,
                           price: Decimal | None = None) -> dict:
        return await self._client.create_order(instrument, side, amount, order_type, price)

    async def cancel_order(self, order_id: str) -> None:
        await self._client.cancel_order(order_id)
