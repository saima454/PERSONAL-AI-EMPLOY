"""Schedule manager — tracks posting state, history, and topic rotation.

Handles:
- ScheduleState persistence (vault/Logs/posting_schedule.json)
- PostingHistory persistence (vault/Logs/posted_topics.json)
- is_post_due() logic (frequency, skip_weekends, already-posted check)
- get_next_topic_index() rotation (no consecutive repeats)
- draft_exists_today() idempotency check
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class ScheduleState:
    """Operational scheduling state persisted between runs."""

    last_run_date: str | None = None       # YYYY-MM-DD
    last_topic_index: int = -1             # 0-based; -1 = no posts yet
    next_topic_index: int = 0             # 0-based; pre-computed
    post_frequency: str = "daily"         # daily | weekdays_only | custom_days
    skip_weekends: bool = False
    timezone: str = "Asia/Karachi"
    posts_today: int = 0
    updated_at: str | None = None         # ISO 8601


@dataclass
class PostingHistoryEntry:
    """A single entry recording a generated draft."""

    date: str                   # YYYY-MM-DD
    topic_index: int            # 0-based
    topic_title: str
    template_id: str
    draft_path: str
    generated_at: str           # ISO 8601


@dataclass
class PostingHistory:
    """Log of all generated drafts for rotation tracking."""

    entries: list[PostingHistoryEntry] = field(default_factory=list)

    def last_topic_index(self) -> int | None:
        """Return the topic_index from the most recent entry, or None."""
        if not self.entries:
            return None
        return self.entries[-1].topic_index

    def was_posted_today(self, date_str: str) -> bool:
        """Return True if any entry has date == date_str."""
        return any(e.date == date_str for e in self.entries)

    def add_entry(self, entry: PostingHistoryEntry) -> None:
        """Append a new history entry."""
        self.entries.append(entry)


# ── ScheduleManager ───────────────────────────────────────────────────────────


class ScheduleManager:
    """Manages schedule state persistence, rotation, and due-date logic."""

    def __init__(
        self,
        vault_path: str | Path,
        timezone: str = "Asia/Karachi",
        skip_weekends: bool = False,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.logs_dir = self.vault_path / "Logs"
        self.schedule_file = self.logs_dir / "posting_schedule.json"
        self.history_file = self.logs_dir / "posted_topics.json"
        self.timezone = timezone
        self.skip_weekends = skip_weekends

    # ── Timezone helpers ──────────────────────────────────────────────────────

    def _get_tz(self) -> ZoneInfo:
        """Return ZoneInfo for configured timezone, falling back to UTC."""
        try:
            return ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            logger.warning("Unknown timezone %r, falling back to UTC", self.timezone)
            return ZoneInfo("UTC")

    def today_str(self) -> str:
        """Return today's date as YYYY-MM-DD in the configured timezone."""
        return datetime.now(self._get_tz()).strftime("%Y-%m-%d")

    def now_iso(self) -> str:
        """Return current datetime as ISO 8601 with timezone offset."""
        return datetime.now(self._get_tz()).isoformat(timespec="seconds")

    # ── Atomic write ─────────────────────────────────────────────────────────

    def _atomic_write_json(self, path: Path, data: dict | list) -> None:
        """Write JSON to path atomically via .tmp + os.replace().

        Uses os.replace() instead of Path.rename() so that the operation
        succeeds on Windows even when the destination file already exists.
        os.replace() is atomic on POSIX and as close to atomic as possible
        on Windows without elevated privileges.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        try:
            tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_path, path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    # ── ScheduleState persistence ─────────────────────────────────────────────

    def load_state(self) -> ScheduleState:
        """Load ScheduleState from posting_schedule.json.

        Returns default ScheduleState if file missing or corrupt.
        """
        if not self.schedule_file.exists():
            logger.debug("posting_schedule.json not found — using default state")
            return ScheduleState(
                skip_weekends=self.skip_weekends,
                timezone=self.timezone,
            )
        try:
            data = json.loads(self.schedule_file.read_text(encoding="utf-8"))
            return ScheduleState(**{k: v for k, v in data.items() if k in ScheduleState.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Corrupt posting_schedule.json (%s) — resetting to default", exc)
            return ScheduleState(skip_weekends=self.skip_weekends, timezone=self.timezone)

    def save_state(self, state: ScheduleState) -> None:
        """Atomically save ScheduleState to posting_schedule.json."""
        self._atomic_write_json(self.schedule_file, asdict(state))
        logger.debug("Schedule state saved: last_run=%s topic=%d", state.last_run_date, state.last_topic_index)

    # ── PostingHistory persistence ────────────────────────────────────────────

    def load_history(self) -> PostingHistory:
        """Load PostingHistory from posted_topics.json.

        Returns empty history if file missing or corrupt.
        """
        if not self.history_file.exists():
            logger.debug("posted_topics.json not found — starting fresh history")
            return PostingHistory()
        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))
            entries = [PostingHistoryEntry(**e) for e in data.get("entries", [])]
            return PostingHistory(entries=entries)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("Corrupt posted_topics.json (%s) — resetting history", exc)
            return PostingHistory()

    def save_history(self, history: PostingHistory) -> None:
        """Atomically save PostingHistory to posted_topics.json."""
        data = {"entries": [asdict(e) for e in history.entries]}
        self._atomic_write_json(self.history_file, data)
        logger.debug("Posting history saved (%d entries)", len(history.entries))

    # ── Schedule logic ────────────────────────────────────────────────────────

    def is_post_due(self, state: ScheduleState, today: str | None = None) -> bool:
        """Return True if a post should be generated today.

        Checks:
        - Already generated today (posts_today > 0 and same date) → False
        - Weekend skip (skip_weekends=True and today is Sat/Sun) → False
        - weekdays_only frequency and today is weekend → False
        - Otherwise → True
        """
        today = today or self.today_str()

        # Already ran today
        if state.last_run_date == today and state.posts_today > 0:
            logger.debug("Post already generated today (%s)", today)
            return False

        # Parse day of week
        try:
            day = date.fromisoformat(today).weekday()  # 0=Mon, 6=Sun
        except ValueError:
            logger.warning("Invalid date format %r, assuming due", today)
            return True

        is_weekend = day >= 5  # Saturday=5, Sunday=6

        effective_skip = state.skip_weekends or state.post_frequency == "weekdays_only"
        if effective_skip and is_weekend:
            logger.debug("Skipping weekend post (%s is %s)", today, "Sat" if day == 5 else "Sun")
            return False

        return True

    def get_next_topic_index(self, last_topic_index: int, num_topics: int) -> int:
        """Return next 0-based topic index using round-robin rotation.

        Guarantees result != last_topic_index when num_topics > 1.
        Falls back to 0 when num_topics == 1.
        """
        if num_topics <= 0:
            return 0
        if num_topics == 1:
            return 0
        next_idx = (last_topic_index + 1) % num_topics
        # Safety: ensure we never repeat (should never trigger with modulo, but defensive)
        if next_idx == last_topic_index:
            next_idx = (next_idx + 1) % num_topics
        return next_idx

    def draft_exists_today(self, today: str | None = None) -> bool:
        """Return True if any {PLATFORM}_POST_{today}.md exists in Pending_Approval or Approved.

        Checks linkedin, facebook, and instagram platform prefixes for idempotency.
        """
        today = today or self.today_str()
        platforms = ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TWITTER")
        for subdir in ("Pending_Approval", "Approved"):
            for prefix in platforms:
                filename = f"{prefix}_POST_{today}.md"
                if (self.vault_path / subdir / filename).exists():
                    logger.debug("Draft exists today: %s/%s", subdir, filename)
                    return True
        return False
