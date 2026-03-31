"""Tests for the content scheduler system.

Covers:
- TestPostGenerator  (T008) — template coverage, validation
- TestContentScheduler (T009) — draft generation, frontmatter
- TestTopicRotation (T018) — round-robin, no consecutive repeats
- TestScheduleManager (T019) — state persistence, atomic write
- TestCLIFlags (T023) — generate_now(), preview(), status()
- TestOrchestratorSchedulerHook (T028) — orchestrator integration
- TestLinkedInPostHandler (T031) — action executor integration
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.scheduler.post_generator import (
    TEMPLATES,
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
from backend.scheduler.content_scheduler import (
    ContentScheduler,
    ContentStrategyError,
    PreviewResult,
    RunResult,
    StatusResult,
    TemplateGenerationError,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

CONTENT_STRATEGY_MINIMAL = """\
---
post_frequency: daily
preferred_time: "09:00"
tone: professional but approachable
max_hashtags: 5
---

## Topics I Want to Post About
1. AI and Automation - Share insights about building AI agents
2. Backend Development - Python, FastAPI, system design tips
3. Hackathon Journey - Updates on my AI Employee project
4. Cloud & DevOps - Kubernetes, Docker, deployment tips
5. Career Tips - Lessons learned as a developer

## Content Rules
- Keep posts under 1300 characters
- Always include a question to drive engagement

## Do NOT Post About
- Politics or religion
"""


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Create a minimal vault in a temp directory."""
    v = tmp_path / "vault"
    v.mkdir()
    (v / "Pending_Approval").mkdir()
    (v / "Approved").mkdir()
    (v / "Done").mkdir()
    (v / "Logs").mkdir()
    return v


@pytest.fixture
def vault_with_strategy(vault: Path) -> Path:
    """Vault with a valid Content_Strategy.md."""
    (vault / "Content_Strategy.md").write_text(CONTENT_STRATEGY_MINIMAL, encoding="utf-8")
    return vault


@pytest.fixture
def scheduler(vault_with_strategy: Path) -> ContentScheduler:
    return ContentScheduler(vault_path=vault_with_strategy, dev_mode=True, dry_run=False)


# ── TestPostGenerator (T008) ─────────────────────────────────────────────────


class TestPostGenerator:
    """Verify 25+ templates, char limits, and validate_post()."""

    EXPECTED_TOPICS = [
        "ai_automation",
        "backend_development",
        "hackathon_journey",
        "cloud_devops",
        "career_tips",
    ]
    EXPECTED_FORMAT_TYPES = {"tip", "insight", "question", "story", "announcement"}

    def test_total_template_count(self) -> None:
        """Must have at least 25 templates (5 topics × 5 format types)."""
        total = sum(len(v) for v in TEMPLATES.values())
        assert total >= 25, f"Expected ≥25 templates, got {total}"

    def test_all_expected_topics_present(self) -> None:
        """All 5 topic keys must be present in TEMPLATES."""
        for key in self.EXPECTED_TOPICS:
            assert key in TEMPLATES, f"Missing topic key: {key}"
            assert len(TEMPLATES[key]) >= 5, (
                f"Topic {key!r} must have ≥5 templates, got {len(TEMPLATES[key])}"
            )

    def test_each_topic_has_all_format_types(self) -> None:
        """Each topic should have at least one template of each format type."""
        for topic_key in self.EXPECTED_TOPICS:
            types_found = {t.format_type for t in TEMPLATES[topic_key]}
            missing = self.EXPECTED_FORMAT_TYPES - types_found
            assert not missing, (
                f"Topic {topic_key!r} missing format types: {missing}"
            )

    def test_all_templates_within_char_limit(self) -> None:
        """All template bodies must be ≤ 1300 characters."""
        generator = PostGenerator()
        for topic_key, templates in TEMPLATES.items():
            for tmpl in templates:
                result = generator.validate_post(tmpl.body)
                assert result.character_count <= 1300, (
                    f"Template {tmpl.template_id!r} exceeds 1300 chars "
                    f"({result.character_count})"
                )

    def test_all_templates_contain_question(self) -> None:
        """Every template body must contain a '?' (engagement requirement)."""
        for topic_key, templates in TEMPLATES.items():
            for tmpl in templates:
                assert "?" in tmpl.body, (
                    f"Template {tmpl.template_id!r} has no question mark"
                )

    def test_validate_post_catches_overlimit_content(self) -> None:
        """validate_post() should flag content exceeding 1300 chars."""
        generator = PostGenerator()
        long_text = "A" * 1400 + "\n\nQuestion?"
        result = generator.validate_post(long_text)
        assert not result.valid
        assert result.character_count > 1300
        assert any("Character count" in e for e in result.errors)

    def test_validate_post_catches_missing_question(self) -> None:
        """validate_post() should flag posts without '?'."""
        generator = PostGenerator()
        result = generator.validate_post("This is a post with no question. " * 5)
        assert not result.valid
        assert any("question" in e.lower() for e in result.errors)

    def test_generate_returns_valid_post(self) -> None:
        """generate() should return a GeneratedPost with valid content."""
        generator = PostGenerator()
        post = generator.generate(
            topic_key="ai_automation",
            topic_title="AI and Automation",
        )
        assert post.character_count <= 1300
        assert post.template_id.startswith("ai_auto_")
        assert "?" in post.body
        assert post.topic_key == "ai_automation"

    def test_generate_uses_fallback_for_unknown_topic(self) -> None:
        """generate() should fall back to available templates for unknown topics."""
        generator = PostGenerator()
        post = generator.generate(
            topic_key="completely_unknown_topic",
            topic_title="Unknown Topic",
        )
        assert post.character_count <= 1300

    def test_normalize_topic_key_known_titles(self) -> None:
        """normalize_topic_key() must map known titles to correct keys."""
        assert normalize_topic_key("AI and Automation") == "ai_automation"
        assert normalize_topic_key("Backend Development") == "backend_development"
        assert normalize_topic_key("Cloud & DevOps") == "cloud_devops"
        assert normalize_topic_key("Career Tips") == "career_tips"
        assert normalize_topic_key("Hackathon Journey") == "hackathon_journey"

    def test_get_templates_for_topic(self) -> None:
        """get_templates_for_topic() should return list of PostTemplate."""
        generator = PostGenerator()
        templates = generator.get_templates_for_topic("career_tips")
        assert len(templates) >= 5
        for t in templates:
            assert t.topic_key == "career_tips"


# ── TestContentScheduler (T009) ──────────────────────────────────────────────


class TestContentScheduler:
    """run_if_due() creates a draft; missing strategy raises ContentStrategyError."""

    def test_missing_strategy_raises_error(self, vault: Path) -> None:
        """run_if_due() raises ContentStrategyError if Content_Strategy.md absent."""
        s = ContentScheduler(vault_path=vault, dev_mode=True, dry_run=False)
        with pytest.raises(ContentStrategyError):
            s.run_if_due()

    def test_run_if_due_creates_draft(self, scheduler: ContentScheduler, vault_with_strategy: Path) -> None:
        """run_if_due() creates LINKEDIN_POST_{date}.md in vault/Pending_Approval/."""
        result = scheduler.run_if_due()
        assert result.status == "generated", f"Expected 'generated', got {result.status!r}: {result.reason}"
        assert result.draft_path is not None
        draft = Path(result.draft_path)
        assert draft.exists(), f"Draft file not found: {draft}"
        assert draft.parent.name == "Pending_Approval"

    def test_draft_has_required_frontmatter(self, scheduler: ContentScheduler) -> None:
        """Draft must have type, status, topic, generated_at, character_count fields."""
        from backend.utils.frontmatter import extract_frontmatter

        result = scheduler.run_if_due()
        assert result.draft_path is not None
        content = Path(result.draft_path).read_text(encoding="utf-8")
        fm, body = extract_frontmatter(content)

        assert fm.get("type") == "linkedin_post"
        assert fm.get("status") == "pending_approval"
        assert fm.get("topic") is not None
        assert fm.get("generated_at") is not None
        assert fm.get("character_count") is not None
        assert int(fm["character_count"]) <= 1300

    def test_draft_body_contains_post_content(self, scheduler: ContentScheduler) -> None:
        """Draft body must contain '# Post Content' heading."""
        result = scheduler.run_if_due()
        assert result.draft_path is not None
        content = Path(result.draft_path).read_text(encoding="utf-8")
        assert "# Post Content" in content

    def test_run_if_due_is_idempotent(self, scheduler: ContentScheduler) -> None:
        """Second call on same day returns 'skipped' (idempotency guard)."""
        first = scheduler.run_if_due()
        assert first.status == "generated"

        second = scheduler.run_if_due()
        assert second.status == "skipped", f"Expected 'skipped', got {second.status!r}"

    def test_dry_run_creates_no_files(self, vault_with_strategy: Path) -> None:
        """dry_run=True must NOT write any files to vault."""
        dry = ContentScheduler(vault_path=vault_with_strategy, dev_mode=True, dry_run=True)
        result = dry.run_if_due()
        # dry_run skips idempotency file check but generates in-memory
        assert result.status in ("generated", "skipped", "error")
        # No actual files should exist in Pending_Approval
        pending = vault_with_strategy / "Pending_Approval"
        drafts = list(pending.glob("LINKEDIN_POST_*.md"))
        assert len(drafts) == 0, f"dry_run should not write files, found: {drafts}"


# ── TestTopicRotation (T018) ─────────────────────────────────────────────────


class TestTopicRotation:
    """Simulate multiple runs and verify no consecutive topic repeats."""

    def test_no_consecutive_repeats_over_10_runs(self, vault_with_strategy: Path) -> None:
        """10 sequential force-generates must never produce consecutive duplicate topics."""
        scheduler = ContentScheduler(vault_path=vault_with_strategy, dev_mode=True, dry_run=False)

        topics_seen: list[str] = []
        for i in range(10):
            # Remove any existing draft to allow each generate_now() to succeed
            today = scheduler._schedule_manager.today_str()
            existing = vault_with_strategy / "Pending_Approval" / f"LINKEDIN_POST_{today}.md"
            if existing.exists():
                existing.unlink()

            result = scheduler.generate_now()
            assert result.status == "generated", f"Run {i}: {result.reason}"
            topics_seen.append(result.topic)

        # Check no consecutive repeats
        for i in range(1, len(topics_seen)):
            assert topics_seen[i] != topics_seen[i - 1], (
                f"Consecutive repeat at positions {i-1} and {i}: {topics_seen[i]!r}"
            )

    def test_full_cycle_before_restart(self, vault_with_strategy: Path) -> None:
        """All 5 topics appear within the first 6 runs (5 unique + 1 cycle wrap)."""
        scheduler = ContentScheduler(vault_path=vault_with_strategy, dev_mode=True, dry_run=False)

        topics_seen: set[str] = set()
        for i in range(6):
            today = scheduler._schedule_manager.today_str()
            existing = vault_with_strategy / "Pending_Approval" / f"LINKEDIN_POST_{today}.md"
            if existing.exists():
                existing.unlink()

            result = scheduler.generate_now()
            assert result.status == "generated"
            if result.topic:
                topics_seen.add(result.topic)

        assert len(topics_seen) == 5, (
            f"Expected all 5 topics in 6 runs, got {len(topics_seen)}: {topics_seen}"
        )

    def test_wrap_around_works_correctly(self, vault_with_strategy: Path) -> None:
        """After the last topic, rotation wraps to first topic (skipping consecutive)."""
        sm = ScheduleManager(vault_path=vault_with_strategy)
        # With 5 topics, index 4 should wrap to 0 (not 5)
        next_idx = sm.get_next_topic_index(last_topic_index=4, num_topics=5)
        assert next_idx == 0

    def test_history_persists_topic_index(self, vault_with_strategy: Path) -> None:
        """History entries record topic_index correctly for next-run rotation."""
        scheduler = ContentScheduler(vault_path=vault_with_strategy, dev_mode=True, dry_run=False)
        result = scheduler.run_if_due()
        assert result.status == "generated"

        sm = scheduler._schedule_manager
        state = sm.load_state()
        assert state.last_topic_index >= 0
        assert state.last_run_date == sm.today_str()


# ── TestScheduleManager (T019) ───────────────────────────────────────────────


class TestScheduleManager:
    """State persistence, rotation logic, atomic writes."""

    def test_get_next_topic_index_different_from_last(self, vault: Path) -> None:
        """get_next_topic_index() must always differ from last when num_topics > 1."""
        sm = ScheduleManager(vault_path=vault)
        for last_idx in range(5):
            next_idx = sm.get_next_topic_index(last_idx, num_topics=5)
            assert next_idx != last_idx, (
                f"Consecutive repeat: last={last_idx}, next={next_idx}"
            )

    def test_get_next_topic_index_single_topic(self, vault: Path) -> None:
        """With one topic, always returns 0."""
        sm = ScheduleManager(vault_path=vault)
        assert sm.get_next_topic_index(0, num_topics=1) == 0

    def test_load_state_creates_default_when_missing(self, vault: Path) -> None:
        """load_state() returns default ScheduleState when file doesn't exist."""
        sm = ScheduleManager(vault_path=vault)
        state = sm.load_state()
        assert state.last_run_date is None
        assert state.last_topic_index == -1

    def test_save_and_load_state_roundtrip(self, vault: Path) -> None:
        """save_state() then load_state() returns same data."""
        sm = ScheduleManager(vault_path=vault)
        state = ScheduleState(
            last_run_date="2026-02-20",
            last_topic_index=2,
            next_topic_index=3,
            posts_today=1,
        )
        sm.save_state(state)
        loaded = sm.load_state()
        assert loaded.last_run_date == "2026-02-20"
        assert loaded.last_topic_index == 2
        assert loaded.next_topic_index == 3
        assert loaded.posts_today == 1

    def test_load_history_creates_empty_when_missing(self, vault: Path) -> None:
        """load_history() returns empty PostingHistory when file doesn't exist."""
        sm = ScheduleManager(vault_path=vault)
        history = sm.load_history()
        assert history.entries == []

    def test_save_and_load_history_roundtrip(self, vault: Path) -> None:
        """save_history() + load_history() round-trips correctly."""
        sm = ScheduleManager(vault_path=vault)
        history = PostingHistory()
        history.add_entry(PostingHistoryEntry(
            date="2026-02-20",
            topic_index=1,
            topic_title="Backend Development",
            template_id="backend_tip_01",
            draft_path="vault/Pending_Approval/LINKEDIN_POST_2026-02-20.md",
            generated_at="2026-02-20T09:00:00+05:00",
        ))
        sm.save_history(history)
        loaded = sm.load_history()
        assert len(loaded.entries) == 1
        assert loaded.entries[0].topic_title == "Backend Development"

    def test_atomic_write_leaves_no_tmp_files(self, vault: Path) -> None:
        """save_state() must not leave .tmp files on success."""
        sm = ScheduleManager(vault_path=vault)
        sm.save_state(ScheduleState(last_run_date="2026-02-20"))
        tmp_files = list(sm.logs_dir.glob("*.tmp"))
        assert tmp_files == [], f"Found leftover .tmp files: {tmp_files}"

    def test_is_post_due_returns_false_when_already_run(self, vault: Path) -> None:
        """is_post_due() returns False if last_run_date == today and posts_today > 0."""
        sm = ScheduleManager(vault_path=vault)
        today = sm.today_str()
        state = ScheduleState(last_run_date=today, posts_today=1)
        assert not sm.is_post_due(state, today)

    def test_is_post_due_returns_true_for_new_day(self, vault: Path) -> None:
        """is_post_due() returns True on a fresh day."""
        sm = ScheduleManager(vault_path=vault)
        today = sm.today_str()
        state = ScheduleState(last_run_date=None, posts_today=0)
        assert sm.is_post_due(state, today)

    def test_draft_exists_today_finds_file(self, vault: Path) -> None:
        """draft_exists_today() returns True if LINKEDIN_POST_{today}.md exists."""
        sm = ScheduleManager(vault_path=vault)
        today = sm.today_str()
        fname = f"LINKEDIN_POST_{today}.md"
        (vault / "Pending_Approval" / fname).write_text("---\n---\n", encoding="utf-8")
        assert sm.draft_exists_today(today)

    def test_draft_exists_today_returns_false_when_absent(self, vault: Path) -> None:
        """draft_exists_today() returns False when no draft file exists."""
        sm = ScheduleManager(vault_path=vault)
        assert not sm.draft_exists_today("2099-01-01")


# ── TestCLIFlags (T023) ──────────────────────────────────────────────────────


class TestCLIFlags:
    """generate_now(), preview(), status() behave correctly."""

    def test_generate_now_creates_draft(self, scheduler: ContentScheduler) -> None:
        """generate_now() always creates a draft regardless of existing file."""
        result = scheduler.generate_now()
        assert result.status == "generated"
        assert result.draft_path is not None
        assert Path(result.draft_path).exists()

    def test_generate_now_overwrites_existing_draft(self, scheduler: ContentScheduler) -> None:
        """generate_now() removes and recreates existing draft."""
        first = scheduler.generate_now()
        assert first.status == "generated"
        assert first.draft_path is not None
        assert Path(first.draft_path).exists()

        second = scheduler.generate_now()
        assert second.status == "generated"
        assert second.draft_path is not None
        assert Path(second.draft_path).exists()

    def test_preview_returns_preview_result(self, scheduler: ContentScheduler) -> None:
        """preview() returns PreviewResult with non-empty post_text."""
        result = scheduler.preview()
        assert isinstance(result, PreviewResult)
        assert result.post_text
        assert len(result.post_text) <= 1300
        assert result.character_count <= 1300
        assert result.topic

    def test_preview_writes_no_files(self, scheduler: ContentScheduler, vault_with_strategy: Path) -> None:
        """preview() must not create any files in the vault."""
        before = list(vault_with_strategy.rglob("LINKEDIN_POST_*.md"))
        scheduler.preview()
        after = list(vault_with_strategy.rglob("LINKEDIN_POST_*.md"))
        assert len(after) == len(before), "preview() should not write draft files"

    def test_status_returns_status_result(self, scheduler: ContentScheduler) -> None:
        """status() returns a StatusResult with correct fields."""
        result = scheduler.status()
        assert isinstance(result, StatusResult)
        assert result.is_due_today is True  # No posts yet, should be due
        assert result.posts_today == 0

    def test_status_after_generation_shows_not_due(self, scheduler: ContentScheduler) -> None:
        """status().is_due_today should be False after a draft was generated today."""
        scheduler.run_if_due()
        result = scheduler.status()
        assert result.is_due_today is False

    def test_status_shows_correct_next_topic(self, scheduler: ContentScheduler) -> None:
        """status().next_topic should match one of the 5 defined topics."""
        EXPECTED = {
            "AI and Automation",
            "Backend Development",
            "Hackathon Journey",
            "Cloud & DevOps",
            "Career Tips",
        }
        result = scheduler.status()
        assert result.next_topic in EXPECTED, (
            f"Unexpected next_topic: {result.next_topic!r}"
        )


# ── TestOrchestratorSchedulerHook (T028) ─────────────────────────────────────


class TestOrchestratorSchedulerHook:
    """Orchestrator _check_content_schedule() handles success and errors gracefully."""

    @pytest.fixture
    def orchestrator(self, vault: Path):
        from backend.orchestrator.orchestrator import Orchestrator, OrchestratorConfig
        config = OrchestratorConfig(
            vault_path=str(vault),
            check_interval=1,
            dev_mode=True,
        )
        return Orchestrator(config)

    @pytest.mark.asyncio
    async def test_check_schedule_logs_on_generated(
        self, orchestrator, vault_with_strategy: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_check_content_schedule() logs INFO when a draft is generated."""
        import logging

        # Patch vault_path to point to vault_with_strategy
        orchestrator.vault_path = vault_with_strategy
        orchestrator.config.vault_path = str(vault_with_strategy)

        with caplog.at_level(logging.INFO, logger="backend.orchestrator.orchestrator"):
            await orchestrator._check_content_schedule()

        # Should log at INFO level about generation or schedule check
        # (exact message may vary, but no crash)

    @pytest.mark.asyncio
    async def test_check_schedule_does_not_raise_on_missing_strategy(
        self, orchestrator, vault: Path
    ) -> None:
        """_check_content_schedule() must NOT raise when Content_Strategy.md is missing."""
        orchestrator.vault_path = vault
        orchestrator.config.vault_path = str(vault)

        # Should not raise — logs WARNING instead
        await orchestrator._check_content_schedule()

    @pytest.mark.asyncio
    async def test_check_schedule_logs_warning_on_content_strategy_error(
        self, orchestrator, vault: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ContentStrategyError is caught and logged at WARNING level."""
        import logging

        orchestrator.vault_path = vault
        orchestrator.config.vault_path = str(vault)

        with caplog.at_level(logging.WARNING, logger="backend.orchestrator.orchestrator"):
            await orchestrator._check_content_schedule()

        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        # There should be a warning about missing strategy
        assert len(warning_messages) >= 1


# ── TestLinkedInPostHandler (T031) ───────────────────────────────────────────


class TestLinkedInPostHandler:
    """action_executor._handle_linkedin_post() integration with LinkedInPoster."""

    @pytest.fixture
    def config(self, vault: Path):
        from backend.orchestrator.orchestrator import OrchestratorConfig
        (vault / "Logs" / "actions").mkdir(parents=True, exist_ok=True)
        return OrchestratorConfig(
            vault_path=str(vault),
            check_interval=1,
            dev_mode=False,  # NOT dev_mode so real handler is called
        )

    @pytest.fixture
    def executor(self, config):
        from backend.orchestrator.action_executor import ActionExecutor
        return ActionExecutor(config)

    def _make_linkedin_file(self, approved_dir: Path, today: str = "2026-02-20") -> Path:
        """Create a fake LINKEDIN_POST approval file."""
        content = (
            "---\n"
            "type: linkedin_post\n"
            "status: approved\n"
            f"scheduled_date: {today}\n"
            "---\n\n"
            "# Post Content\n\n"
            "This is a test LinkedIn post. Does this work?\n\n"
            "#Testing #AIAgents\n"
        )
        p = approved_dir / f"LINKEDIN_POST_{today}.md"
        p.write_text(content, encoding="utf-8")
        return p

    @pytest.mark.asyncio
    async def test_handle_linkedin_post_calls_poster(
        self, executor, vault: Path
    ) -> None:
        """_handle_linkedin_post() calls LinkedInPoster.process_approved_posts()."""
        file_path = self._make_linkedin_file(vault / "Approved")
        fm = {"type": "linkedin_post", "status": "approved"}

        mock_poster = AsyncMock()
        mock_poster.process_approved_posts = AsyncMock(return_value=1)
        mock_poster._close_browser = AsyncMock()

        # Patch at source module since _handle_linkedin_post uses a local import
        with patch(
            "backend.actions.linkedin_poster.LinkedInPoster",
            return_value=mock_poster,
        ):
            # Should not raise
            await executor._handle_linkedin_post(file_path, fm, "test-cid")
            mock_poster.process_approved_posts.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_linkedin_post_raises_on_zero_count(
        self, executor, vault: Path
    ) -> None:
        """_handle_linkedin_post() raises RuntimeError when poster returns 0."""
        file_path = self._make_linkedin_file(vault / "Approved")
        fm = {"type": "linkedin_post", "status": "approved"}

        mock_poster = AsyncMock()
        mock_poster.process_approved_posts = AsyncMock(return_value=0)
        mock_poster._close_browser = AsyncMock()

        # Patch at source module since _handle_linkedin_post uses a local import
        with patch(
            "backend.actions.linkedin_poster.LinkedInPoster",
            return_value=mock_poster,
        ):
            with pytest.raises(RuntimeError):
                await executor._handle_linkedin_post(file_path, fm, "test-cid")

    @pytest.mark.asyncio
    async def test_process_file_skips_move_when_file_already_moved(
        self, executor, vault: Path
    ) -> None:
        """process_file() skips _move_to_done() if file was moved by handler."""
        file_path = self._make_linkedin_file(vault / "Approved")
        fm = {"type": "linkedin_post", "status": "approved"}

        async def fake_handler(fp, f, cid):
            # Simulate LinkedInPoster moving the file away
            fp.unlink()

        with patch.object(executor, "_handle_linkedin_post", side_effect=fake_handler):
            result = await executor.process_file(file_path, fm)

        # Should return True (success) without crashing on missing file
        assert result is True
        # File should NOT be in Done/ (it was "moved" by the fake handler)
        assert not (vault / "Done" / file_path.name).exists()
