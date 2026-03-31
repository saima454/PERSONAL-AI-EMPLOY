"""CEO Briefing Generator — weekly executive briefing from vault + Odoo data.

Generates a structured Markdown report covering financial health, completed tasks,
pending items, communication summary, bottlenecks, and proactive suggestions.

Mirrors the ContentScheduler pattern exactly:
    run_if_due()     — idempotent Monday check → generate if due
    generate_now()   — force-generate ignoring schedule
    preview()        — return markdown to console, no files written
    status()         — operational health check
    main()           — CLI entry point

CLI usage:
    uv run python -m backend.briefing.briefing_generator --generate-now
    uv run python -m backend.briefing.briefing_generator --generate-now --force
    uv run python -m backend.briefing.briefing_generator --preview
    uv run python -m backend.briefing.briefing_generator --generate-now --period 30
    uv run python -m backend.briefing.briefing_generator --status
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from backend.briefing import (
    BriefingConfig,
    BriefingData,
    BriefingRunResult,
    BriefingStatusResult,
)
from backend.briefing.data_collectors import DataCollectors
from backend.briefing.report_formatter import ReportFormatter
from backend.briefing.scheduler import BriefingScheduler
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso

logger = logging.getLogger(__name__)

_SENTINEL_START = "<!-- BRIEFING_SECTION_START -->"
_SENTINEL_END = "<!-- BRIEFING_SECTION_END -->"


class BriefingGenerator:
    """Orchestrates the CEO briefing pipeline: config → collect → format → write.

    Args:
        vault_path: Path to vault root directory.
        dev_mode: When True, use mock Odoo data and label output as simulated.
        dry_run: When True, log actions but do not write any files.
        config: Optional pre-built BriefingConfig (overrides vault_path/dev_mode/dry_run).
    """

    def __init__(
        self,
        vault_path: str | Path | None = None,
        dev_mode: bool | None = None,
        dry_run: bool | None = None,
        config: BriefingConfig | None = None,
    ) -> None:
        if config is not None:
            self.config = config
        else:
            self.config = BriefingConfig()
            if vault_path is not None:
                self.config.vault_path = Path(vault_path)
            if dev_mode is not None:
                self.config.dev_mode = dev_mode
            if dry_run is not None:
                self.config.dry_run = dry_run

        self.vault_path = self.config.vault_path
        self._scheduler = BriefingScheduler(
            vault_path=self.vault_path,
            day=self.config.briefing_day,
            time_str=self.config.briefing_time,
            tz_name=self.config.briefing_timezone,
        )
        self.log_dir = self.vault_path / "Logs" / "actions"

    # ── Public API ─────────────────────────────────────────────────────────

    def run_if_due(self) -> BriefingRunResult:
        """Check schedule and generate a briefing if one is due today.

        Idempotent — safe to call multiple times. Skips if:
        - Today is not the configured briefing day
        - Current time is before the configured briefing time
        - A briefing already exists for today

        Returns:
            BriefingRunResult with status "generated", "skipped", or "error".
        """
        try:
            if not self._scheduler.is_briefing_due():
                reason = "Briefing not due (wrong day, early time, or already generated today)"
                logger.debug("CEO briefing: %s", reason)
                self._log_run("briefing_skipped", reason)
                return BriefingRunResult(status="skipped", reason=reason)

            return self.generate_now(
                period_days=self.config.period_days,
                force=False,
            )
        except Exception as exc:
            logger.warning("CEO briefing run_if_due error: %s", exc)
            return BriefingRunResult(status="error", reason=str(exc))

    def generate_now(
        self,
        period_days: int | None = None,
        force: bool = False,
    ) -> BriefingRunResult:
        """Force-generate a briefing, optionally overwriting an existing one.

        Args:
            period_days: Override the lookback window. None uses config default.
            force: If True, overwrite an existing same-day briefing.

        Returns:
            BriefingRunResult with status "generated", "skipped", or "error".
        """
        try:
            effective_days = period_days if period_days is not None else self.config.period_days

            # Idempotency check (unless force)
            if not force and self._scheduler.briefing_exists_today():
                today_local = self._scheduler.local_now().strftime("%Y-%m-%d")
                reason = f"Briefing already exists for {today_local}. Use --force to overwrite."
                logger.info("CEO briefing: %s", reason)
                return BriefingRunResult(status="skipped", reason=reason)

            # Run the full pipeline
            data, content = self._generate_briefing(effective_days)

            if self.config.dry_run:
                logger.info("[DRY_RUN] Would write CEO briefing (not writing)")
                return BriefingRunResult(
                    status="generated",
                    reason="dry_run — no files written",
                    period_start=data.period_start.isoformat(),
                    period_end=data.period_end.isoformat(),
                )

            # Write briefing file
            briefing_path = self._write_briefing(content, data)

            # Update dashboard
            self._update_dashboard(data, briefing_path)

            # Log the run
            self._log_run(
                "briefing_generated",
                f"Period: {data.period_start.isoformat()} to {data.period_end.isoformat()}",
            )

            logger.info(
                "CEO briefing generated: %s (period=%s to %s)",
                briefing_path.name,
                data.period_start.isoformat(),
                data.period_end.isoformat(),
            )
            return BriefingRunResult(
                status="generated",
                briefing_path=briefing_path,
                period_start=data.period_start.isoformat(),
                period_end=data.period_end.isoformat(),
                reason=f"Generated for period {data.period_start.isoformat()} to {data.period_end.isoformat()}",
            )

        except Exception as exc:
            logger.warning("CEO briefing generate_now error: %s", exc)
            self._log_run("briefing_error", str(exc))
            return BriefingRunResult(status="error", reason=str(exc))

    def preview(self, period_days: int | None = None) -> None:
        """Generate briefing content and print to stdout. No files written.

        Args:
            period_days: Override the lookback window. None uses config default.
        """
        effective_days = period_days if period_days is not None else self.config.period_days
        data, content = self._generate_briefing(effective_days)

        print(
            f"\n[PREVIEW] CEO Briefing — Period: "
            f"{data.period_start.isoformat()} to {data.period_end.isoformat()}"
        )
        print("[PREVIEW] ---")
        print(content)
        print("[PREVIEW] --- No files written.")

    def status(self) -> BriefingStatusResult:
        """Return operational status for CLI display.

        Checks: last briefing, next scheduled run, vault directory presence,
        and Odoo connectivity.

        Returns:
            BriefingStatusResult with current operational state.
        """
        last_path = self._scheduler.most_recent_briefing()
        last_date: str | None = None
        if last_path:
            # Extract date from filename: YYYY-MM-DD_Monday_Briefing.md
            date_match = re.match(r"(\d{4}-\d{2}-\d{2})", last_path.name)
            if date_match:
                last_date = date_match.group(1)

        # Odoo connectivity check
        odoo_reachable: bool | None = None
        if not self.config.dev_mode:
            try:
                from backend.mcp_servers.odoo.odoo_client import OdooClient
                odoo = OdooClient(
                    url=os.getenv("ODOO_URL", "http://localhost:8069"),
                    db=os.getenv("ODOO_DATABASE", "ai_employee"),
                    username=os.getenv("ODOO_USERNAME", ""),
                    api_key=os.getenv("ODOO_API_KEY", ""),
                    dev_mode=False,
                )
                odoo.authenticate()
                odoo_reachable = True
            except Exception:
                odoo_reachable = False

        return BriefingStatusResult(
            last_briefing_path=last_path,
            last_briefing_date=last_date,
            next_scheduled=self._scheduler.next_run_str(),
            is_due_today=self._scheduler.is_briefing_due(),
            briefings_dir_exists=(self.vault_path / "Briefings").exists(),
            done_dir_exists=(self.vault_path / "Done").exists(),
            logs_dir_exists=(self.vault_path / "Logs" / "actions").exists(),
            odoo_reachable=odoo_reachable,
        )

    # ── Internal Pipeline ──────────────────────────────────────────────────

    def _generate_briefing(self, period_days: int) -> tuple[BriefingData, str]:
        """Run full data collection and formatting pipeline.

        Args:
            period_days: Number of days to look back.

        Returns:
            (BriefingData, formatted_markdown_string)
        """
        now_utc = datetime.now(UTC)
        local_now = self._scheduler.local_now()
        period_end = local_now.date()
        period_start = period_end - timedelta(days=period_days - 1)

        # Collect business goals first (needed for financial target)
        business_goals = DataCollectors.collect_business_goals(self.vault_path)
        monthly_target: float | None = None
        if business_goals:
            monthly_target = business_goals.monthly_revenue_target

        # Collect all data sources
        financial, financial_error = DataCollectors.collect_financial(
            dev_mode=self.config.dev_mode,
            period_start=period_start,
            period_end=period_end,
            monthly_target=monthly_target,
        )

        completed_tasks = DataCollectors.collect_completed_tasks(
            vault_path=self.vault_path,
            period_start=period_start,
            period_end=period_end,
        )

        pending_items = DataCollectors.collect_pending_items(
            vault_path=self.vault_path,
        )

        communication = DataCollectors.collect_communication_summary(
            vault_path=self.vault_path,
            period_start=period_start,
            period_end=period_end,
        )

        bottlenecks = DataCollectors.detect_bottlenecks(
            pending_items=pending_items,
            communication=communication,
            completed_tasks=completed_tasks,
        )

        suggestions = DataCollectors.generate_suggestions(
            pending_items=pending_items,
            communication=communication,
            financial=financial,
            business_goals=business_goals,
            bottlenecks=bottlenecks,
        )

        data = BriefingData(
            period_start=period_start,
            period_end=period_end,
            generated_at=now_utc,
            financial=financial,
            financial_error=financial_error,
            completed_tasks=completed_tasks,
            pending_items=pending_items,
            communication=communication,
            bottlenecks=bottlenecks,
            business_goals=business_goals,
            suggestions=suggestions,
            dev_mode=self.config.dev_mode,
        )

        content = ReportFormatter.format(data)
        return data, content

    def _write_briefing(self, content: str, data: BriefingData) -> Path:
        """Write the briefing Markdown file to vault/Briefings/.

        Args:
            content: Formatted Markdown string.
            data: BriefingData (used for filename date).

        Returns:
            Path to the written file.
        """
        briefings_dir = self.vault_path / "Briefings"
        briefings_dir.mkdir(parents=True, exist_ok=True)

        # Use local date for filename (as per spec)
        local_date = self._scheduler.local_now().strftime("%Y-%m-%d")
        filename = f"{local_date}_Monday_Briefing.md"
        briefing_path = briefings_dir / filename

        briefing_path.write_text(content, encoding="utf-8")
        logger.debug("Briefing written: %s (%d bytes)", briefing_path, len(content))
        return briefing_path

    def _update_dashboard(self, data: BriefingData, briefing_path: Path) -> None:
        """Update vault/Dashboard.md with the latest briefing info.

        Uses sentinel comments to preserve the rest of the dashboard:
            <!-- BRIEFING_SECTION_START -->
            ...
            <!-- BRIEFING_SECTION_END -->

        If the sentinel is absent (first run), the block is prepended.
        """
        dashboard = self.vault_path / "Dashboard.md"

        generated_str = data.generated_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        relative_path = f"vault/Briefings/{briefing_path.name}"

        # Build the briefing block
        weekly_rev = ""
        if data.financial:
            weekly_rev = f"{data.financial.currency} {data.financial.weekly_revenue:,.2f}"
        else:
            weekly_rev = "N/A"

        new_block = (
            f"{_SENTINEL_START}\n"
            f"## Latest Briefing\n"
            f"- **Date**: {data.period_end.isoformat()}\n"
            f"- **File**: {relative_path}\n"
            f"- **Period**: {data.period_start.isoformat()} to {data.period_end.isoformat()}\n"
            f"- **Revenue this week**: {weekly_rev}\n"
            f"- **Tasks completed**: {len(data.completed_tasks)}\n"
            f"- **Pending items**: {len(data.pending_items)}\n"
            f"- **Generated**: {generated_str}\n"
            f"{_SENTINEL_END}"
        )

        if dashboard.exists():
            existing = dashboard.read_text(encoding="utf-8")
            if _SENTINEL_START in existing:
                # Replace existing sentinel block
                pattern = re.compile(
                    re.escape(_SENTINEL_START) + r".*?" + re.escape(_SENTINEL_END),
                    re.DOTALL,
                )
                updated = pattern.sub(new_block, existing)
            else:
                # Prepend the block
                updated = new_block + "\n\n" + existing
        else:
            updated = new_block + "\n"

        dashboard.write_text(updated, encoding="utf-8")
        logger.debug("Dashboard updated with latest briefing sentinel block")

    def _log_run(self, action_type: str, details: str) -> None:
        """Log a briefing run event to vault/Logs/actions/."""
        try:
            log_action(
                self.log_dir,
                {
                    "timestamp": now_iso(),
                    "actor": "briefing-generator",
                    "action_type": action_type,
                    "target": "vault/Briefings/",
                    "result": "success" if "error" not in action_type else "error",
                    "details": details,
                },
            )
        except Exception as exc:
            logger.debug("Could not write briefing log: %s", exc)


# ── CLI Entry Point ─────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CEO Briefing Generator — AI Employee Weekly Executive Report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --generate-now                # Generate briefing immediately\n"
            "  %(prog)s --generate-now --force        # Overwrite existing same-day briefing\n"
            "  %(prog)s --generate-now --period 30   # 30-day lookback\n"
            "  %(prog)s --preview                     # Preview without writing files\n"
            "  %(prog)s --status                      # Check system status\n"
        ),
    )

    action_group = parser.add_mutually_exclusive_group()
    action_group.add_argument(
        "--generate-now",
        action="store_true",
        help="Generate a CEO briefing immediately (respects --force and --period)",
    )
    action_group.add_argument(
        "--preview",
        action="store_true",
        help="Preview briefing content without writing any files",
    )
    action_group.add_argument(
        "--status",
        action="store_true",
        help="Show system status (last run, next scheduled, data source health)",
    )

    parser.add_argument(
        "--period",
        type=int,
        default=None,
        metavar="N",
        help="Override lookback window to N days (default: CEO_BRIEFING_PERIOD_DAYS or 7)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing same-day briefing file",
    )
    parser.add_argument(
        "--vault-path",
        default=None,
        help="Override vault path (default: VAULT_PATH env var or ./vault)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions but do not write any files",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for the CEO briefing generator."""
    # Ensure stdout handles Unicode/emoji on Windows terminals
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    env_path = Path(__file__).resolve().parents[2] / "config" / ".env"
    load_dotenv(env_path)

    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    args = _parse_args(argv)

    vault_path = args.vault_path or os.getenv("VAULT_PATH", "./vault")
    dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"
    dry_run = args.dry_run or os.getenv("DRY_RUN", "false").lower() == "true"

    generator = BriefingGenerator(
        vault_path=vault_path,
        dev_mode=dev_mode,
        dry_run=dry_run,
    )

    try:
        # ── --status ────────────────────────────────────────────────────────
        if args.status:
            result = generator.status()
            print("\nCEO Briefing Status")
            print("=" * 42)
            if result.last_briefing_path:
                print(f"Last briefing   : {result.last_briefing_path.name}")
                print(f"Last generated  : {result.last_briefing_date or 'unknown'}")
            else:
                print("Last briefing   : No briefings generated yet")
            print(f"Next scheduled  : {result.next_scheduled}")
            print(f"Due today       : {'YES' if result.is_due_today else 'NO'}")
            print(f"vault/Briefings/: {'✓ exists' if result.briefings_dir_exists else '✗ missing'}")
            print(f"vault/Done/     : {'✓ exists' if result.done_dir_exists else '✗ missing'}")
            print(f"vault/Logs/     : {'✓ exists' if result.logs_dir_exists else '✗ missing'}")
            if result.odoo_reachable is None:
                print("Odoo            : DEV_MODE (no connectivity check)")
            else:
                print(f"Odoo            : {'✓ reachable' if result.odoo_reachable else '✗ unreachable'}")
            return

        # ── --preview ───────────────────────────────────────────────────────
        if args.preview:
            generator.preview(period_days=args.period)
            return

        # ── --generate-now (or plain run → run_if_due) ──────────────────────
        if args.generate_now:
            result = generator.generate_now(period_days=args.period, force=args.force)
        else:
            result = generator.run_if_due()

        if result.status == "generated":
            print(f"✅ Briefing generated: {result.briefing_path}")
            print(f"   Period: {result.period_start} to {result.period_end}")
        elif result.status == "skipped":
            print(f"ℹ️  Skipped: {result.reason}")
        else:
            print(f"❌ Error: {result.reason}")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        print(f"❌ Unexpected error: {exc}")
        sys.exit(3)


if __name__ == "__main__":
    main()
