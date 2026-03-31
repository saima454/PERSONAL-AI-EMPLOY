"""Tests for the LinkedIn poster module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.actions.linkedin_poster import (
    MAX_POSTS_PER_RUN,
    POST_SELECTORS,
    LinkedInPoster,
)
from backend.utils.frontmatter import create_file_with_frontmatter

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Create a temporary vault directory structure."""
    (tmp_path / "Approved").mkdir()
    (tmp_path / "Done").mkdir()
    (tmp_path / "Logs" / "actions").mkdir(parents=True)
    (tmp_path / "Logs" / "errors").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def poster(vault_dir: Path, tmp_path: Path) -> LinkedInPoster:
    """Create a LinkedInPoster instance with test config."""
    return LinkedInPoster(
        vault_path=str(vault_dir),
        session_path=str(tmp_path / "linkedin_session"),
        headless=True,
        dry_run=False,
        dev_mode=True,
    )


@pytest.fixture
def dry_run_poster(vault_dir: Path, tmp_path: Path) -> LinkedInPoster:
    """Create a LinkedInPoster in dry run mode."""
    return LinkedInPoster(
        vault_path=str(vault_dir),
        session_path=str(tmp_path / "linkedin_session"),
        headless=True,
        dry_run=True,
        dev_mode=True,
    )


@pytest.fixture
def sample_post_file(vault_dir: Path) -> Path:
    """Create a sample approved LinkedIn post file."""
    file_path = vault_dir / "Approved" / "LPOST_test_20260212T090000.md"
    frontmatter = {
        "type": "linkedin_post",
        "id": "LPOST_abc12345_20260212T090000",
        "source": "claude_draft",
        "status": "pending_approval",
        "created": "2026-02-12T09:00:00Z",
        "action_summary": "Post about AI hackathon experience",
        "risk_assessment": "Public post visible to all connections",
        "rollback_plan": "Delete post from LinkedIn manually",
        "sensitivity": "medium",
    }
    body = """# Post Content

Excited to share our experience at the AI Employee Hackathon!

We built an autonomous agent system that manages tasks 24/7.

#AI #Hackathon #Innovation"""
    create_file_with_frontmatter(file_path, frontmatter, body)
    return file_path


@pytest.fixture
def sample_non_linkedin_file(vault_dir: Path) -> Path:
    """Create a non-LinkedIn file in Approved/."""
    file_path = vault_dir / "Approved" / "OTHER_test.md"
    frontmatter = {
        "type": "email_draft",
        "id": "EMAIL_abc12345",
        "status": "pending_approval",
    }
    body = "Some email draft content."
    create_file_with_frontmatter(file_path, frontmatter, body)
    return file_path


# ── Unit Tests: find_approved_posts ─────────────────────────────────


class TestFindApprovedPosts:
    def test_finds_linkedin_post(self, poster: LinkedInPoster, sample_post_file: Path) -> None:
        posts = poster.find_approved_posts()
        assert len(posts) == 1
        assert posts[0] == sample_post_file

    def test_ignores_non_linkedin_files(
        self, poster: LinkedInPoster, sample_non_linkedin_file: Path
    ) -> None:
        posts = poster.find_approved_posts()
        assert len(posts) == 0

    def test_empty_approved_dir(self, poster: LinkedInPoster) -> None:
        posts = poster.find_approved_posts()
        assert len(posts) == 0

    def test_no_approved_dir(self, poster: LinkedInPoster, vault_dir: Path) -> None:
        import shutil
        shutil.rmtree(vault_dir / "Approved")
        posts = poster.find_approved_posts()
        assert len(posts) == 0

    def test_max_posts_limit(self, poster: LinkedInPoster, vault_dir: Path) -> None:
        for i in range(MAX_POSTS_PER_RUN + 3):
            file_path = vault_dir / "Approved" / f"LPOST_test_{i:04d}.md"
            create_file_with_frontmatter(
                file_path,
                {"type": "linkedin_post", "id": f"LPOST_{i}"},
                f"Post content {i}",
            )
        posts = poster.find_approved_posts()
        assert len(posts) == MAX_POSTS_PER_RUN

    def test_skips_malformed_files(self, poster: LinkedInPoster, vault_dir: Path) -> None:
        bad_file = vault_dir / "Approved" / "bad_file.md"
        bad_file.write_text("no frontmatter here", encoding="utf-8")
        posts = poster.find_approved_posts()
        assert len(posts) == 0


# ── Unit Tests: _extract_post_content ───────────────────────────────


class TestExtractPostContent:
    def test_extracts_frontmatter_and_body(
        self, poster: LinkedInPoster, sample_post_file: Path
    ) -> None:
        frontmatter, body = poster._extract_post_content(sample_post_file)
        assert frontmatter["type"] == "linkedin_post"
        assert "AI Employee Hackathon" in body
        assert "#AI #Hackathon #Innovation" in body

    def test_strips_heading(self, poster: LinkedInPoster, sample_post_file: Path) -> None:
        frontmatter, body = poster._extract_post_content(sample_post_file)
        assert not body.startswith("# Post Content")

    def test_preserves_multiple_paragraphs(
        self, poster: LinkedInPoster, sample_post_file: Path
    ) -> None:
        _, body = poster._extract_post_content(sample_post_file)
        assert "\n\n" in body


# ── Unit Tests: publish_post (dev_mode) ─────────────────────────────


class TestPublishPostDevMode:
    async def test_dev_mode_returns_true(self, poster: LinkedInPoster) -> None:
        poster._page = AsyncMock()
        result = await poster.publish_post("Test post content")
        assert result is True

    async def test_dev_mode_does_not_click(self, poster: LinkedInPoster) -> None:
        mock_page = AsyncMock()
        poster._page = mock_page
        await poster.publish_post("Test post content")
        mock_page.query_selector.assert_not_called()


# ── Unit Tests: _move_to_done ───────────────────────────────────────


class TestMoveToDone:
    def test_moves_file_to_done(
        self, poster: LinkedInPoster, sample_post_file: Path, vault_dir: Path
    ) -> None:
        dest = poster._move_to_done(sample_post_file, "success")
        assert dest.parent == vault_dir / "Done"
        assert dest.exists()
        assert not sample_post_file.exists()

    def test_updates_frontmatter_status(
        self, poster: LinkedInPoster, sample_post_file: Path
    ) -> None:
        dest = poster._move_to_done(sample_post_file, "success")
        content = dest.read_text(encoding="utf-8")
        assert "status: done" in content
        assert "result: success" in content
        assert "completed_at:" in content

    def test_creates_done_dir_if_missing(
        self, poster: LinkedInPoster, sample_post_file: Path, vault_dir: Path
    ) -> None:
        import shutil
        shutil.rmtree(vault_dir / "Done")
        dest = poster._move_to_done(sample_post_file, "success")
        assert dest.exists()


# ── Unit Tests: process_approved_posts (dry_run) ────────────────────


class TestProcessApprovedPostsDryRun:
    async def test_dry_run_no_file_move(
        self, dry_run_poster: LinkedInPoster, sample_post_file: Path, vault_dir: Path
    ) -> None:
        # Mock browser to avoid launching
        dry_run_poster._page = AsyncMock()
        dry_run_poster._context = MagicMock()

        # Mock navigation and session check
        dry_run_poster._navigate_and_wait = AsyncMock()
        dry_run_poster._check_session_state = AsyncMock(return_value="ready")

        count = await dry_run_poster.process_approved_posts()
        assert count == 1
        # File should still be in Approved
        assert sample_post_file.exists()

    async def test_dry_run_logs_action(
        self, dry_run_poster: LinkedInPoster, sample_post_file: Path, vault_dir: Path
    ) -> None:
        dry_run_poster._page = AsyncMock()
        dry_run_poster._context = MagicMock()
        dry_run_poster._navigate_and_wait = AsyncMock()
        dry_run_poster._check_session_state = AsyncMock(return_value="ready")

        await dry_run_poster.process_approved_posts()
        log_files = list((vault_dir / "Logs" / "actions").glob("*.json"))
        assert len(log_files) == 1
        log_data = json.loads(log_files[0].read_text(encoding="utf-8"))
        entry = log_data["entries"][0]
        assert entry["result"] == "dry_run"
        assert entry["actor"] == "linkedin_poster"


# ── Unit Tests: process_approved_posts (not logged in) ──────────────


class TestProcessNotLoggedIn:
    async def test_returns_zero_when_not_logged_in(
        self, poster: LinkedInPoster, sample_post_file: Path
    ) -> None:
        poster._page = AsyncMock()
        poster._context = MagicMock()
        poster._navigate_and_wait = AsyncMock()
        poster._check_session_state = AsyncMock(return_value="login_required")
        poster._save_debug_screenshot = AsyncMock()

        count = await poster.process_approved_posts()
        assert count == 0

    async def test_no_posts_returns_zero(self, poster: LinkedInPoster) -> None:
        count = await poster.process_approved_posts()
        assert count == 0


# ── Unit Tests: POST_SELECTORS ──────────────────────────────────────


class TestPostSelectors:
    def test_has_start_post(self) -> None:
        assert "start_post" in POST_SELECTORS
        assert len(POST_SELECTORS["start_post"]) >= 2

    def test_has_text_editor(self) -> None:
        assert "text_editor" in POST_SELECTORS
        assert len(POST_SELECTORS["text_editor"]) >= 2

    def test_has_post_button(self) -> None:
        assert "post_button" in POST_SELECTORS
        assert len(POST_SELECTORS["post_button"]) >= 2

    def test_has_authenticated_selectors(self) -> None:
        from backend.actions.linkedin_poster import AUTHENTICATED_SELECTORS
        assert len(AUTHENTICATED_SELECTORS) >= 4


# ── Unit Tests: Poster Init ────────────────────────────────────────


class TestPosterInit:
    def test_paths_set_correctly(self, poster: LinkedInPoster, vault_dir: Path) -> None:
        assert poster.vault_path == vault_dir
        assert poster.approved_path == vault_dir / "Approved"
        assert poster.done_path == vault_dir / "Done"
        assert poster.logs_path == vault_dir / "Logs"

    def test_dry_run_flag(self, dry_run_poster: LinkedInPoster) -> None:
        assert dry_run_poster.dry_run is True

    def test_dev_mode_flag(self, poster: LinkedInPoster) -> None:
        assert poster.dev_mode is True

    def test_defaults(self, vault_dir: Path) -> None:
        p = LinkedInPoster(vault_path=str(vault_dir))
        assert p.dry_run is True
        assert p.dev_mode is True
        assert p.headless is True
