"""Configuration loading from environment (.env) and YAML."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class RiskConfig:
    max_order_notional_eur: float = 50.0
    max_total_exposure_eur: float = 200.0
    max_daily_loss_eur: float = 25.0
    max_slippage_pct: float = 0.5


@dataclass
class AppConfig:
    api_key: str
    rest_url: str
    dry_run: bool
    poll_interval_seconds: int
    allowed_instruments: list[str]
    risk: RiskConfig
    strategies: dict


def _as_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(config_path: str | os.PathLike | None = None) -> AppConfig:
    """Load .env + YAML config. .env values are required for credentials;
    YAML holds tunable trading parameters."""
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

    api_key = os.getenv("ONETRADING_API_KEY", "").strip()
    dry_run = _as_bool(os.getenv("DRY_RUN"), default=True)

    # Guard against accidentally going live without a key.
    if not dry_run and not api_key:
        raise ValueError("DRY_RUN is false but ONETRADING_API_KEY is not set.")

    risk_raw = raw.get("risk", {})
    return AppConfig(
        api_key=api_key,
        rest_url=os.getenv(
            "ONETRADING_REST_URL", "https://api.exchange.bitpanda.com/public/v1"
        ).rstrip("/"),
        dry_run=dry_run,
        poll_interval_seconds=int(raw.get("poll_interval_seconds", 10)),
        allowed_instruments=list(raw.get("allowed_instruments", [])),
        risk=RiskConfig(**{k: risk_raw[k] for k in risk_raw if k in RiskConfig.__annotations__}),
        strategies=raw.get("strategies", {}),
    )
