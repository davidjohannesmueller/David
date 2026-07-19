"""Configuration loading from environment (.env) and YAML."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class RiskConfig:
    max_order_notional_eur: float = 1000.0
    max_total_exposure_eur: float = 5000.0
    max_daily_loss_eur: float = 250.0
    max_slippage_pct: float = 0.5


@dataclass
class AppConfig:
    dry_run: bool
    poll_interval_seconds: int
    exchanges: list[dict]
    strategies: dict
    risk: RiskConfig
    allowed_instruments: list[str] = field(default_factory=list)


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(config_path: str | os.PathLike | None = None) -> AppConfig:
    """Load .env + YAML config. Credentials live in .env (per exchange);
    YAML holds venues, strategies and tunable trading parameters."""
    load_dotenv()

    root = Path(__file__).resolve().parent.parent
    cfg_path = Path(config_path) if config_path else root / "config.yaml"
    if not cfg_path.exists():
        example = root / "config.example.yaml"
        if example.exists():
            cfg_path = example  # fall back so a fresh checkout still runs
        else:
            raise FileNotFoundError(f"No config found at {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    dry_run = _as_bool(os.getenv("DRY_RUN"), default=True)
    exchanges = list(raw.get("exchanges", []))

    # allow-list defaults to the union of every venue's instruments.
    allowed = list(raw.get("allowed_instruments") or
                   {i for ex in exchanges for i in ex.get("instruments", [])})

    risk_raw = raw.get("risk", {})
    return AppConfig(
        dry_run=dry_run,
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 10)),
        exchanges=exchanges,
        strategies=raw.get("strategies", {}),
        risk=RiskConfig(**{k: risk_raw[k] for k in risk_raw
                           if k in RiskConfig.__annotations__}),
        allowed_instruments=allowed,
    )
