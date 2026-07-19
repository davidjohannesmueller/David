"""Trading strategies. Each returns a list of Signals from a market snapshot."""
from .base import Strategy
from .mean_reversion import MeanReversion
from .momentum import Momentum
from .trend_following import TrendFollowing
from .triangular_arbitrage import TriangularArbitrage

REGISTRY = {
    "trend_following": TrendFollowing,
    "triangular_arbitrage": TriangularArbitrage,
    "momentum": Momentum,
    "mean_reversion": MeanReversion,
}

__all__ = ["Strategy", "REGISTRY"]
