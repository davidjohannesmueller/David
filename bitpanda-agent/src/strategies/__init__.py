"""Trading strategies. Each returns a list of Signals from a market snapshot."""
from .base import Strategy
from .triangular_arbitrage import TriangularArbitrage
from .momentum import Momentum
from .mean_reversion import MeanReversion

REGISTRY = {
    "triangular_arbitrage": TriangularArbitrage,
    "momentum": Momentum,
    "mean_reversion": MeanReversion,
}

__all__ = ["Strategy", "REGISTRY"]
