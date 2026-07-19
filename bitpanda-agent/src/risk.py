"""Risk manager — the last line of defence before any order is sent.

Every signal must pass through `check()`. Anything that violates a limit is
rejected with a reason, regardless of what the strategy wanted."""
from __future__ import annotations

import logging
from decimal import Decimal

from .config import RiskConfig
from .models import OrderBook, Signal

log = logging.getLogger("agent.risk")


class RiskManager:
    def __init__(self, cfg: RiskConfig, allowed_instruments: list[str]):
        self.cfg = cfg
        self.allowed = set(allowed_instruments)
        self.realised_pnl_eur = Decimal(0)
        self.open_exposure_eur = Decimal(0)
        self._halted = False

    def halted(self) -> bool:
        return self._halted

    def register_fill(self, notional_eur: Decimal, pnl_eur: Decimal = Decimal(0)) -> None:
        """Update running exposure / PnL after an order executes."""
        self.open_exposure_eur += notional_eur
        self.realised_pnl_eur += pnl_eur
        if self.realised_pnl_eur <= -Decimal(str(self.cfg.max_daily_loss_eur)):
            self._halted = True
            log.error(
                "Daily loss limit hit (%.2f EUR). Trading halted.",
                self.realised_pnl_eur,
            )

    def check(self, signal: Signal, book: OrderBook | None) -> tuple[bool, str]:
        """Return (allowed, reason)."""
        if self._halted:
            return False, "trading halted (daily loss limit)"

        if signal.instrument not in self.allowed:
            return False, f"instrument {signal.instrument} not in allow-list"

        if signal.amount <= 0:
            return False, "non-positive amount"

        # Estimate notional in quote currency from the order book.
        ref_price = signal.price
        if ref_price is None and book is not None:
            ref_price = book.best_ask if signal.side.value == "BUY" else book.best_bid
        if ref_price is None:
            return False, "no reference price to size the order"

        notional = signal.amount * ref_price
        if notional > Decimal(str(self.cfg.max_order_notional_eur)):
            return False, (
                f"order notional {notional:.2f} > max "
                f"{self.cfg.max_order_notional_eur}"
            )

        if self.open_exposure_eur + notional > Decimal(str(self.cfg.max_total_exposure_eur)):
            return False, "would exceed max total exposure"

        return True, "ok"
