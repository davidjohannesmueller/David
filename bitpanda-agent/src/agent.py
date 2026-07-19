"""The trading agent: fetch market data, run strategies, execute signals."""
from __future__ import annotations

import asyncio
import logging

from .client import OneTradingClient
from .config import AppConfig
from .executor import OrderExecutor
from .models import OrderBook
from .risk import RiskManager
from .strategies import REGISTRY
from .strategies.base import MarketSnapshot, Strategy

log = logging.getLogger("agent")

# Keep at most this many mid prices per instrument for indicator windows.
MAX_HISTORY = 500


class TradingAgent:
    def __init__(self, cfg: AppConfig, client: OneTradingClient):
        self.cfg = cfg
        self.client = client
        self.risk = RiskManager(cfg.risk, cfg.allowed_instruments)
        self.executor = OrderExecutor(client, self.risk, cfg.dry_run)
        self.strategies: list[Strategy] = self._build_strategies()
        self.price_history: dict[str, list[float]] = {}

    def _build_strategies(self) -> list[Strategy]:
        active: list[Strategy] = []
        for name, params in self.cfg.strategies.items():
            cls = REGISTRY.get(name)
            if cls is None:
                log.warning("Unknown strategy '%s' in config — skipped", name)
                continue
            strat = cls(params or {})
            if strat.enabled:
                active.append(strat)
                log.info("Strategy enabled: %s", name)
        return active

    def _needed_instruments(self) -> set[str]:
        needed: set[str] = set()
        for strat in self.strategies:
            needed.update(strat.instruments)
        return needed & set(self.cfg.allowed_instruments) or needed

    async def _snapshot(self) -> MarketSnapshot:
        instruments = self._needed_instruments()
        books: dict[str, OrderBook] = {}
        results = await asyncio.gather(
            *(self.client.get_order_book(code) for code in instruments),
            return_exceptions=True,
        )
        for code, res in zip(instruments, results):
            if isinstance(res, Exception):
                log.warning("order book fetch failed for %s: %s", code, res)
                continue
            books[code] = res
            if res.mid is not None:
                hist = self.price_history.setdefault(code, [])
                hist.append(float(res.mid))
                del hist[:-MAX_HISTORY]
        return MarketSnapshot(order_books=books, price_history=self.price_history)

    async def tick(self) -> None:
        if self.risk.halted():
            log.error("Risk manager halted trading — skipping tick.")
            return
        market = await self._snapshot()
        for strat in self.strategies:
            try:
                signals = await strat.evaluate(market)
            except Exception as exc:  # noqa: BLE001
                log.error("Strategy %s raised: %s", strat.name, exc)
                continue
            for sig in signals:
                await self.executor.execute(sig, market.order_books.get(sig.instrument))

    async def run(self, run_once: bool = False) -> None:
        mode = "DRY-RUN (simulated)" if self.cfg.dry_run else "LIVE (real money!)"
        log.info("Agent starting — mode: %s — strategies: %d",
                 mode, len(self.strategies))
        if not self.strategies:
            log.warning("No strategies enabled. Nothing to do.")
            return
        while True:
            await self.tick()
            if run_once:
                return
            await asyncio.sleep(self.cfg.poll_interval_seconds)
