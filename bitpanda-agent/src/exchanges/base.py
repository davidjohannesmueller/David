"""Exchange abstraction. Every broker (Alpaca, Bitpanda, OANDA, ...) implements
this same interface, so strategies and the agent never care which venue an
instrument lives on."""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from ..models import Balance, OrderBook, OrderType, Side


class Exchange(ABC):
    #: human-readable name, e.g. "alpaca"
    name: str = "exchange"
    #: "stocks" | "crypto" | "forex"
    asset_class: str = "unknown"

    def __init__(self, instruments: list[str]):
        self._instruments = list(instruments)

    @property
    def instruments(self) -> list[str]:
        """Instruments this venue is configured to trade."""
        return self._instruments

    def handles(self, instrument: str) -> bool:
        return instrument in self._instruments

    # ── market data ─────────────────────────────────────────────────────
    @abstractmethod
    async def get_order_book(self, instrument: str) -> OrderBook:
        ...

    # ── account / trading ───────────────────────────────────────────────
    @abstractmethod
    async def get_balances(self) -> list[Balance]:
        ...

    @abstractmethod
    async def create_order(
        self,
        instrument: str,
        side: Side,
        amount: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
    ) -> dict:
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None:
        ...

    async def close(self) -> None:
        """Release any network resources. Override if needed."""
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
