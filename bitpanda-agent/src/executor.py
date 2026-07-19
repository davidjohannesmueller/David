"""Turns approved signals into orders — or, in dry-run mode, simulates them."""
from __future__ import annotations

import logging
from decimal import Decimal

from .client import OneTradingClient
from .models import OrderBook, OrderResult, Signal
from .risk import RiskManager

log = logging.getLogger("agent.executor")


class OrderExecutor:
    def __init__(self, client: OneTradingClient, risk: RiskManager, dry_run: bool):
        self.client = client
        self.risk = risk
        self.dry_run = dry_run

    async def execute(self, signal: Signal, book: OrderBook | None) -> OrderResult:
        allowed, reason = self.risk.check(signal, book)
        if not allowed:
            log.warning("REJECTED %s %s %s — %s",
                        signal.side.value, signal.amount, signal.instrument, reason)
            return OrderResult(accepted=False, dry_run=self.dry_run,
                               signal=signal, detail=reason)

        ref_price = signal.price
        if ref_price is None and book is not None:
            ref_price = book.best_ask if signal.side.value == "BUY" else book.best_bid
        notional = signal.amount * (ref_price or Decimal(0))

        if self.dry_run:
            log.info("[DRY-RUN] would %s %s %s (~%.2f EUR) — %s",
                     signal.side.value, signal.amount, signal.instrument,
                     notional, signal.reason)
            self.risk.register_fill(notional)
            return OrderResult(accepted=True, dry_run=True, signal=signal,
                               detail="simulated")

        try:
            resp = await self.client.create_order(
                instrument=signal.instrument,
                side=signal.side,
                amount=signal.amount,
                order_type=signal.order_type,
                price=signal.price,
            )
            order_id = resp.get("order_id") or resp.get("id")
            log.info("LIVE order placed %s %s %s id=%s",
                     signal.side.value, signal.amount, signal.instrument, order_id)
            self.risk.register_fill(notional)
            return OrderResult(accepted=True, dry_run=False, signal=signal,
                               order_id=order_id, detail="placed")
        except Exception as exc:  # noqa: BLE001 — surface any API failure
            log.error("Order FAILED %s %s %s — %s",
                      signal.side.value, signal.amount, signal.instrument, exc)
            return OrderResult(accepted=False, dry_run=False, signal=signal,
                               detail=str(exc))
