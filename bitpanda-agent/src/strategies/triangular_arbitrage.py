"""Triangular arbitrage within a single exchange.

Given three instruments that share three currencies (e.g. BTC_EUR, ETH_BTC,
ETH_EUR), we look for a cycle  START -> X -> Y -> START  whose product of
executable rates (best bid/ask, net of taker fees) exceeds 1 + min_profit.
If found, we emit the three legs as market orders.

Note on live execution: the three legs are emitted together with amounts
derived from *expected* fills. In production you should chain each leg on the
actual fill of the previous one; here they are bundled so the flow is visible
end-to-end and fully exercised in dry-run.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from ..models import OrderType, Side, Signal
from .base import MarketSnapshot, Strategy

log = logging.getLogger("agent.strat.arb")


class TriangularArbitrage(Strategy):
    name = "triangular_arbitrage"

    def __init__(self, params: dict):
        super().__init__(params)
        self.cycle: list[str] = list(params.get("cycle", []))
        self.start_currency: str = params.get("start_currency", "EUR")
        self.min_profit = Decimal(str(params.get("min_profit_pct", 0.3))) / 100
        self.fee = Decimal(str(params.get("taker_fee_pct", 0.15))) / 100
        self.notional = Decimal(str(params.get("trade_notional_eur", 30)))

    @property
    def instruments(self) -> list[str]:
        return self.cycle

    def _edges(self, market: MarketSnapshot) -> dict:
        """Map currency->currency to (rate, instrument, side). Returns {} if any
        book is missing a top-of-book price."""
        edges: dict[tuple[str, str], tuple[Decimal, str, Side]] = {}
        for code in self.cycle:
            book = market.order_books.get(code)
            if book is None or book.best_bid is None or book.best_ask is None:
                return {}
            base, quote = code.split("_", 1)
            # Sell base -> receive quote at best bid.
            edges[(base, quote)] = (book.best_bid, code, Side.SELL)
            # Buy base with quote -> pay best ask (rate base per quote = 1/ask).
            edges[(quote, base)] = (Decimal(1) / book.best_ask, code, Side.BUY)
        return edges

    async def evaluate(self, market: MarketSnapshot) -> list[Signal]:
        if len(self.cycle) != 3:
            return []
        edges = self._edges(market)
        if not edges:
            return []

        currencies = {c for code in self.cycle for c in code.split("_", 1)}
        others = [c for c in currencies if c != self.start_currency]
        if len(others) != 2:
            return []

        best: tuple[Decimal, list] | None = None
        # Two possible directions around the triangle.
        for path in ([self.start_currency, others[0], others[1], self.start_currency],
                     [self.start_currency, others[1], others[0], self.start_currency]):
            legs = []
            rate = Decimal(1)
            ok = True
            for frm, to in zip(path, path[1:]):
                edge = edges.get((frm, to))
                if edge is None:
                    ok = False
                    break
                hop_rate, code, side = edge
                rate *= hop_rate * (Decimal(1) - self.fee)
                legs.append((code, side, frm, to, hop_rate))
            if ok and (best is None or rate > best[0]):
                best = (rate, legs)

        if best is None:
            return []

        gross, legs = best
        profit = gross - Decimal(1)
        if profit < self.min_profit:
            log.debug("no arb: best net return %.4f%% < %.4f%%",
                      profit * 100, self.min_profit * 100)
            return []

        log.info("ARB opportunity: net %.4f%% over %s",
                 profit * 100, " -> ".join(p[0] for p in legs))

        # Size the legs by walking the cycle from `notional` in start currency.
        signals: list[Signal] = []
        amount_from = self.notional  # in start currency
        for code, side, frm, to, hop_rate in legs:
            base, quote = code.split("_", 1)
            if side is Side.BUY:  # spend `amount_from` quote, receive base
                base_amount = (amount_from / (Decimal(1) / hop_rate)) * (Decimal(1) - self.fee)
                order_amount = base_amount
                amount_from = base_amount  # now holding base
            else:  # SELL: have `amount_from` base, receive quote
                order_amount = amount_from
                amount_from = amount_from * hop_rate * (Decimal(1) - self.fee)
            signals.append(Signal(
                instrument=code,
                side=side,
                amount=order_amount.quantize(Decimal("0.00000001")),
                order_type=OrderType.MARKET,
                reason=f"triangular arb leg {frm}->{to}, net {profit*100:.3f}%",
                strategy=self.name,
                meta={"arb_net_pct": float(profit * 100)},
            ))
        return signals
