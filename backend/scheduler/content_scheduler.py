"""Content scheduler — generates LinkedIn post drafts from vault/Content_Strategy.md.

Main entry point for the content scheduling system. Reads the user's content strategy,
selects the next topic in rotation, generates a post draft from templates, and saves it
to vault/Pending_Approval/ for human review via the HITL workflow.

CLI usage:
    uv run python -m backend.scheduler.content_scheduler [--generate-now] [--preview] [--status]

Orchestrator usage:
    scheduler = ContentScheduler(vault_path=config.vault_path)
    result = scheduler.run_if_due()
"""


from __future__ import annotations

import argparse
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from backend.scheduler.post_generator import (
    PostContext,
    PostGenerator,
    normalize_topic_key,
)
from backend.scheduler.schedule_manager import (
    PostingHistory,
    PostingHistoryEntry,
    ScheduleManager,
    ScheduleState,
)
from backend.utils.frontmatter import create_file_with_frontmatter

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────


class ContentStrategyError(Exception):
    """Raised when vault/Content_Strategy.md is missing or cannot be parsed."""


class TemplateGenerationError(Exception):
    """Raised when no template can produce a valid post for the selected topic."""


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class Topic:
    """A single topic entry from Content_Strategy.md."""

    index: int          # 0-based position
    title: str          # e.g. "AI and Automation"
    description: str    # e.g. "Share insights about building AI agents"
    topic_key: str      # Normalized key e.g. "ai_automation"
    platform: str = "linkedin"  # linkedin | facebook | instagram (default: linkedin)


@dataclass
class ContentStrategy:
    """Parsed user content strategy from vault/Content_Strategy.md."""

    topics: list[Topic]
    post_frequency: str = "daily"
    preferred_time: str = "09:00"
    tone: str = "professional"
    max_hashtags: int = 5
    content_rules: list[str] = None       # type: ignore[assignment]
    excluded_topics: list[str] = None     # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.content_rules is None:
            self.content_rules = []
        if self.excluded_topics is None:
            self.excluded_topics = []


@dataclass
class RunResult:
    """Result from run_if_due() or generate_now()."""

    status: str                  # "generated" | "skipped" | "error"
    draft_path: str | None = None
    topic: str | None = None
    reason: str = ""


@dataclass
class PreviewResult:
    """Result from preview() — content only, no files written."""

    topic: str
    post_text: str
    character_count: int
    template_id: str


@dataclass
class StatusResult:
    """Result from status() — current schedule state for display."""

    last_post_date: str | None
    last_topic: str | None
    next_topic: str | None
    is_due_today: bool
    posts_today: int
    next_run_time: str


# ── ContentScheduler ──────────────────────────────────────────────────────────


class ContentScheduler:
    """Generates LinkedIn post drafts from user-defined content strategy."""

    def __init__(
        self,
        vault_path: str | Path = "./vault",
        dev_mode: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.dev_mode = dev_mode
        self.dry_run = dry_run
        self.timezone = os.getenv("CONTENT_TIMEZONE", "Asia/Karachi")
        self.skip_weekends = os.getenv("CONTENT_SKIP_WEEKENDS", "false").lower() == "true"
        self._schedule_manager = ScheduleManager(
            vault_path=self.vault_path,
            timezone=self.timezone,
            skip_weekends=self.skip_weekends,
        )
        self._generator = PostGenerator(
            max_hashtags=int(os.getenv("CONTENT_MAX_HASHTAGS", "5")),
        )

    # ── Strategy loading ──────────────────────────────────────────────────────

    def _load_strategy(self) -> ContentStrategy:
        """Parse vault/Content_Strategy.md into a ContentStrategy object.

        Raises:
            ContentStrategyError: if file missing, YAML unreadable, or no topics
        """
        strategy_path = self.vault_path / "Content_Strategy.md"
        if not strategy_path.exists():
            raise ContentStrategyError(
                f"Content_Strategy.md not found at {strategy_path}. "
                "Create it first — see vault/Content_Strategy.md template."
            )

        try:
            content = strategy_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ContentStrategyError(f"Cannot read Content_Strategy.md: {exc}") from exc

        # Parse YAML frontmatter
        fm: dict = {}
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", content, re.DOTALL)
        if fm_match:
            import yaml
            try:
                fm = yaml.safe_load(fm_match.group(1)) or {}
            except Exception:
                logger.warning("Could not parse Content_Strategy.md frontmatter — using defaults")

        # Parse body sections
        body = content[fm_match.end():] if fm_match else content

        topics = self._parse_topics(body)
        if not topics:
            raise ContentStrategyError(
                "No topics found in Content_Strategy.md. "
                "Add entries under '## Topics I Want to Post About'."
            )

        return ContentStrategy(
            topics=topics,
            post_frequency=str(fm.get("post_frequency", os.getenv("CONTENT_POST_FREQUENCY", "daily"))),
            preferred_time=str(fm.get("preferred_time", os.getenv("CONTENT_POST_TIME", "09:00"))),
            tone=str(fm.get("tone", "professional")),
            max_hashtags=int(fm.get("max_hashtags", 5)),
            content_rules=self._parse_list_section(body, "## Content Rules"),
            excluded_topics=self._parse_list_section(body, "## Do NOT Post About"),
        )

    @staticmethod
    def _parse_topics(body: str) -> list[Topic]:
        """Extract numbered topic list from strategy body.

        Topic format:
            1. Title - Description
            2. Title [platform: facebook] - Description
            3. Title - Description [platform: instagram]
        The optional [platform: X] tag anywhere in the line sets the target
        platform (linkedin | facebook | instagram). Default: linkedin.
        """
        topics: list[Topic] = []
        in_section = False
        platform_pattern = re.compile(r"\[platform:\s*(linkedin|facebook|instagram|twitter)\]", re.IGNORECASE)
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("## topics i want to post about"):
                in_section = True
                continue
            if in_section and stripped.startswith("## "):
                break
            if in_section and re.match(r"^\d+\.", stripped):
                # Extract and remove optional [platform: X] tag
                platform = "linkedin"
                platform_match = platform_pattern.search(stripped)
                if platform_match:
                    platform = platform_match.group(1).lower()
                    stripped = platform_pattern.sub("", stripped).strip()

                # Format: "1. Title - Description"
                parts = stripped.split(".", 1)[1].strip()
                if " - " in parts:
                    title, description = parts.split(" - ", 1)
                else:
                    title, description = parts, ""
                title = title.strip()
                description = description.strip()
                topics.append(Topic(
                    index=len(topics),
                    title=title,
                    description=description,
                    topic_key=normalize_topic_key(title),
                    platform=platform,
                ))
        return topics

    @staticmethod
    def _parse_list_section(body: str, heading: str) -> list[str]:
        """Extract bullet list from a named section in the body."""
        items: list[str] = []
        in_section = False
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith(heading.lower()):
                in_section = True
                continue
            if in_section and stripped.startswith("## "):
                break
            if in_section and stripped.startswith("-"):
                items.append(stripped.lstrip("- ").strip())
        return items

    def _load_context(self) -> PostContext:
        """Load optional context from Company_Handbook.md and Business_Goals.md."""
        def _read(filename: str) -> str | None:
            path = self.vault_path / filename
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")[:2000]  # cap at 2KB
                except OSError:
                    return None
            return None

        return PostContext(
            business_goals=_read("Business_Goals.md"),
            company_handbook=_read("Company_Handbook.md"),
        )

    # ── Draft saving ──────────────────────────────────────────────────────────

    def _save_draft(
        self,
        topic: Topic,
        post_body: str,
        template_id: str,
        character_count: int,
        today: str,
    ) -> Path:
        """Write {PLATFORM}_POST_{date}.md to vault/Pending_Approval/.

        Platform is read from topic.platform (default: "linkedin").
        ActionExecutor routes by the frontmatter "type" field:
          linkedin → type: linkedin_post
          facebook → type: facebook_post
          instagram → type: instagram_post

        Returns the path of the created file.
        """
        pending_dir = self.vault_path / "Pending_Approval"
        pending_dir.mkdir(parents=True, exist_ok=True)
        platform = getattr(topic, "platform", "linkedin")
        filename = f"{platform.upper()}_POST_{today}.md"
        draft_path = pending_dir / filename

        sm = self._schedule_manager
        frontmatter = {
            "type": f"{platform}_post",        # ActionExecutor reads fm.get("type")
            "platform": platform,
            "status": "pending_approval",
            "topic": topic.title,
            "topic_index": topic.index,
            "template_id": template_id,
            "generated_at": sm.now_iso(),
            "scheduled_date": today,
            "character_count": character_count,
        }
        body = f"\n# Post Content\n\n{post_body}\n"

        if self.dry_run:
            logger.info("[DRY_RUN] Would write draft to %s", draft_path)
            return draft_path

        create_file_with_frontmatter(draft_path, frontmatter, body)
        logger.info("Draft saved: %s (%d chars, platform=%s)", draft_path, character_count, platform)
        return draft_path

    # ── Core pipeline ─────────────────────────────────────────────────────────

    def _generate_pipeline(
        self,
        strategy: ContentStrategy,
        state: ScheduleState,
        history: PostingHistory,  # noqa: ARG002  # kept for API symmetry with callers
        today: str,               # noqa: ARG002  # kept for API symmetry with callers
        force: bool = False,
    ) -> tuple[Topic, str, str, int]:
        """Run generation pipeline: select topic → generate post.

        Returns (topic, post_body, template_id, character_count).
        Raises TemplateGenerationError on failure.
        """
        # Select topic index
        if force or state.last_topic_index == -1:
            next_idx = self._schedule_manager.get_next_topic_index(
                state.last_topic_index, len(strategy.topics)
            )
        else:
            next_idx = state.next_topic_index

        next_idx = next_idx % len(strategy.topics)
        topic = strategy.topics[next_idx]

        logger.info("Selected topic: [%d] %r (key=%s)", next_idx, topic.title, topic.topic_key)

        context = self._load_context()
        try:
            generated = self._generator.generate(
                topic_key=topic.topic_key,
                topic_title=topic.title,
                context=context,
                platform=getattr(topic, "platform", "linkedin"),
            )
        except (ValueError, RuntimeError) as exc:
            raise TemplateGenerationError(str(exc)) from exc

        return topic, generated.body, generated.template_id, generated.character_count

    def _update_state_after_generation(
        self,
        state: ScheduleState,
        history: PostingHistory,
        topic: Topic,
        template_id: str,
        draft_path: Path,
        today: str,
        num_topics: int,
    ) -> tuple[ScheduleState, PostingHistory]:
        """Update and persist state + history after successful draft generation."""
        sm = self._schedule_manager

        # Update history
        history.add_entry(PostingHistoryEntry(
            date=today,
            topic_index=topic.index,
            topic_title=topic.title,
            template_id=template_id,
            draft_path=str(draft_path),
            generated_at=sm.now_iso(),
        ))

        # Compute next topic for next run
        next_next_idx = sm.get_next_topic_index(topic.index, num_topics)

        # Update state
        state.last_run_date = today
        state.last_topic_index = topic.index
        state.next_topic_index = next_next_idx
        state.posts_today = (state.posts_today + 1) if state.last_run_date == today else 1
        state.updated_at = sm.now_iso()

        if not self.dry_run:
            sm.save_history(history)
            sm.save_state(state)

        return state, history

    # ── Public API ────────────────────────────────────────────────────────────

    def run_if_due(self) -> RunResult:
        """Check schedule and generate a draft if a post is due today.

        Idempotent — safe to call multiple times on the same day.

        Returns:
            RunResult with status "generated", "skipped", or "error".

        Raises:
            ContentStrategyError: if Content_Strategy.md is missing or invalid.
        """
        strategy = self._load_strategy()  # raises ContentStrategyError
        sm = self._schedule_manager
        today = sm.today_str()
        state = sm.load_state()
        history = sm.load_history()

        # Idempotency guard
        if sm.draft_exists_today(today):
            logger.info("Draft already exists for %s — skipping", today)
            return RunResult(status="skipped", reason=f"Draft already exists for {today}")

        # Schedule check
        if not sm.is_post_due(state, today):
            reason = f"Post not due today ({today})"
            logger.info(reason)
            return RunResult(status="skipped", reason=reason)

        try:
            topic, post_body, template_id, char_count = self._generate_pipeline(
                strategy, state, history, today
            )
        except TemplateGenerationError as exc:
            logger.error("Template generation failed: %s", exc)
            return RunResult(status="error", reason=str(exc))

        draft_path = self._save_draft(topic, post_body, template_id, char_count, today)
        self._update_state_after_generation(
            state, history, topic, template_id, draft_path, today, len(strategy.topics)
        )

        return RunResult(
            status="generated",
            draft_path=str(draft_path),
            topic=topic.title,
            reason=f"Generated for {today}",
        )

    def generate_now(self) -> RunResult:
        """Force-generate a draft, ignoring schedule and idempotency.

        Always generates a new draft, overwriting if one exists today.

        Returns:
            RunResult with status "generated" or "error".

        Raises:
            ContentStrategyError: if Content_Strategy.md is missing or invalid.
        """
        strategy = self._load_strategy()
        sm = self._schedule_manager
        today = sm.today_str()
        state = sm.load_state()
        history = sm.load_history()

        logger.info("Force-generating draft for %s", today)

        try:
            topic, post_body, template_id, char_count = self._generate_pipeline(
                strategy, state, history, today, force=True
            )
        except TemplateGenerationError as exc:
            logger.error("Template generation failed: %s", exc)
            return RunResult(status="error", reason=str(exc))

        # Remove existing draft if present (--generate-now overrides)
        # Check both platform-specific and legacy linkedin filename
        platform = getattr(topic, "platform", "linkedin")
        existing = self.vault_path / "Pending_Approval" / f"{platform.upper()}_POST_{today}.md"
        if existing.exists() and not self.dry_run:
            existing.unlink()
            logger.info("Removed existing draft to regenerate: %s", existing.name)

        draft_path = self._save_draft(topic, post_body, template_id, char_count, today)
        self._update_state_after_generation(
            state, history, topic, template_id, draft_path, today, len(strategy.topics)
        )

        return RunResult(
            status="generated",
            draft_path=str(draft_path),
            topic=topic.title,
            reason="Force-generated (--generate-now)",
        )

    def preview(self) -> PreviewResult:
        """Generate post content and return it without writing any files.

        Returns:
            PreviewResult with topic, post_text, character_count, template_id.

        Raises:
            ContentStrategyError: if Content_Strategy.md is missing.
            TemplateGenerationError: if all templates fail validation.
        """
        strategy = self._load_strategy()
        sm = self._schedule_manager
        today = sm.today_str()
        state = sm.load_state()
        history = sm.load_history()

        topic, post_body, template_id, char_count = self._generate_pipeline(
            strategy, state, history, today
        )
        logger.info("[PREVIEW] Topic=%r template=%s chars=%d (no files written)", topic.title, template_id, char_count)

        return PreviewResult(
            topic=topic.title,
            post_text=post_body,
            character_count=char_count,
            template_id=template_id,
        )

    def status(self) -> StatusResult:
        """Return current schedule state for CLI display.

        Returns:
            StatusResult with last/next topic, due-today flag, etc.
        """
        sm = self._schedule_manager
        today = sm.today_str()
        state = sm.load_state()
        history = sm.load_history()

        # Try to load strategy for next topic name (graceful if missing)
        next_topic_name: str | None = None
        last_topic_name: str | None = None
        try:
            strategy = self._load_strategy()
            if strategy.topics:
                next_idx = state.next_topic_index % len(strategy.topics)
                next_topic_name = strategy.topics[next_idx].title
            if state.last_topic_index >= 0 and strategy.topics:
                last_idx = state.last_topic_index % len(strategy.topics)
                last_topic_name = strategy.topics[last_idx].title
        except ContentStrategyError:
            pass

        # If no history but entries exist, use last entry's topic
        if last_topic_name is None and history.entries:
            last_topic_name = history.entries[-1].topic_title

        is_due = sm.is_post_due(state, today) and not sm.draft_exists_today(today)

        return StatusResult(
            last_post_date=state.last_run_date,
            last_topic=last_topic_name,
            next_topic=next_topic_name,
            is_due_today=is_due,
            posts_today=state.posts_today if state.last_run_date == today else 0,
            next_run_time=state.post_frequency if hasattr(state, "post_frequency") else "09:00",
        )


# ── CLI Entry Point ────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Content Scheduler — AI Employee LinkedIn Draft Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--generate-now",
        action="store_true",
        help="Force generate a draft immediately, ignoring schedule",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview generated post content without saving any files",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current schedule status and exit",
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
    """CLI entry point for content scheduler."""
    import sys
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

    scheduler = ContentScheduler(
        vault_path=vault_path,
        dev_mode=dev_mode,
        dry_run=dry_run,
    )

    try:
        if args.status:
            result = scheduler.status()
            print("\nContent Scheduler Status")
            print("=" * 40)
            print(f"Last post date  : {result.last_post_date or 'None (no posts yet)'}")
            print(f"Last topic      : {result.last_topic or 'None'}")
            print(f"Next topic      : {result.next_topic or 'Unknown'}")
            print(f"Due today       : {'YES' if result.is_due_today else 'NO'}")
            print(f"Posts today     : {result.posts_today}")
            print(f"Frequency       : {result.next_run_time}")
            return

        if args.preview:
            result = scheduler.preview()
            print(f"\n[PREVIEW] Topic: {result.topic}")
            print(f"[PREVIEW] Template: {result.template_id}")
            print(f"[PREVIEW] Character count: {result.character_count}/1300")
            print("[PREVIEW] ---")
            print(result.post_text)
            print("---")
            print("[PREVIEW] No files written.")
            return

        run_result = scheduler.generate_now() if args.generate_now else scheduler.run_if_due()

        if run_result.status == "generated":
            print(f"✅ Draft generated: {run_result.draft_path}")
            print(f"   Topic: {run_result.topic}")
        elif run_result.status == "skipped":
            print(f"ℹ️  Skipped: {run_result.reason}")
        else:
            print(f"❌ Error: {run_result.reason}")
            raise SystemExit(1)

    except ContentStrategyError as exc:
        logger.error("Content strategy error: %s", exc)
        print(f"❌ {exc}")
        raise SystemExit(1) from exc
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        print(f"❌ Unexpected error: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
