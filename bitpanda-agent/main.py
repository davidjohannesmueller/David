#!/usr/bin/env python3
"""Entry point for the Bitpanda / One Trading trading agent.

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
from src.client import OneTradingClient
from src.config import load_config


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
    async with OneTradingClient(cfg.rest_url, cfg.api_key) as client:
        agent = TradingAgent(cfg, client)
        await agent.run(run_once=args.once)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bitpanda trading agent")
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
