"""Typed data structures shared across the agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


@dataclass(frozen=True)
class Instrument:
    """A tradable pair, e.g. BTC_EUR (base=BTC, quote=EUR)."""

    code: str
    base: str
    quote: str

    @staticmethod
    def from_api(payload: dict) -> "Instrument":
        base = payload.get("base", {}).get("code") or payload.get("base_currency", "")
        quote = payload.get("quote", {}).get("code") or payload.get("quote_currency", "")
        code = payload.get("code") or f"{base}_{quote}"
        return Instrument(code=code, base=base, quote=quote)


@dataclass
class Balance:
    currency: str
    available: Decimal
    locked: Decimal = Decimal(0)

    @property
    def total(self) -> Decimal:
        return self.available + self.locked


@dataclass
class PriceLevel:
    price: Decimal
    amount: Decimal


@dataclass
class OrderBook:
    """Best-effort snapshot of an instrument's order book."""

    instrument: str
    bids: list[PriceLevel] = field(default_factory=list)  # buyers, high -> low
    asks: list[PriceLevel] = field(default_factory=list)  # sellers, low -> high

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> Decimal | None:
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2
        return None


@dataclass
class Signal:
    """A strategy's intent to trade. Not yet an order — the risk manager and
    executor decide whether and how it becomes one."""

    instrument: str
    side: Side
    amount: Decimal  # in base currency
    order_type: OrderType = OrderType.MARKET
    price: Decimal | None = None  # required for LIMIT
    reason: str = ""
    strategy: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class OrderResult:
    accepted: bool
    dry_run: bool
    signal: Signal
    order_id: str | None = None
    detail: str = ""
