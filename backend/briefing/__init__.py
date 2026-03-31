"""CEO Briefing Generator — weekly executive briefing from vault + Odoo data.

Generates a structured Markdown report every Monday covering financial health,
completed tasks, pending items, communication summary, and proactive suggestions.

Usage:
    uv run python -m backend.briefing.briefing_generator --generate-now
    uv run python -m backend.briefing.briefing_generator --preview
    uv run python -m backend.briefing.briefing_generator --status
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass
class BriefingConfig:
    """Configuration loaded from environment variables and defaults."""

    vault_path: Path = field(default_factory=lambda: Path(os.getenv("VAULT_PATH", "./vault")))
    briefing_day: str = field(default_factory=lambda: os.getenv("CEO_BRIEFING_DAY", "monday").lower())
    briefing_time: str = field(default_factory=lambda: os.getenv("CEO_BRIEFING_TIME", "08:00"))
    briefing_timezone: str = field(default_factory=lambda: os.getenv("CEO_BRIEFING_TIMEZONE", "Asia/Karachi"))
    period_days: int = field(default_factory=lambda: int(os.getenv("CEO_BRIEFING_PERIOD_DAYS", "7")))
    dev_mode: bool = field(default_factory=lambda: os.getenv("DEV_MODE", "true").lower() == "true")
    dry_run: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "false").lower() == "true")

    def __post_init__(self) -> None:
        # Validate period_days
        if self.period_days <= 0:
            import logging
            logging.getLogger(__name__).warning(
                "CEO_BRIEFING_PERIOD_DAYS=%d is invalid, defaulting to 7", self.period_days
            )
            self.period_days = 7

        # Validate timezone
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(self.briefing_timezone)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "CEO_BRIEFING_TIMEZONE=%r is invalid, falling back to UTC",
                self.briefing_timezone,
            )
            self.briefing_timezone = "UTC"

        # Validate time format
        parts = self.briefing_time.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            import logging
            logging.getLogger(__name__).warning(
                "CEO_BRIEFING_TIME=%r is not HH:MM format, defaulting to 08:00",
                self.briefing_time,
            )
            self.briefing_time = "08:00"


# ── Odoo Financial Data ────────────────────────────────────────────────────────


@dataclass
class FinancialSnapshot:
    """Financial data collected from Odoo for the review period."""

    weekly_revenue: float = 0.0
    mtd_revenue: float = 0.0
    monthly_target: float | None = None
    mtd_pct_of_target: float | None = None
    outstanding_invoices_count: int = 0
    outstanding_invoices_total: float = 0.0
    payments_received_count: int = 0
    payments_received_total: float = 0.0
    bank_balance: float = 0.0
    receivables_balance: float = 0.0
    trend: str = "Unknown"
    currency: str = "USD"

    def __post_init__(self) -> None:
        # Calculate trend from mtd_pct_of_target if not set
        if self.mtd_pct_of_target is None and self.monthly_target and self.monthly_target > 0:
            self.mtd_pct_of_target = (self.mtd_revenue / self.monthly_target) * 100

        if self.mtd_pct_of_target is not None:
            if self.mtd_pct_of_target >= 100:
                self.trend = "Ahead"
            elif self.mtd_pct_of_target >= 75:
                self.trend = "On track"
            else:
                self.trend = "Behind"


# ── Task & Item Entities ───────────────────────────────────────────────────────


@dataclass
class CompletedTask:
    """A task from vault/Done/ completed within the review period."""

    title: str
    completed_at: datetime
    completed_date: str
    task_type: str = "unknown"
    source_file: str = ""


@dataclass
class PendingItem:
    """A file in vault/Needs_Action/ or vault/Pending_Approval/ awaiting attention."""

    title: str
    item_type: str = "unknown"
    priority: str = "medium"
    vault_folder: str = "Needs_Action"
    created_at: datetime | None = None
    age_days: int = 0
    source_file: str = ""


# ── Communication & Bottlenecks ────────────────────────────────────────────────


@dataclass
class CommunicationSummary:
    """Aggregated action counts from vault/Logs/actions/*.json for the period."""

    emails_processed: int = 0
    whatsapp_flagged: int = 0
    linkedin_flagged: int = 0
    social_posts_published: int = 0
    total_actions: int = 0


@dataclass
class BottleneckEntry:
    """A detected delay or problematic pattern."""

    item: str
    reason: str
    age_days: int | None = None
    frequency: int | None = None
    bottleneck_type: str = "age"  # "age" | "frequency" | "pattern"


# ── Business Goals ─────────────────────────────────────────────────────────────


@dataclass
class KeyResult:
    """A single OKR key result from Business_Goals.md."""

    metric: str
    target: str
    current: str
    status: str = ""


@dataclass
class Deadline:
    """An upcoming deadline from Business_Goals.md Key Initiatives."""

    initiative: str
    deadline: str
    status: str = ""


@dataclass
class BusinessGoals:
    """Parsed from vault/Business_Goals.md."""

    monthly_revenue_target: float | None = None
    new_clients_target: int | None = None
    key_results: list[KeyResult] = field(default_factory=list)
    upcoming_deadlines: list[Deadline] = field(default_factory=list)
    raw_text: str = ""


# ── Aggregate Briefing Data ────────────────────────────────────────────────────


@dataclass
class BriefingData:
    """Complete collected data for one briefing period."""

    period_start: date
    period_end: date
    generated_at: datetime
    financial: FinancialSnapshot | None = None
    financial_error: str | None = None
    completed_tasks: list[CompletedTask] = field(default_factory=list)
    pending_items: list[PendingItem] = field(default_factory=list)
    communication: CommunicationSummary = field(default_factory=CommunicationSummary)
    bottlenecks: list[BottleneckEntry] = field(default_factory=list)
    business_goals: BusinessGoals | None = None
    suggestions: list[str] = field(default_factory=list)
    dev_mode: bool = True


# ── Result Types ───────────────────────────────────────────────────────────────


@dataclass
class BriefingRunResult:
    """Return value from generate_now() / run_if_due()."""

    status: str  # "generated" | "skipped" | "error"
    briefing_path: Path | None = None
    period_start: str | None = None
    period_end: str | None = None
    reason: str = ""


@dataclass
class BriefingStatusResult:
    """Return value from status() CLI command."""

    last_briefing_path: Path | None = None
    last_briefing_date: str | None = None
    next_scheduled: str = ""
    is_due_today: bool = False
    briefings_dir_exists: bool = False
    done_dir_exists: bool = False
    logs_dir_exists: bool = False
    odoo_reachable: bool | None = None


# ── Public Exports ─────────────────────────────────────────────────────────────

__all__ = [
    "BriefingConfig",
    "BriefingData",
    "BriefingRunResult",
    "BriefingStatusResult",
    "BottleneckEntry",
    "BusinessGoals",
    "CommunicationSummary",
    "CompletedTask",
    "Deadline",
    "FinancialSnapshot",
    "KeyResult",
    "PendingItem",
]
