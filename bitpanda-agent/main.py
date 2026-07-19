#!/usr/bin/env python3
"""Entry point for the multi-asset trading agent (stocks / crypto / forex).

Examples:
  python main.py                 # run continuously (dry-run per .env)
  python main.py --once          # single evaluation tick, then exit
  python main.py --config my.yaml
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from src.agent import TradingAgent
from src.config import load_config
from src.exchanges import build_exchange


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


async def amain(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    if not cfg.dry_run:
        logging.getLogger("agent").warning(
            "LIVE MODE — real orders will be sent with real money!"
        )
    exchanges = [build_exchange(spec) for spec in cfg.exchanges]
    try:
        agent = TradingAgent(cfg, exchanges)
        await agent.run(run_once=args.once)
    finally:
        for ex in exchanges:
            await ex.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-asset trading agent")
    parser.add_argument("--config", default=None, help="path to config YAML")
    parser.add_argument("--once", action="store_true",
                        help="run a single tick then exit")
    args = parser.parse_args()

    setup_logging()
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        logging.getLogger("agent").info("Stopped by user.")


if __name__ == "__main__":
    main()
