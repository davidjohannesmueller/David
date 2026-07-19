"""Async REST client for the One Trading (formerly Bitpanda Pro) exchange API.

Endpoints (base: /public/v1):
  GET  instruments                 -> tradable pairs (public)
  GET  order-book/{instrument}     -> order book snapshot (public)
  GET  account/balances            -> balances (auth)
  POST account/orders              -> create order (auth)
  DELETE account/orders/{id}       -> cancel order (auth)

Auth: HTTP header  Authorization: Bearer <API_KEY>
"""
from __future__ import annotations

from decimal import Decimal

import httpx

from .models import Balance, Instrument, OrderBook, OrderType, PriceLevel, Side


class OneTradingClient:
    def __init__(self, rest_url: str, api_key: str = "", timeout: float = 10.0):
        self._base = rest_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base, headers=headers, timeout=timeout
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OneTradingClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # ── Public market data ──────────────────────────────────────────────
    async def get_instruments(self) -> list[Instrument]:
        resp = await self._client.get("/instruments")
        resp.raise_for_status()
        return [Instrument.from_api(item) for item in resp.json()]

    async def get_order_book(self, instrument: str, depth: int = 5) -> OrderBook:
        resp = await self._client.get(
            f"/order-book/{instrument}", params={"level": 2, "depth": depth}
        )
        resp.raise_for_status()
        data = resp.json()

        def levels(rows) -> list[PriceLevel]:
            out = []
            for row in rows or []:
                # API returns dicts {price, amount} or [price, amount] pairs.
                if isinstance(row, dict):
                    price, amount = row.get("price"), row.get("amount")
                else:
                    price, amount = row[0], row[1]
                out.append(PriceLevel(Decimal(str(price)), Decimal(str(amount))))
            return out

        return OrderBook(
            instrument=instrument,
            bids=levels(data.get("bids")),
            asks=levels(data.get("asks")),
        )

    # ── Account (authenticated) ─────────────────────────────────────────
    async def get_balances(self) -> list[Balance]:
        resp = await self._client.get("/account/balances")
        resp.raise_for_status()
        payload = resp.json()
        rows = payload.get("balances", payload) if isinstance(payload, dict) else payload
        result = []
        for row in rows:
            result.append(
                Balance(
                    currency=row.get("currency_code") or row.get("currency", ""),
                    available=Decimal(str(row.get("available", "0"))),
                    locked=Decimal(str(row.get("locked", "0"))),
                )
            )
        return result

    async def create_order(
        self,
        instrument: str,
        side: Side,
        amount: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
    ) -> dict:
        body: dict = {
            "instrument_code": instrument,
            "side": side.value,
            "type": order_type.value,
            "amount": str(amount),
        }
        if order_type is OrderType.LIMIT:
            if price is None:
                raise ValueError("LIMIT order requires a price")
            body["price"] = str(price)
        resp = await self._client.post("/account/orders", json=body)
        resp.raise_for_status()
        return resp.json()

    async def cancel_order(self, order_id: str) -> None:
        resp = await self._client.delete(f"/account/orders/{order_id}")
        resp.raise_for_status()
