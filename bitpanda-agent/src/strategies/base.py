"""Strategy interface and the market snapshot passed to each strategy."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import OrderBook, Signal


@dataclass
class MarketSnapshot:
    """Everything a strategy needs for one evaluation tick."""

    order_books: dict[str, OrderBook] = field(default_factory=dict)
    # Rolling recent mid-prices per instrument, oldest -> newest.
    price_history: dict[str, list[float]] = field(default_factory=dict)


class Strategy(ABC):
    name: str = "strategy"

    def __init__(self, params: dict):
        self.params = params
        self.enabled = bool(params.get("enabled", False))

    @property
    def instruments(self) -> list[str]:
        """Instruments this strategy needs order books for."""
        return []

    @abstractmethod
    async def evaluate(self, market: MarketSnapshot) -> list[Signal]:
        """Return zero or more Signals for the current market state."""
        raise NotImplementedError
