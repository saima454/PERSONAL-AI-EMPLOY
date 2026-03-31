"""CLI entry point for the orchestrator.

Usage:
    uv run python -m backend.orchestrator
    uv run python -m backend.orchestrator --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Employee Orchestrator")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions without executing them (overrides DRY_RUN env)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Parse args, load config, run orchestrator."""
    load_dotenv(dotenv_path="config/.env")
    args = _parse_args(argv)

    if args.dry_run:
        os.environ["DRY_RUN"] = "true"

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    from backend.orchestrator.orchestrator import Orchestrator, OrchestratorConfig

    config = OrchestratorConfig.from_env()
    orchestrator = Orchestrator(config)

    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Orchestrator interrupted by user (Ctrl+C)")


if __name__ == "__main__":
    main()
