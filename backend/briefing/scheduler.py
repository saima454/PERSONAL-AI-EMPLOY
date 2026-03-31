"""Briefing scheduler — Monday check logic for the CEO briefing system.

Determines whether a briefing is due based on configured day, time, and timezone.
Uses Python stdlib zoneinfo (backed by tzdata package for Windows support).

No I/O except vault directory check (briefing_exists_today, most_recent_briefing).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class BriefingScheduler:
    """Determines if a CEO briefing is due and provides next-run information.

    Args:
        vault_path: Path to the vault directory.
        day: Day of week for briefing (e.g. "monday"). Case-insensitive.
        time_str: Time for briefing in HH:MM 24-hour format (e.g. "08:00").
        tz_name: IANA timezone name (e.g. "Asia/Karachi"). Falls back to UTC.
    """

    def __init__(
        self,
        vault_path: str | Path,
        day: str = "monday",
        time_str: str = "08:00",
        tz_name: str = "Asia/Karachi",
    ) -> None:
        self.vault_path = Path(vault_path)
        self.day = day.lower().strip()
        self.time_str = time_str
        self.tz_name = tz_name
        self._tz = self._load_tz(tz_name)

    @staticmethod
    def _load_tz(tz_name: str):
        """Load a ZoneInfo object, falling back to UTC on error."""
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except Exception:
            from zoneinfo import ZoneInfo
            logger.warning("Invalid timezone %r — falling back to UTC", tz_name)
            return ZoneInfo("UTC")

    def local_now(self) -> datetime:
        """Return the current datetime in the configured local timezone."""
        return datetime.now(self._tz)

    def is_briefing_due(self) -> bool:
        """Return True if a briefing should be generated right now.

        Conditions (all must be true):
        1. Today (local) matches configured briefing day (e.g. "monday")
        2. Current local time >= configured briefing time (e.g. 08:00)
        3. No briefing file exists for today (idempotency check)
        """
        now = self.local_now()
        today_day = _DAY_NAMES[now.weekday()]

        if today_day != self.day:
            return False

        try:
            h, m = map(int, self.time_str.split(":"))
        except (ValueError, AttributeError):
            logger.warning("Invalid briefing time %r — defaulting to 08:00", self.time_str)
            h, m = 8, 0

        configured_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now < configured_time:
            return False

        return not self.briefing_exists_today()

    def briefing_exists_today(self) -> bool:
        """Return True if a briefing file already exists for today (local date).

        Checks vault/Briefings/YYYY-MM-DD_Monday_Briefing.md using local timezone date.
        The filename suffix is always "_Monday_Briefing.md" regardless of actual weekday,
        matching the spec output format.
        """
        today_local = self.local_now().strftime("%Y-%m-%d")
        briefing_file = self.vault_path / "Briefings" / f"{today_local}_Monday_Briefing.md"
        return briefing_file.exists()

    def most_recent_briefing(self) -> Path | None:
        """Return the path to the most recently generated briefing, or None.

        Finds the newest .md file in vault/Briefings/ by filename (ISO date prefix
        sorts lexicographically).
        """
        briefings_dir = self.vault_path / "Briefings"
        if not briefings_dir.exists():
            return None

        md_files = sorted(briefings_dir.glob("*_Monday_Briefing.md"), reverse=True)
        if not md_files:
            # Fallback: any .md file
            md_files = sorted(briefings_dir.glob("*.md"), reverse=True)

        return md_files[0] if md_files else None

    def next_run_str(self) -> str:
        """Return a human-readable string for the next scheduled briefing run.

        Format: "Monday 2026-03-02 08:00 PKT"

        Calculates the next occurrence of the configured weekday from today.
        """
        now = self.local_now()
        target_weekday = _DAY_NAMES.index(self.day) if self.day in _DAY_NAMES else 0

        days_ahead = target_weekday - now.weekday()
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0:
            # Same day — check if time has passed
            try:
                h, m = map(int, self.time_str.split(":"))
            except (ValueError, AttributeError):
                h, m = 8, 0
            configured_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if now >= configured_time:
                days_ahead = 7  # Already passed today — next week

        next_date = (now + timedelta(days=days_ahead)).date()

        # Get timezone abbreviation
        tz_abbr = now.strftime("%Z") or self.tz_name.split("/")[-1][:3].upper()

        day_name = self.day.capitalize()
        return f"{day_name} {next_date.isoformat()} {self.time_str} {tz_abbr}"
