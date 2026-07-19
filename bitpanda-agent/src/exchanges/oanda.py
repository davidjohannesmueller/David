"""OANDA adapter — Forex (currencies). Alpaca does not offer forex, so this is
the third venue that completes stocks + crypto + forex.

OANDA has a free "practice" (paper) account, ideal for risk-free development.
Docs: https://developer.oanda.com/rest-live-v20/introduction/
  Practice REST: https://api-fxpractice.oanda.com
Auth header: Authorization: Bearer <token>

Credentials from the environment:
  OANDA_API_TOKEN, OANDA_ACCOUNT_ID
  OANDA_REST_URL (default = practice)

Status: wired against the real v20 endpoints, but not yet validated against a
live practice token. Enable it once you have an OANDA practice account.
Instruments use the underscore form, e.g. EUR_USD, GBP_JPY.
"""
from __future__ import annotations

import os
from decimal import Decimal

import httpx

from ..models import Balance, OrderBook, OrderType, PriceLevel, Side
from .base import Exchange


class OandaExchange(Exchange):
    name = "oanda"
    asset_class = "forex"

    def __init__(self, instruments: list[str]):
        super().__init__(instruments)
        self._account = os.getenv("OANDA_ACCOUNT_ID", "")
        base = os.getenv("OANDA_REST_URL", "https://api-fxpractice.oanda.com").rstrip("/")
        headers = {
            "Authorization": f"Bearer {os.getenv('OANDA_API_TOKEN', '')}",
            "Content-Type": "application/json",
        }
        self._http = httpx.AsyncClient(base_url=base, headers=headers, timeout=10.0)

    async def close(self) -> None:
        await self._http.aclose()

    async def get_order_book(self, instrument: str) -> OrderBook:
        # v20 gives top-of-book bid/ask via the pricing endpoint.
        resp = await self._http.get(
            f"/v3/accounts/{self._account}/pricing",
            params={"instruments": instrument},
        )
        resp.raise_for_status()
        prices = resp.json().get("prices", [])
        if not prices:
            return OrderBook(instrument=instrument)
        p = prices[0]
        bid = p.get("bids", [{}])[0].get("price")
        ask = p.get("asks", [{}])[0].get("price")
        bids = [PriceLevel(Decimal(str(bid)), Decimal(1))] if bid else []
        asks = [PriceLevel(Decimal(str(ask)), Decimal(1))] if ask else []
        return OrderBook(instrument=instrument, bids=bids, asks=asks)

    async def get_balances(self) -> list[Balance]:
        resp = await self._http.get(f"/v3/accounts/{self._account}/summary")
        resp.raise_for_status()
        acct = resp.json().get("account", {})
        return [Balance(currency=acct.get("currency", "EUR"),
                        available=Decimal(str(acct.get("balance", "0"))))]

    async def create_order(self, instrument: str, side: Side, amount: Decimal,
                           order_type: OrderType = OrderType.MARKET,
                           price: Decimal | None = None) -> dict:
        # OANDA signs direction into the units: positive = buy, negative = sell.
        units = amount if side is Side.BUY else -amount
        order: dict = {
            "order": {
                "instrument": instrument,
                "units": str(units),
                "type": order_type.value,       # MARKET / LIMIT
                "timeInForce": "FOK" if order_type is OrderType.MARKET else "GTC",
                "positionFill": "DEFAULT",
            }
        }
        if order_type is OrderType.LIMIT:
            if price is None:
                raise ValueError("LIMIT order requires a price")
            order["order"]["price"] = str(price)
        resp = await self._http.post(f"/v3/accounts/{self._account}/orders", json=order)
        resp.raise_for_status()
        return resp.json()

    async def cancel_order(self, order_id: str) -> None:
        resp = await self._http.put(
            f"/v3/accounts/{self._account}/orders/{order_id}/cancel"
        )
        resp.raise_for_status()
