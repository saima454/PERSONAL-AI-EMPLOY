"""Tests for Meta Social Integration — Facebook & Instagram watchers, posters, and routing.

Covers:
    TestFacebookPoster       — validation, DEV_MODE lifecycle, file moves
    TestInstagramPoster      — 2200-char limit, DEV_MODE lifecycle, file moves
    TestFacebookWatcher      — DEV_MODE guard, create_action_file, dedup
    TestInstagramWatcher     — DEV_MODE guard, create_action_file, dedup
    TestContentSchedulerPlatform — platform routing in PostGenerator + scheduler
    TestActionExecutorMeta   — HANDLERS dict dispatch for facebook_post/instagram_post
    TestMetaSessionSetup     — session state detection logic (mocked Playwright)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.actions.facebook_poster import FACEBOOK_CHAR_LIMIT, FacebookPoster
from backend.actions.instagram_poster import INSTAGRAM_CHAR_LIMIT, InstagramPoster
from backend.orchestrator.action_executor import ActionExecutor
from backend.orchestrator.orchestrator import OrchestratorConfig
from backend.scheduler.post_generator import (
    INSTAGRAM_CHAR_LIMIT as PG_INSTAGRAM_LIMIT,
    PostGenerator,
)
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
    body: str = "Test post body.",
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


# ── TestFacebookPoster ────────────────────────────────────────────────────────


class TestFacebookPoster:
    """Tests for backend.actions.facebook_poster.FacebookPoster."""

    @pytest.fixture
    def vault(self, tmp_path: Path) -> Path:
        return _make_vault(tmp_path)

    @pytest.fixture
    def poster(self, vault: Path, tmp_path: Path) -> FacebookPoster:
        return FacebookPoster(
            vault_path=str(vault),
            session_path=str(tmp_path / "meta_session"),
            headless=True,
            dry_run=False,
            dev_mode=True,
        )

    def test_validate_post_valid(self, poster: FacebookPoster) -> None:
        assert poster._validate_post("Hello world.", {}) is None

    def test_validate_post_empty_body(self, poster: FacebookPoster) -> None:
        assert poster._validate_post("   ", {}) == "empty_body"

    def test_validate_post_char_limit_exceeded(self, poster: FacebookPoster) -> None:
        body = "x" * (FACEBOOK_CHAR_LIMIT + 1)
        assert poster._validate_post(body, {}) == "character_count_exceeded"

    def test_validate_post_at_char_limit(self, poster: FacebookPoster) -> None:
        body = "x" * FACEBOOK_CHAR_LIMIT
        assert poster._validate_post(body, {}) is None

    def test_validate_post_missing_image(self, poster: FacebookPoster, tmp_path: Path) -> None:
        result = poster._validate_post("Body text.", {"image_path": str(tmp_path / "nonexistent.jpg")})
        assert result == "image_file_not_found"

    def test_validate_post_existing_image(self, poster: FacebookPoster, tmp_path: Path) -> None:
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"fake-image-data")
        assert poster._validate_post("Body text.", {"image_path": str(img)}) is None

    @pytest.mark.asyncio
    async def test_dev_mode_moves_to_done(self, poster: FacebookPoster, vault: Path) -> None:
        """In DEV_MODE, approved post is logged and moved to Done/."""
        _write_approved_file(vault, "FACEBOOK_POST_test.md", "facebook_post", "My FB post.")
        count = await poster.process_approved_posts()
        assert count == 1
        assert (vault / "Done" / "FACEBOOK_POST_test.md").exists()
        assert not (vault / "Approved" / "FACEBOOK_POST_test.md").exists()

    @pytest.mark.asyncio
    async def test_dev_mode_done_file_has_status(self, poster: FacebookPoster, vault: Path) -> None:
        """Done file should have status: done after DEV_MODE processing."""
        _write_approved_file(vault, "FACEBOOK_POST_test2.md", "facebook_post", "Post body.")
        await poster.process_approved_posts()
        done_file = vault / "Done" / "FACEBOOK_POST_test2.md"
        content = done_file.read_text(encoding="utf-8")
        assert "status: done" in content

    @pytest.mark.asyncio
    async def test_invalid_post_moves_to_rejected(self, poster: FacebookPoster, vault: Path) -> None:
        """Empty body should move file to Rejected/."""
        _write_approved_file(vault, "FACEBOOK_POST_bad.md", "facebook_post", "   ")
        count = await poster.process_approved_posts()
        assert count == 1
        assert (vault / "Rejected" / "FACEBOOK_POST_bad.md").exists()

    @pytest.mark.asyncio
    async def test_skips_non_facebook_type(self, poster: FacebookPoster, vault: Path) -> None:
        """Files with wrong type should not be processed."""
        _write_approved_file(vault, "LINKEDIN_POST_test.md", "linkedin_post", "LinkedIn post.")
        count = await poster.process_approved_posts()
        assert count == 0
        assert (vault / "Approved" / "LINKEDIN_POST_test.md").exists()

    @pytest.mark.asyncio
    async def test_no_approved_dir_returns_zero(self, tmp_path: Path) -> None:
        """When Approved/ doesn't exist, return 0."""
        poster = FacebookPoster(vault_path=str(tmp_path), dev_mode=True)
        count = await poster.process_approved_posts()
        assert count == 0

    @pytest.mark.asyncio
    async def test_max_posts_per_run_respected(self, poster: FacebookPoster, vault: Path) -> None:
        """Should process at most MAX_POSTS_PER_RUN files per call."""
        from backend.actions.facebook_poster import MAX_POSTS_PER_RUN
        for i in range(MAX_POSTS_PER_RUN + 2):
            _write_approved_file(vault, f"FACEBOOK_POST_{i:03d}.md", "facebook_post", f"Post {i}")
        count = await poster.process_approved_posts()
        assert count == MAX_POSTS_PER_RUN

    @pytest.mark.asyncio
    async def test_close_browser_is_safe_when_not_launched(self, poster: FacebookPoster) -> None:
        """_close_browser() should not raise if browser was never launched."""
        await poster._close_browser()  # no exception expected


# ── TestInstagramPoster ───────────────────────────────────────────────────────


class TestInstagramPoster:
    """Tests for backend.actions.instagram_poster.InstagramPoster."""

    @pytest.fixture
    def vault(self, tmp_path: Path) -> Path:
        return _make_vault(tmp_path)

    @pytest.fixture
    def poster(self, vault: Path, tmp_path: Path) -> InstagramPoster:
        return InstagramPoster(
            vault_path=str(vault),
            session_path=str(tmp_path / "meta_session"),
            headless=True,
            dry_run=False,
            dev_mode=True,
        )

    def test_char_limit_constant(self) -> None:
        assert INSTAGRAM_CHAR_LIMIT == 2_200

    def test_validate_post_valid(self, poster: InstagramPoster) -> None:
        assert poster._validate_post("Hello world!", {}) is None

    def test_validate_post_empty_body(self, poster: InstagramPoster) -> None:
        assert poster._validate_post("", {}) == "empty_body"

    def test_validate_post_at_limit(self, poster: InstagramPoster) -> None:
        body = "x" * INSTAGRAM_CHAR_LIMIT
        assert poster._validate_post(body, {}) is None

    def test_validate_post_over_limit(self, poster: InstagramPoster) -> None:
        body = "x" * (INSTAGRAM_CHAR_LIMIT + 1)
        assert poster._validate_post(body, {}) == "character_count_exceeded"

    def test_validate_post_missing_image(self, poster: InstagramPoster, tmp_path: Path) -> None:
        result = poster._validate_post("Caption.", {"image_path": str(tmp_path / "no.jpg")})
        assert result == "image_file_not_found"

    @pytest.mark.asyncio
    async def test_dev_mode_moves_to_done(self, poster: InstagramPoster, vault: Path) -> None:
        _write_approved_file(vault, "INSTAGRAM_POST_test.md", "instagram_post", "IG caption.")
        count = await poster.process_approved_posts()
        assert count == 1
        assert (vault / "Done" / "INSTAGRAM_POST_test.md").exists()

    @pytest.mark.asyncio
    async def test_dev_mode_done_has_status(self, poster: InstagramPoster, vault: Path) -> None:
        _write_approved_file(vault, "INSTAGRAM_POST_x.md", "instagram_post", "Caption.")
        await poster.process_approved_posts()
        content = (vault / "Done" / "INSTAGRAM_POST_x.md").read_text(encoding="utf-8")
        assert "status: done" in content

    @pytest.mark.asyncio
    async def test_over_limit_moves_to_rejected(self, poster: InstagramPoster, vault: Path) -> None:
        big_body = "x" * (INSTAGRAM_CHAR_LIMIT + 100)
        _write_approved_file(vault, "INSTAGRAM_POST_big.md", "instagram_post", big_body)
        count = await poster.process_approved_posts()
        assert count == 1
        assert (vault / "Rejected" / "INSTAGRAM_POST_big.md").exists()

    @pytest.mark.asyncio
    async def test_skips_facebook_type(self, poster: InstagramPoster, vault: Path) -> None:
        _write_approved_file(vault, "FACEBOOK_POST_x.md", "facebook_post", "FB post.")
        count = await poster.process_approved_posts()
        assert count == 0

    @pytest.mark.asyncio
    async def test_close_browser_safe(self, poster: InstagramPoster) -> None:
        await poster._close_browser()


# ── TestFacebookWatcher ───────────────────────────────────────────────────────


class TestFacebookWatcher:
    """Tests for backend.watchers.facebook_watcher.FacebookWatcher — DEV_MODE and vault."""

    @pytest.fixture
    def vault(self, tmp_path: Path) -> Path:
        return _make_vault(tmp_path)

    @pytest.fixture
    def watcher(self, vault: Path, tmp_path: Path):  # noqa: ANN201
        from backend.watchers.facebook_watcher import FacebookWatcher
        return FacebookWatcher(
            vault_path=str(vault),
            session_path=str(tmp_path / "meta_session"),
            check_interval=30,
            keywords=["urgent", "invoice"],
            headless=True,
            dry_run=False,
            dev_mode=True,
        )

    @pytest.mark.asyncio
    async def test_dev_mode_returns_synthetic_item(self, watcher) -> None:  # noqa: ANN001
        """DEV_MODE should return one synthetic item without launching browser."""
        items = await watcher.check_for_updates()
        assert len(items) == 1
        assert items[0]["sender"] == "[DEV_MODE]"

    @pytest.mark.asyncio
    async def test_dev_mode_no_browser_launched(self, watcher) -> None:  # noqa: ANN001
        """Browser should never be launched in DEV_MODE."""
        await watcher.check_for_updates()
        assert watcher._context is None
        assert watcher._page is None

    @pytest.mark.asyncio
    async def test_create_action_file_writes_file(self, watcher, vault: Path) -> None:  # noqa: ANN001
        """In dry_run=False / dev_mode=True, create_action_file should write vault file."""
        from backend.watchers.facebook_watcher import _make_dedup_key
        item = {
            "sender": "Test User",
            "item_type": "notification",
            "preview": "Hello there",
            "received": "2026-01-01T10:00:00Z",
            "priority": "medium",
            "matched_keyword": "invoice",
            "needs_reply": False,
            "dedup_key": _make_dedup_key("Test User", "Hello there", "2026-01-01T10:00:00Z"),
        }
        result = await watcher.create_action_file(item)
        assert result is not None
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        assert "type: facebook" in content
        assert "source: facebook_watcher" in content

    @pytest.mark.asyncio
    async def test_create_action_file_dry_run_returns_none(self, vault: Path, tmp_path: Path) -> None:
        """In dry_run=True, create_action_file should return None without writing."""
        from backend.watchers.facebook_watcher import FacebookWatcher, _make_dedup_key
        watcher = FacebookWatcher(
            vault_path=str(vault),
            session_path=str(tmp_path / "meta_session"),
            dry_run=True,
            dev_mode=True,
        )
        item = {
            "sender": "Alice",
            "item_type": "message",
            "preview": "Hey",
            "received": "2026-01-01T10:00:00Z",
            "priority": "low",
            "dedup_key": _make_dedup_key("Alice", "Hey", "2026-01-01T10:00:00Z"),
        }
        result = await watcher.create_action_file(item)
        assert result is None

    @pytest.mark.asyncio
    async def test_create_action_file_populates_processed_ids(self, watcher, vault: Path) -> None:  # noqa: ANN001
        """create_action_file should store dedup_key in _processed_ids after writing."""
        from backend.watchers.facebook_watcher import _make_dedup_key
        dedup_key = _make_dedup_key("Bob", "Test notification", "2026-01-01T10:00:00Z")
        item = {
            "sender": "Bob",
            "item_type": "notification",
            "preview": "Test notification",
            "received": "2026-01-01T10:00:00Z",
            "priority": "low",
            "dedup_key": dedup_key,
        }
        result = await watcher.create_action_file(item)
        assert result is not None
        # After creation, dedup key should be registered
        assert dedup_key in watcher._processed_ids

    def test_keyword_filter_module_function(self, vault: Path, tmp_path: Path) -> None:
        """Module-level _classify_priority returns tuple of (priority, matched_keyword)."""
        from backend.watchers.facebook_watcher import _classify_priority
        priority, kw = _classify_priority("urgent invoice needed", ["urgent", "invoice"])
        assert priority in ("high", "medium", "low")
        assert kw is not None


# ── TestInstagramWatcher ──────────────────────────────────────────────────────


class TestInstagramWatcher:
    """Tests for backend.watchers.instagram_watcher.InstagramWatcher."""

    @pytest.fixture
    def vault(self, tmp_path: Path) -> Path:
        return _make_vault(tmp_path)

    @pytest.fixture
    def watcher(self, vault: Path, tmp_path: Path):  # noqa: ANN201
        from backend.watchers.instagram_watcher import InstagramWatcher
        return InstagramWatcher(
            vault_path=str(vault),
            session_path=str(tmp_path / "meta_session"),
            check_interval=60,
            keywords=["urgent", "collab"],
            headless=True,
            dry_run=False,
            dev_mode=True,
        )

    @pytest.mark.asyncio
    async def test_dev_mode_returns_synthetic_item(self, watcher) -> None:  # noqa: ANN001
        items = await watcher.check_for_updates()
        assert len(items) == 1
        assert items[0]["sender"] == "[DEV_MODE]"

    @pytest.mark.asyncio
    async def test_dev_mode_no_browser_launched(self, watcher) -> None:  # noqa: ANN001
        await watcher.check_for_updates()
        assert watcher._context is None
        assert watcher._page is None

    @pytest.mark.asyncio
    async def test_create_action_file_writes_instagram_type(self, watcher, vault: Path) -> None:  # noqa: ANN001
        from backend.watchers.instagram_watcher import _make_dedup_key
        item = {
            "sender": "influencer_user",
            "item_type": "direct_message",
            "preview": "Hey, want to collab?",
            "received": "2026-01-01T12:00:00Z",
            "priority": "high",
            "matched_keyword": "collab",
            "needs_reply": True,
            "dedup_key": _make_dedup_key("influencer_user", "Hey, want to collab?", "2026-01-01T12:00:00Z"),
        }
        result = await watcher.create_action_file(item)
        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "type: instagram" in content
        assert "source: instagram_watcher" in content
        assert "needs_reply: true" in content

    @pytest.mark.asyncio
    async def test_create_action_file_dry_run(self, vault: Path, tmp_path: Path) -> None:
        from backend.watchers.instagram_watcher import InstagramWatcher, _make_dedup_key
        watcher = InstagramWatcher(
            vault_path=str(vault),
            session_path=str(tmp_path / "meta_session"),
            dry_run=True,
            dev_mode=True,
        )
        result = await watcher.create_action_file({
            "sender": "someone",
            "item_type": "notification",
            "preview": "test",
            "received": "2026-01-01T10:00:00Z",
            "priority": "low",
            "dedup_key": _make_dedup_key("someone", "test", "2026-01-01T10:00:00Z"),
        })
        assert result is None

    @pytest.mark.asyncio
    async def test_create_action_file_populates_processed_ids(self, watcher, vault: Path) -> None:  # noqa: ANN001
        """create_action_file should store dedup_key in _processed_ids after writing."""
        from backend.watchers.instagram_watcher import _make_dedup_key
        dedup_key = _make_dedup_key("Zara", "Like on your post", "2026-01-01T09:00:00Z")
        item = {
            "sender": "Zara",
            "item_type": "notification",
            "preview": "Like on your post",
            "received": "2026-01-01T09:00:00Z",
            "priority": "low",
            "dedup_key": dedup_key,
        }
        result = await watcher.create_action_file(item)
        assert result is not None
        assert dedup_key in watcher._processed_ids


# ── TestContentSchedulerPlatform ──────────────────────────────────────────────


class TestContentSchedulerPlatform:
    """Tests for platform routing in PostGenerator and ContentScheduler."""

    def test_post_generator_default_platform_is_linkedin(self) -> None:
        gen = PostGenerator()
        post = gen.generate(topic_key="ai_automation", topic_title="AI and Automation")
        assert post.platform == "linkedin"

    def test_post_generator_facebook_platform_set(self) -> None:
        gen = PostGenerator()
        post = gen.generate(
            topic_key="ai_automation", topic_title="AI and Automation", platform="facebook"
        )
        assert post.platform == "facebook"

    def test_post_generator_instagram_platform_set(self) -> None:
        gen = PostGenerator()
        post = gen.generate(
            topic_key="ai_automation", topic_title="AI and Automation", platform="instagram"
        )
        assert post.platform == "instagram"

    def test_instagram_post_within_char_limit(self) -> None:
        gen = PostGenerator()
        post = gen.generate(
            topic_key="ai_automation", topic_title="AI Test", platform="instagram"
        )
        assert post.character_count <= PG_INSTAGRAM_LIMIT

    def test_instagram_truncation_when_over_limit(self) -> None:
        """If body exceeds 2200, it must be truncated."""
        gen = PostGenerator()
        # Override a template to be oversized
        from backend.scheduler.post_generator import PostTemplate, TEMPLATES
        oversized = "x" * 2500
        fake_template = PostTemplate(
            template_id="test_oversized",
            topic_key="ai_automation",
            format_type="tip",
            body=oversized,
            hashtags=["#Test"],
        )
        original = TEMPLATES["ai_automation"][:]
        TEMPLATES["ai_automation"] = [fake_template]
        try:
            # validate_post will fail on "no question" but truncation happens first
            # We test that body is truncated to <= INSTAGRAM_CHAR_LIMIT
            from backend.scheduler.post_generator import INSTAGRAM_CHAR_LIMIT
            with patch.object(gen, "validate_post", return_value=MagicMock(valid=True, character_count=100)):
                post = gen.generate(
                    topic_key="ai_automation",
                    topic_title="AI Test",
                    platform="instagram",
                )
            assert len(post.body) <= INSTAGRAM_CHAR_LIMIT
        finally:
            TEMPLATES["ai_automation"] = original

    def test_content_scheduler_topic_parse_default_platform(self, tmp_path: Path) -> None:
        """Topics without [platform:] tag default to linkedin."""
        from backend.scheduler.content_scheduler import ContentScheduler
        strategy_md = tmp_path / "Content_Strategy.md"
        strategy_md.write_text(
            "---\npost_frequency: daily\n---\n"
            "## Topics I Want to Post About\n"
            "1. AI and Automation - Test topic\n",
            encoding="utf-8",
        )
        scheduler = ContentScheduler(vault_path=str(tmp_path), dev_mode=True)
        strategy = scheduler._load_strategy()
        assert strategy.topics[0].platform == "linkedin"

    def test_content_scheduler_topic_parse_facebook_platform(self, tmp_path: Path) -> None:
        from backend.scheduler.content_scheduler import ContentScheduler
        strategy_md = tmp_path / "Content_Strategy.md"
        strategy_md.write_text(
            "---\npost_frequency: daily\n---\n"
            "## Topics I Want to Post About\n"
            "1. AI and Automation [platform: facebook] - Test topic\n",
            encoding="utf-8",
        )
        scheduler = ContentScheduler(vault_path=str(tmp_path), dev_mode=True)
        strategy = scheduler._load_strategy()
        assert strategy.topics[0].platform == "facebook"

    def test_content_scheduler_topic_parse_instagram_platform(self, tmp_path: Path) -> None:
        from backend.scheduler.content_scheduler import ContentScheduler
        strategy_md = tmp_path / "Content_Strategy.md"
        strategy_md.write_text(
            "---\npost_frequency: daily\n---\n"
            "## Topics I Want to Post About\n"
            "1. Career Tips [platform: instagram] - Career content\n",
            encoding="utf-8",
        )
        scheduler = ContentScheduler(vault_path=str(tmp_path), dev_mode=True)
        strategy = scheduler._load_strategy()
        assert strategy.topics[0].platform == "instagram"

    def test_save_draft_uses_platform_in_filename_and_type(self, tmp_path: Path) -> None:
        """Draft files should be named FACEBOOK_POST_*.md with type: facebook_post."""
        from backend.scheduler.content_scheduler import ContentScheduler, Topic
        scheduler = ContentScheduler(vault_path=str(tmp_path), dev_mode=True, dry_run=False)
        (tmp_path / "Pending_Approval").mkdir(exist_ok=True)
        topic = Topic(
            index=0,
            title="AI and Automation",
            description="Test",
            topic_key="ai_automation",
            platform="facebook",
        )
        path = scheduler._save_draft(topic, "Test body.", "tmpl_001", 10, "2026-02-21")
        assert "FACEBOOK_POST_" in path.name
        content = path.read_text(encoding="utf-8")
        assert "type: facebook_post" in content
        assert "platform: facebook" in content

    def test_save_draft_linkedin_uses_linkedin_type(self, tmp_path: Path) -> None:
        from backend.scheduler.content_scheduler import ContentScheduler, Topic
        scheduler = ContentScheduler(vault_path=str(tmp_path), dev_mode=True, dry_run=False)
        (tmp_path / "Pending_Approval").mkdir(exist_ok=True)
        topic = Topic(
            index=0,
            title="Backend Dev",
            description="Test",
            topic_key="backend_development",
            platform="linkedin",
        )
        path = scheduler._save_draft(topic, "Test body.", "tmpl_002", 10, "2026-02-21")
        assert "LINKEDIN_POST_" in path.name
        content = path.read_text(encoding="utf-8")
        assert "type: linkedin_post" in content


# ── TestActionExecutorMeta ────────────────────────────────────────────────────


class TestActionExecutorMeta:
    """Tests for HANDLERS dict dispatch of facebook_post and instagram_post."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> OrchestratorConfig:
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "Approved").mkdir()
        (vault / "Done").mkdir()
        (vault / "Logs" / "actions").mkdir(parents=True)
        return OrchestratorConfig(vault_path=str(vault), check_interval=1, dev_mode=True)

    @pytest.fixture
    def executor(self, config: OrchestratorConfig) -> ActionExecutor:
        return ActionExecutor(config)

    def test_handlers_contains_facebook_post(self, executor: ActionExecutor) -> None:
        assert "facebook_post" in ActionExecutor.HANDLERS

    def test_handlers_contains_instagram_post(self, executor: ActionExecutor) -> None:
        assert "instagram_post" in ActionExecutor.HANDLERS

    def test_handle_facebook_post_method_exists(self, executor: ActionExecutor) -> None:
        assert hasattr(executor, "_handle_facebook_post")
        assert callable(getattr(executor, "_handle_facebook_post"))

    def test_handle_instagram_post_method_exists(self, executor: ActionExecutor) -> None:
        assert hasattr(executor, "_handle_instagram_post")
        assert callable(getattr(executor, "_handle_instagram_post"))

    @pytest.mark.asyncio
    async def test_facebook_post_dispatched_via_handlers(
        self, executor: ActionExecutor, tmp_path: Path
    ) -> None:
        """facebook_post type should resolve to _handle_facebook_post."""
        handler_name = ActionExecutor.HANDLERS.get("facebook_post")
        assert handler_name == "_handle_facebook_post"
        handler = getattr(executor, handler_name)
        assert callable(handler)

    @pytest.mark.asyncio
    async def test_instagram_post_dispatched_via_handlers(
        self, executor: ActionExecutor, tmp_path: Path
    ) -> None:
        """instagram_post type should resolve to _handle_instagram_post."""
        handler_name = ActionExecutor.HANDLERS.get("instagram_post")
        assert handler_name == "_handle_instagram_post"
        handler = getattr(executor, handler_name)
        assert callable(handler)

    @pytest.mark.asyncio
    async def test_dev_mode_processes_facebook_post_type(
        self, executor: ActionExecutor, config: OrchestratorConfig
    ) -> None:
        """In DEV_MODE, facebook_post file should be moved to Done/."""
        vault = Path(config.vault_path)
        approved_file = vault / "Approved" / "FACEBOOK_POST_dev.md"
        create_file_with_frontmatter(
            approved_file,
            {"type": "facebook_post", "status": "approved"},
            "\nTest Facebook post.\n",
        )
        result = await executor.process_file(approved_file, {"type": "facebook_post", "status": "approved"})
        assert result is True
        assert (vault / "Done" / "FACEBOOK_POST_dev.md").exists()

    @pytest.mark.asyncio
    async def test_dev_mode_processes_instagram_post_type(
        self, executor: ActionExecutor, config: OrchestratorConfig
    ) -> None:
        """In DEV_MODE, instagram_post file should be moved to Done/."""
        vault = Path(config.vault_path)
        approved_file = vault / "Approved" / "INSTAGRAM_POST_dev.md"
        create_file_with_frontmatter(
            approved_file,
            {"type": "instagram_post", "status": "approved"},
            "\nTest Instagram caption.\n",
        )
        result = await executor.process_file(approved_file, {"type": "instagram_post", "status": "approved"})
        assert result is True
        assert (vault / "Done" / "INSTAGRAM_POST_dev.md").exists()


# ── TestMetaSessionSetup ──────────────────────────────────────────────────────


class TestMetaSessionSetup:
    """Tests for session state detection in FacebookWatcher and InstagramWatcher."""

    @pytest.fixture
    def vault(self, tmp_path: Path) -> Path:
        return _make_vault(tmp_path)

    @pytest.mark.asyncio
    async def test_facebook_session_state_login_url(self, vault: Path, tmp_path: Path) -> None:
        """URL containing /login should return login_required."""
        from backend.watchers.facebook_watcher import FacebookWatcher
        watcher = FacebookWatcher(vault_path=str(vault), session_path=str(tmp_path / "s"), dev_mode=True)
        mock_page = MagicMock()
        mock_page.url = "https://www.facebook.com/login/?next=/"
        mock_page.query_selector = AsyncMock(return_value=None)
        watcher._page = mock_page
        state = await watcher._check_session_state()
        assert state == "login_required"

    @pytest.mark.asyncio
    async def test_facebook_session_state_checkpoint_url(self, vault: Path, tmp_path: Path) -> None:
        """URL with /checkpoint should return captcha."""
        from backend.watchers.facebook_watcher import FacebookWatcher
        watcher = FacebookWatcher(vault_path=str(vault), session_path=str(tmp_path / "s"), dev_mode=True)
        mock_page = MagicMock()
        mock_page.url = "https://www.facebook.com/checkpoint/blocked/"
        mock_page.query_selector = AsyncMock(return_value=None)
        watcher._page = mock_page
        state = await watcher._check_session_state()
        assert state == "captcha"

    @pytest.mark.asyncio
    async def test_instagram_session_state_login_url(self, vault: Path, tmp_path: Path) -> None:
        """Instagram /accounts/login/ URL should return login_required."""
        from backend.watchers.instagram_watcher import InstagramWatcher
        watcher = InstagramWatcher(vault_path=str(vault), session_path=str(tmp_path / "s"), dev_mode=True)
        mock_page = MagicMock()
        mock_page.url = "https://www.instagram.com/accounts/login/"
        mock_page.query_selector = AsyncMock(return_value=None)
        watcher._page = mock_page
        state = await watcher._check_session_state()
        assert state == "login_required"

    @pytest.mark.asyncio
    async def test_facebook_session_ready_with_nav_element(self, vault: Path, tmp_path: Path) -> None:
        """Finding an authenticated element should return ready."""
        from backend.watchers.facebook_watcher import FacebookWatcher
        watcher = FacebookWatcher(vault_path=str(vault), session_path=str(tmp_path / "s"), dev_mode=True)
        mock_page = MagicMock()
        mock_page.url = "https://www.facebook.com/"
        mock_element = MagicMock()
        # Return None for all login DOM probes, then mock_element for first auth selector
        # login selectors = 3 probes, auth selectors = up to 5 probes (we return element on first)
        # FacebookWatcher._check_session_state probes 4 login DOM selectors,
        # then delegates to _is_authenticated() which checks auth selectors.
        # Return None for the 4 login probes, mock_element for auth selector queries.
        call_count = {"n": 0}
        async def _selector_side_effect(sel: str) -> MagicMock | None:
            call_count["n"] += 1
            if call_count["n"] <= 4:  # noqa: PLR2004  # 4 login selectors → None
                return None
            return mock_element  # auth selectors → authenticated element
        mock_page.query_selector = _selector_side_effect
        watcher._page = mock_page
        state = await watcher._check_session_state()
        assert state == "ready"

    def test_facebook_watcher_session_path_attribute(self, vault: Path, tmp_path: Path) -> None:
        """FacebookWatcher should expose session_path as Path."""
        from backend.watchers.facebook_watcher import FacebookWatcher
        session = str(tmp_path / "meta_session")
        watcher = FacebookWatcher(vault_path=str(vault), session_path=session, dev_mode=True)
        assert watcher.session_path == Path(session)

    def test_instagram_watcher_session_path_attribute(self, vault: Path, tmp_path: Path) -> None:
        """InstagramWatcher should expose session_path as Path."""
        from backend.watchers.instagram_watcher import InstagramWatcher
        session = str(tmp_path / "meta_session")
        watcher = InstagramWatcher(vault_path=str(vault), session_path=session, dev_mode=True)
        assert watcher.session_path == Path(session)
