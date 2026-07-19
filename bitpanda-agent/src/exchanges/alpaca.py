"""Alpaca adapter — covers US stocks/ETFs AND crypto.

Paper trading is free and works from anywhere (no EU restriction), which makes
it the recommended venue for developing and validating the agent risk-free.

Docs: https://docs.alpaca.markets/
  Trading (paper): https://paper-api.alpaca.markets/v2
  Market data:     https://data.alpaca.markets
Auth headers: APCA-API-KEY-ID, APCA-API-SECRET-KEY

Credentials come from the environment:
  ALPACA_API_KEY, ALPACA_API_SECRET
  ALPACA_TRADING_URL (default = paper), ALPACA_DATA_URL
"""
from __future__ import annotations

import os
from decimal import Decimal

import httpx

from ..models import Balance, OrderBook, OrderType, PriceLevel, Side
from .base import Exchange


class AlpacaExchange(Exchange):
    name = "alpaca"

    def __init__(self, instruments: list[str], asset_class: str = "stocks"):
        super().__init__(instruments)
        self.asset_class = asset_class  # "stocks" or "crypto"
        key = os.getenv("ALPACA_API_KEY", "")
        secret = os.getenv("ALPACA_API_SECRET", "")
        self._trading_url = os.getenv(
            "ALPACA_TRADING_URL", "https://paper-api.alpaca.markets"
        ).rstrip("/")
        self._data_url = os.getenv(
            "ALPACA_DATA_URL", "https://data.alpaca.markets"
        ).rstrip("/")
        headers = {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
        }
        self._http = httpx.AsyncClient(headers=headers, timeout=10.0)

    async def close(self) -> None:
        await self._http.aclose()

    # ── market data ─────────────────────────────────────────────────────
    async def get_order_book(self, instrument: str) -> OrderBook:
        if self.asset_class == "crypto":
            # Crypto symbols use the BTC/USD form.
            url = f"{self._data_url}/v1beta3/crypto/us/latest/quotes"
            resp = await self._http.get(url, params={"symbols": instrument})
            resp.raise_for_status()
            q = resp.json().get("quotes", {}).get(instrument, {})
        else:
            url = f"{self._data_url}/v2/stocks/{instrument}/quotes/latest"
            resp = await self._http.get(url)
            resp.raise_for_status()
            q = resp.json().get("quote", {})

        bid, ask = q.get("bp"), q.get("ap")  # bid price / ask price
        bids = [PriceLevel(Decimal(str(bid)), Decimal(str(q.get("bs", 0))))] if bid else []
        asks = [PriceLevel(Decimal(str(ask)), Decimal(str(q.get("as", 0))))] if ask else []
        return OrderBook(instrument=instrument, bids=bids, asks=asks)

    # ── account / trading ───────────────────────────────────────────────
    async def get_balances(self) -> list[Balance]:
        resp = await self._http.get(f"{self._trading_url}/v2/account")
        resp.raise_for_status()
        acct = resp.json()
        out = [Balance(currency=acct.get("currency", "USD"),
                       available=Decimal(str(acct.get("cash", "0"))))]
        pos = await self._http.get(f"{self._trading_url}/v2/positions")
        if pos.status_code == 200:
            for p in pos.json():
                out.append(Balance(currency=p.get("symbol", ""),
                                   available=Decimal(str(p.get("qty", "0")))))
        return out

    async def create_order(
        self,
        instrument: str,
        side: Side,
        amount: Decimal,
        order_type: OrderType = OrderType.MARKET,
        price: Decimal | None = None,
    ) -> dict:
        body: dict = {
            "symbol": instrument,
            "qty": str(amount),
            "side": side.value.lower(),           # alpaca uses "buy"/"sell"
            "type": order_type.value.lower(),     # "market"/"limit"
            "time_in_force": "gtc" if self.asset_class == "crypto" else "day",
        }
        if order_type is OrderType.LIMIT:
            if price is None:
                raise ValueError("LIMIT order requires a price")
            body["limit_price"] = str(price)
        resp = await self._http.post(f"{self._trading_url}/v2/orders", json=body)
        resp.raise_for_status()
        return resp.json()

    async def cancel_order(self, order_id: str) -> None:
        resp = await self._http.delete(f"{self._trading_url}/v2/orders/{order_id}")
        resp.raise_for_status()
