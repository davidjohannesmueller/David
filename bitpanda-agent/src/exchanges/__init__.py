"""Exchange adapters + factory."""
from .alpaca import AlpacaExchange
from .base import Exchange
from .bitpanda import BitpandaExchange
from .mock import MockExchange
from .oanda import OandaExchange

_TYPES = {
    "alpaca": AlpacaExchange,
    "bitpanda": BitpandaExchange,
    "oanda": OandaExchange,
    "mock": MockExchange,
}


def build_exchange(spec: dict) -> Exchange:
    """Build one exchange from a config entry, e.g.
    {type: alpaca, asset_class: stocks, instruments: [AAPL, MSFT]}."""
    etype = spec.get("type")
    cls = _TYPES.get(etype)
    if cls is None:
        raise ValueError(f"Unknown exchange type: {etype!r}")
    instruments = spec.get("instruments", [])
    if etype == "alpaca":
        return AlpacaExchange(instruments, asset_class=spec.get("asset_class", "stocks"))
    return cls(instruments)


__all__ = ["Exchange", "build_exchange", "AlpacaExchange", "BitpandaExchange",
           "OandaExchange", "MockExchange"]
