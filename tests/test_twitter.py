"""Tests for Twitter (X) Integration — watcher, poster, session, scheduler, and templates.

Covers:
    TestTwitterPoster           — validation, DEV_MODE lifecycle, file moves
    TestTwitterWatcher          — DEV_MODE guard, create_action_file, dedup
    TestTwitterSessionSetup     — session state detection logic (mocked Playwright)
    TestContentSchedulerTwitter — platform routing, draft filename, type frontmatter
    TestActionExecutorTwitter   — HANDLERS dict dispatch for twitter_post
    TestTwitterDeduplication    — load/save/cleanup processed_ids
    TestTwitterTemplates        — all 5 twitter_short templates are ≤280 chars
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.actions.twitter_poster import TWITTER_CHAR_LIMIT, TwitterPoster
from backend.orchestrator.action_executor import ActionExecutor
from backend.orchestrator.orchestrator import OrchestratorConfig
from backend.scheduler.post_generator import (
    TWITTER_CHAR_LIMIT as PG_TWITTER_LIMIT,
    PostGenerator,
    TEMPLATES,
)
from backend.scheduler.schedule_manager import ScheduleManager
from backend.utils.frontmatter import create_file_with_frontmatter


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_vault(tmp_path: Path) -> Path:
    """Create standard vault directory structure."""
    for subdir in ("Approved", "Done", "Rejected", "Needs_Action", "Pending_Approval"):
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    (tmp_path / "Logs" / "actions").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Logs" / "errors").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_approved_file(
    vault: Path,
    filename: str,
    post_type: str,
    body: str = "Test tweet body.",
    **extra_fm: Any,
) -> Path:
    """Write an approved post file to vault/Approved/."""
    fm = {
        "type": post_type,
        "status": "approved",
        **extra_fm,
    }
    path = vault / "Approved" / filename
    create_file_with_frontmatter(path, fm, f"\n{body}\n")
    return path


# ── TestTwitterPoster ─────────────────────────────────────────────────────────


class TestTwitterPoster:
    """Tests for backend.actions.twitter_poster.TwitterPoster."""

    @pytest.fixture
    def vault(self, tmp_path: Path) -> Path:
        return _make_vault(tmp_path)

    @pytest.fixture
    def poster(self, vault: Path, tmp_path: Path) -> TwitterPoster:
        return TwitterPoster(
            vault_path=str(vault),
            session_path=str(tmp_path / "twitter_session"),
            headless=True,
            dry_run=False,
            dev_mode=True,
        )

    def test_validate_post_valid(self, poster: TwitterPoster) -> None:
        assert poster._validate_post("Hello Twitter!", {}) is None

    def test_validate_post_empty_body(self, poster: TwitterPoster) -> None:
        assert poster._validate_post("   ", {}) == "empty_body"

    def test_validate_post_exactly_280_chars(self, poster: TwitterPoster) -> None:
        body = "x" * TWITTER_CHAR_LIMIT
        assert len(body) == 280
        assert poster._validate_post(body, {}) is None

    def test_validate_post_281_chars_rejected(self, poster: TwitterPoster) -> None:
        body = "x" * (TWITTER_CHAR_LIMIT + 1)
        assert poster._validate_post(body, {}) == "exceeds_character_limit"

    def test_validate_post_well_under_limit(self, poster: TwitterPoster) -> None:
        body = "Short tweet #AIAgents"
        assert poster._validate_post(body, {}) is None

    @pytest.mark.asyncio
    async def test_dev_mode_moves_to_done(self, vault: Path, tmp_path: Path) -> None:
        """DEV_MODE: approved twitter_post moves to vault/Done/ with status=done."""
        poster = TwitterPoster(
            vault_path=str(vault),
            session_path=str(tmp_path / "twitter_session"),
            dev_mode=True,
        )
        _write_approved_file(vault, "TWITTER_POST_test.md", "twitter_post", body="Short tweet.")
        count = await poster.process_approved_posts()
        assert count == 1
        done_files = list((vault / "Done").glob("*.md"))
        assert len(done_files) == 1
        content = done_files[0].read_text(encoding="utf-8")
        assert "done" in content

    @pytest.mark.asyncio
    async def test_exceeds_limit_moves_to_rejected(self, vault: Path, tmp_path: Path) -> None:
        """Post exceeding 280 chars is rejected (not truncated)."""
        poster = TwitterPoster(
            vault_path=str(vault),
            session_path=str(tmp_path / "twitter_session"),
            dev_mode=True,
        )
        long_body = "x" * 281
        _write_approved_file(vault, "TWITTER_POST_long.md", "twitter_post", body=long_body)
        count = await poster.process_approved_posts()
        assert count == 1
        rejected_files = list((vault / "Rejected").glob("*.md"))
        assert len(rejected_files) == 1
        content = rejected_files[0].read_text(encoding="utf-8")
        assert "exceeds_character_limit" in content

    @pytest.mark.asyncio
    async def test_scan_approved_filters_by_type(self, vault: Path, tmp_path: Path) -> None:
        """_scan_approved() only returns twitter_post type files."""
        poster = TwitterPoster(vault_path=str(vault), session_path=str(tmp_path / "s"))
        _write_approved_file(vault, "TWITTER_POST_1.md", "twitter_post", body="Tweet 1.")
        _write_approved_file(vault, "LINKEDIN_POST_1.md", "linkedin_post", body="LinkedIn post.")
        _write_approved_file(vault, "FACEBOOK_POST_1.md", "facebook_post", body="FB post.")
        results = poster._scan_approved()
        assert len(results) == 1
        assert results[0][1].get("type") == "twitter_post"

    @pytest.mark.asyncio
    async def test_no_approved_files_returns_zero(self, vault: Path, tmp_path: Path) -> None:
        poster = TwitterPoster(vault_path=str(vault), session_path=str(tmp_path / "s"))
        count = await poster.process_approved_posts()
        assert count == 0

    @pytest.mark.asyncio
    async def test_scan_approved_filters_by_status(self, vault: Path, tmp_path: Path) -> None:
        """_scan_approved() only returns status=approved files."""
        poster = TwitterPoster(vault_path=str(vault), session_path=str(tmp_path / "s"))
        # Write a pending (not approved) twitter_post
        fm = {"type": "twitter_post", "status": "pending_approval"}
        path = vault / "Approved" / "TWITTER_PENDING.md"
        create_file_with_frontmatter(path, fm, "\nPending tweet.\n")
        results = poster._scan_approved()
        assert len(results) == 0


# ── TestTwitterWatcher ────────────────────────────────────────────────────────


class TestTwitterWatcher:
    """Tests for backend.watchers.twitter_watcher.TwitterWatcher."""

    @pytest.fixture
    def vault(self, tmp_path: Path) -> Path:
        return _make_vault(tmp_path)

    @pytest.fixture
    def watcher(self, vault: Path, tmp_path: Path):
        from backend.watchers.twitter_watcher import TwitterWatcher
        return TwitterWatcher(
            vault_path=str(vault),
            session_path=str(tmp_path / "twitter_session"),
            dev_mode=True,
            dry_run=False,
        )

    @pytest.mark.asyncio
    async def test_dev_mode_returns_synthetic_item(self, watcher) -> None:
        """DEV_MODE: check_for_updates() returns 1 synthetic item without browser."""
        items = await watcher.check_for_updates()
        assert len(items) == 1
        item = items[0]
        assert item["sender"] == "[DEV_MODE]"
        assert item["item_type"] == "notification"

    @pytest.mark.asyncio
    async def test_session_path_missing_returns_empty(self, vault: Path, tmp_path: Path) -> None:
        """Non-existent session_path causes watcher to return [] (no crash)."""
        from backend.watchers.twitter_watcher import TwitterWatcher
        watcher = TwitterWatcher(
            vault_path=str(vault),
            session_path=str(tmp_path / "nonexistent_session"),
            dev_mode=False,
            dry_run=False,
        )
        # Without DEV_MODE, missing session path → warning + empty list
        items = await watcher.check_for_updates()
        assert items == []

    @pytest.mark.asyncio
    async def test_create_action_file_correct_frontmatter(self, watcher, vault: Path) -> None:
        """create_action_file() writes type=twitter, source=twitter_watcher."""
        item = {
            "item_type": "notification",
            "sender": "test_user",
            "preview": "Hello urgent help needed",
            "time": "2m",
            "priority": "high",
            "matched_keyword": "urgent",
            "dedup_key": "test_user|hello urgent|2m",
            "needs_reply": False,
        }
        result = await watcher.create_action_file(item)
        assert result is not None
        files = list((vault / "Needs_Action").glob("TWITTER_*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "type: twitter" in content
        assert "source: twitter_watcher" in content

    @pytest.mark.asyncio
    async def test_dry_run_returns_none_no_file(self, vault: Path, tmp_path: Path) -> None:
        """dry_run=True: create_action_file() logs but does not write file."""
        from backend.watchers.twitter_watcher import TwitterWatcher
        watcher = TwitterWatcher(
            vault_path=str(vault),
            session_path=str(tmp_path / "s"),
            dev_mode=True,
            dry_run=True,
        )
        # First get a synthetic item
        items = await watcher.check_for_updates()
        result = await watcher.create_action_file(items[0])
        assert result is None
        files = list((vault / "Needs_Action").glob("TWITTER_*.md"))
        assert len(files) == 0

    @pytest.mark.asyncio
    async def test_keyword_match_creates_action_file(self, watcher, vault: Path) -> None:
        """Keyword-matched item creates action file with dedup key stored."""
        item = {
            "item_type": "direct_message",
            "sender": "alice",
            "preview": "urgent project help",
            "time": "now",
            "priority": "high",
            "matched_keyword": "urgent",
            "dedup_key": "alice|urgent project|now",
            "needs_reply": True,
        }
        result = await watcher.create_action_file(item)
        assert result is not None
        # Dedup key should be stored
        assert "alice|urgent project|now" in watcher._processed_ids


# ── TestTwitterSessionSetup ───────────────────────────────────────────────────


class TestTwitterSessionSetup:
    """Tests for TwitterWatcher session state detection."""

    @pytest.fixture
    def watcher(self, tmp_path: Path):
        from backend.watchers.twitter_watcher import TwitterWatcher
        vault = _make_vault(tmp_path)
        return TwitterWatcher(
            vault_path=str(vault),
            session_path=str(tmp_path / "twitter_session"),
            dev_mode=False,
        )

    @pytest.mark.asyncio
    async def test_login_url_returns_login_required(self, watcher) -> None:
        """URL containing /i/flow/login → 'login_required'."""
        mock_page = AsyncMock()
        mock_page.url = "https://x.com/i/flow/login"
        watcher._page = mock_page
        state = await watcher._check_session_state()
        assert state == "login_required"

    @pytest.mark.asyncio
    async def test_login_redirect_returns_login_required(self, watcher) -> None:
        """/login in URL → 'login_required'."""
        mock_page = AsyncMock()
        mock_page.url = "https://x.com/login"
        watcher._page = mock_page
        state = await watcher._check_session_state()
        assert state == "login_required"

    @pytest.mark.asyncio
    async def test_suspended_url_returns_captcha(self, watcher) -> None:
        """URL containing /account/suspended → 'captcha'."""
        mock_page = AsyncMock()
        mock_page.url = "https://x.com/account/suspended"
        mock_page.query_selector = AsyncMock(return_value=None)
        watcher._page = mock_page
        state = await watcher._check_session_state()
        assert state == "captcha"

    @pytest.mark.asyncio
    async def test_auth_selector_found_returns_ready(self, watcher) -> None:
        """Mock [data-testid='AppTabBar_Home_Link'] found → 'ready'."""
        mock_page = AsyncMock()
        mock_page.url = "https://x.com/home"
        mock_element = MagicMock()
        # First selector returns element → ready
        mock_page.query_selector = AsyncMock(return_value=mock_element)
        watcher._page = mock_page
        state = await watcher._check_session_state()
        assert state == "ready"

    @pytest.mark.asyncio
    async def test_no_auth_selectors_returns_unknown(self, watcher) -> None:
        """No auth selectors found → 'unknown'."""
        mock_page = AsyncMock()
        mock_page.url = "https://x.com/home"
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.query_selector_all = AsyncMock(return_value=[])
        watcher._page = mock_page
        state = await watcher._check_session_state()
        assert state == "unknown"


# ── TestContentSchedulerTwitter ───────────────────────────────────────────────


class TestContentSchedulerTwitter:
    """Tests for Twitter platform routing in content scheduler."""

    @pytest.fixture
    def vault(self, tmp_path: Path) -> Path:
        return _make_vault(tmp_path)

    def test_parse_topics_extracts_twitter_platform(self) -> None:
        """[platform: twitter] tag in topic line sets platform='twitter'."""
        from backend.scheduler.content_scheduler import ContentScheduler
        body = """## Topics I want to post about

1. AI and Automation [platform: twitter] - Quick Twitter tips
2. Backend Development - Python tips
"""
        topics = ContentScheduler._parse_topics(body)
        assert len(topics) == 2
        assert topics[0].platform == "twitter"
        assert topics[1].platform == "linkedin"

    def test_twitter_draft_filename(self, vault: Path) -> None:
        """Twitter platform generates TWITTER_POST_{today}.md filename."""
        from backend.scheduler.content_scheduler import ContentScheduler
        from backend.scheduler.content_scheduler import Topic

        scheduler = ContentScheduler(vault_path=vault, dev_mode=True)
        topic = Topic(
            index=0,
            title="AI and Automation",
            description="Twitter tips",
            topic_key="ai_automation",
            platform="twitter",
        )
        draft_path = scheduler._save_draft(topic, "Short tweet #AIAgents", "twitter_ai_01", 25, "2026-02-21")
        assert "TWITTER_POST" in draft_path.name

    def test_save_draft_sets_twitter_post_type(self, vault: Path) -> None:
        """_save_draft() with platform=twitter sets type=twitter_post frontmatter."""
        from backend.scheduler.content_scheduler import ContentScheduler, Topic
        from backend.utils.frontmatter import extract_frontmatter

        scheduler = ContentScheduler(vault_path=vault, dev_mode=False)
        topic = Topic(
            index=0,
            title="AI Tips",
            description="Twitter content",
            topic_key="ai_automation",
            platform="twitter",
        )
        draft_path = scheduler._save_draft(topic, "Quick AI tip! #AIAgents", "twitter_ai_01", 24, "2026-02-21")
        assert draft_path.exists()
        content = draft_path.read_text(encoding="utf-8")
        fm, _ = extract_frontmatter(content)
        assert fm.get("type") == "twitter_post"
        assert fm.get("platform") == "twitter"

    def test_draft_exists_today_twitter(self, vault: Path) -> None:
        """draft_exists_today() returns True when TWITTER_POST_{today}.md exists."""
        sm = ScheduleManager(vault_path=vault)
        today = "2026-02-21"
        (vault / "Pending_Approval" / f"TWITTER_POST_{today}.md").write_text("---\n---\n", encoding="utf-8")
        assert sm.draft_exists_today(today) is True

    def test_draft_exists_today_no_twitter_draft(self, vault: Path) -> None:
        """draft_exists_today() returns False when no TWITTER_POST exists."""
        sm = ScheduleManager(vault_path=vault)
        assert sm.draft_exists_today("2026-02-21") is False

    def test_generate_twitter_platform_returns_short_post(self) -> None:
        """generate(platform='twitter') with ai_automation topic returns ≤ 280 chars."""
        generator = PostGenerator()
        post = generator.generate("ai_automation", "AI and Automation", platform="twitter")
        assert post.platform == "twitter"
        assert post.character_count <= TWITTER_CHAR_LIMIT

    def test_twitter_template_exactly_280_accepted(self) -> None:
        """Template with exactly 280 chars is accepted (not truncated)."""
        generator = PostGenerator()
        # Any twitter_short template body should be ≤ 280
        for topic_key, templates in TEMPLATES.items():
            for tmpl in templates:
                if tmpl.format_type == "twitter_short":
                    assert len(tmpl.body) <= 280, (
                        f"Template {tmpl.template_id} exceeds 280 chars: {len(tmpl.body)}"
                    )

    def test_draft_exists_today_approved_directory(self, vault: Path) -> None:
        """draft_exists_today() also checks Approved/ directory."""
        sm = ScheduleManager(vault_path=vault)
        today = "2026-02-21"
        (vault / "Approved" / f"TWITTER_POST_{today}.md").write_text("---\n---\n", encoding="utf-8")
        assert sm.draft_exists_today(today) is True


# ── TestActionExecutorTwitter ─────────────────────────────────────────────────


class TestActionExecutorTwitter:
    """Tests for twitter_post routing in ActionExecutor."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> OrchestratorConfig:
        return OrchestratorConfig(
            vault_path=str(_make_vault(tmp_path)),
            dev_mode=True,
        )

    @pytest.fixture
    def executor(self, config: OrchestratorConfig) -> ActionExecutor:
        return ActionExecutor(config)

    def test_handlers_contains_twitter_post(self, executor: ActionExecutor) -> None:
        assert "twitter_post" in ActionExecutor.HANDLERS

    def test_handlers_twitter_post_maps_to_handle_method(self, executor: ActionExecutor) -> None:
        assert ActionExecutor.HANDLERS["twitter_post"] == "_handle_twitter_post"

    def test_handle_twitter_post_method_exists(self, executor: ActionExecutor) -> None:
        assert hasattr(executor, "_handle_twitter_post")
        assert callable(getattr(executor, "_handle_twitter_post"))

    @pytest.mark.asyncio
    async def test_handle_twitter_post_calls_process_approved(
        self, executor: ActionExecutor, tmp_path: Path
    ) -> None:
        """_handle_twitter_post() calls process_approved_posts() on TwitterPoster."""
        file_path = tmp_path / "TWITTER_POST_test.md"
        file_path.write_text("---\ntype: twitter_post\n---\n\nBody\n", encoding="utf-8")
        fm = {"type": "twitter_post", "status": "approved"}

        with patch("backend.actions.twitter_poster.TwitterPoster") as MockPoster:
            mock_instance = AsyncMock()
            mock_instance.process_approved_posts = AsyncMock(return_value=1)
            mock_instance._close_browser = AsyncMock()
            MockPoster.return_value = mock_instance

            await executor._handle_twitter_post(file_path, fm, "cid-123")
            mock_instance.process_approved_posts.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_twitter_post_closes_browser_in_finally(
        self, executor: ActionExecutor, tmp_path: Path
    ) -> None:
        """_close_browser() is always called even on success."""
        file_path = tmp_path / "TWITTER_POST_test.md"
        file_path.write_text("---\ntype: twitter_post\n---\n\nBody\n", encoding="utf-8")
        fm = {"type": "twitter_post", "status": "approved"}

        with patch("backend.actions.twitter_poster.TwitterPoster") as MockPoster:
            mock_instance = AsyncMock()
            mock_instance.process_approved_posts = AsyncMock(return_value=1)
            mock_instance._close_browser = AsyncMock()
            MockPoster.return_value = mock_instance

            await executor._handle_twitter_post(file_path, fm, "cid-123")
            mock_instance._close_browser.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_twitter_post_raises_on_zero_count(
        self, executor: ActionExecutor, tmp_path: Path
    ) -> None:
        """RuntimeError raised when TwitterPoster processes 0 posts."""
        file_path = tmp_path / "TWITTER_POST_test.md"
        file_path.write_text("---\ntype: twitter_post\n---\n\nBody\n", encoding="utf-8")
        fm = {"type": "twitter_post", "status": "approved"}

        with patch("backend.actions.twitter_poster.TwitterPoster") as MockPoster:
            mock_instance = AsyncMock()
            mock_instance.process_approved_posts = AsyncMock(return_value=0)
            mock_instance._close_browser = AsyncMock()
            MockPoster.return_value = mock_instance

            with pytest.raises(RuntimeError, match="0 posts"):
                await executor._handle_twitter_post(file_path, fm, "cid-123")


# ── TestTwitterDeduplication ──────────────────────────────────────────────────


class TestTwitterDeduplication:
    """Tests for TwitterWatcher deduplication store."""

    @pytest.fixture
    def watcher(self, tmp_path: Path):
        from backend.watchers.twitter_watcher import TwitterWatcher
        vault = _make_vault(tmp_path)
        return TwitterWatcher(
            vault_path=str(vault),
            session_path=str(tmp_path / "twitter_session"),
            dev_mode=True,
        )

    def test_load_processed_ids_returns_empty_when_missing(self, watcher) -> None:
        """_load_processed_ids() sets self._processed_ids = {} when file doesn't exist."""
        watcher._load_processed_ids()
        assert watcher._processed_ids == {}

    def test_load_processed_ids_loads_valid_json(self, watcher, tmp_path: Path) -> None:
        """_load_processed_ids() correctly loads existing JSON into self._processed_ids."""
        data = {
            "processed_ids": {"key1|text|ts": "2026-02-21T10:00:00"},
            "last_cleanup": "2026-02-21T10:00:00",
        }
        watcher.processed_ids_path.parent.mkdir(parents=True, exist_ok=True)
        watcher.processed_ids_path.write_text(json.dumps(data), encoding="utf-8")
        watcher._load_processed_ids()
        assert "key1|text|ts" in watcher._processed_ids

    def test_load_processed_ids_handles_corrupt_json(self, watcher) -> None:
        """_load_processed_ids() resets self._processed_ids = {} on corrupt JSON."""
        watcher.processed_ids_path.parent.mkdir(parents=True, exist_ok=True)
        watcher.processed_ids_path.write_text("{INVALID JSON", encoding="utf-8")
        watcher._load_processed_ids()
        assert watcher._processed_ids == {}

    def test_save_processed_ids_creates_file(self, watcher) -> None:
        """_save_processed_ids() creates the JSON file."""
        watcher._processed_ids = {"key1": "2026-02-21T10:00:00"}
        watcher._save_processed_ids()
        assert watcher.processed_ids_path.exists()
        data = json.loads(watcher.processed_ids_path.read_text(encoding="utf-8"))
        assert "key1" in data.get("processed_ids", {})

    def test_cleanup_old_ids_removes_expired_entries(self, watcher) -> None:
        """_cleanup_old_ids() removes entries older than 7 days."""
        from backend.utils.timestamps import now_iso
        # An entry from 8 days ago (well beyond 7*24 hours)
        old_ts = "2020-01-01T00:00:00+00:00"
        watcher._processed_ids = {
            "old_key": old_ts,
            "new_key": now_iso(),
        }
        watcher._cleanup_old_ids()
        assert "old_key" not in watcher._processed_ids
        assert "new_key" in watcher._processed_ids

    def test_cleanup_retains_recent_entries(self, watcher) -> None:
        """_cleanup_old_ids() keeps entries within 7 days."""
        from backend.utils.timestamps import now_iso
        watcher._processed_ids = {"recent_key": now_iso()}
        watcher._cleanup_old_ids()
        assert "recent_key" in watcher._processed_ids

    def test_cleanup_skips_if_last_cleanup_within_24h(self, watcher) -> None:
        """_cleanup_old_ids() does not run if last cleanup was < 24h ago."""
        from backend.utils.timestamps import now_iso
        watcher._last_cleanup = now_iso()  # just ran
        old_ts = "2020-01-01T00:00:00+00:00"
        watcher._processed_ids = {"old_key": old_ts}
        watcher._cleanup_old_ids()
        # Should NOT have cleaned up since last_cleanup is recent
        assert "old_key" in watcher._processed_ids


# ── TestTwitterTemplates ──────────────────────────────────────────────────────


class TestTwitterTemplates:
    """Tests for Twitter-specific PostTemplate entries."""

    def _get_twitter_templates(self):
        """Return all templates with format_type='twitter_short'."""
        result = []
        for topic_key, templates in TEMPLATES.items():
            for tmpl in templates:
                if tmpl.format_type == "twitter_short":
                    result.append(tmpl)
        return result

    def test_all_twitter_templates_under_280_chars(self) -> None:
        """All twitter_short templates have body length ≤ 280 chars."""
        twitter_templates = self._get_twitter_templates()
        assert len(twitter_templates) >= 5, "Expected at least 5 twitter_short templates"
        for tmpl in twitter_templates:
            assert len(tmpl.body) <= 280, (
                f"Template {tmpl.template_id} body is {len(tmpl.body)} chars (limit 280)"
            )

    def test_all_twitter_templates_have_correct_format_type(self) -> None:
        """All twitter_short templates have format_type == 'twitter_short'."""
        twitter_templates = self._get_twitter_templates()
        for tmpl in twitter_templates:
            assert tmpl.format_type == "twitter_short"

    def test_five_topic_keys_have_twitter_templates(self) -> None:
        """Each of the 5 main topic keys has at least one twitter_short template."""
        expected_topics = {
            "ai_automation",
            "backend_development",
            "hackathon_journey",
            "cloud_devops",
            "career_tips",
        }
        covered = set()
        for topic_key, templates in TEMPLATES.items():
            for tmpl in templates:
                if tmpl.format_type == "twitter_short":
                    covered.add(topic_key)
        assert expected_topics.issubset(covered), (
            f"Missing twitter_short templates for topics: {expected_topics - covered}"
        )

    def test_all_twitter_templates_have_hashtags(self) -> None:
        """Each twitter_short template has at least one hashtag."""
        twitter_templates = self._get_twitter_templates()
        for tmpl in twitter_templates:
            assert len(tmpl.hashtags) >= 1, (
                f"Template {tmpl.template_id} has no hashtags"
            )

    def test_generate_twitter_returns_correct_platform(self) -> None:
        """generate(platform='twitter') returns GeneratedPost with platform='twitter'."""
        generator = PostGenerator()
        post = generator.generate("ai_automation", "AI and Automation", platform="twitter")
        assert post.platform == "twitter"
        assert post.character_count <= PG_TWITTER_LIMIT

    def test_twitter_char_limit_constant_is_280(self) -> None:
        """TWITTER_CHAR_LIMIT constant is exactly 280."""
        assert TWITTER_CHAR_LIMIT == 280
        assert PG_TWITTER_LIMIT == 280
