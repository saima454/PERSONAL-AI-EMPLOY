"""Tests for the LinkedIn watcher module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.watchers.linkedin_watcher import (
    AUTHENTICATED_SELECTORS,
    LOGGED_IN_SELECTOR,
    SELECTORS,
    LinkedInWatcher,
    _classify_priority,
    _make_dedup_key,
    _slugify,
)

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Create a temporary vault directory structure."""
    (tmp_path / "Needs_Action").mkdir()
    (tmp_path / "Logs" / "actions").mkdir(parents=True)
    (tmp_path / "Logs" / "errors").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def watcher(vault_dir: Path, tmp_path: Path) -> LinkedInWatcher:
    """Create a LinkedInWatcher instance with test config."""
    return LinkedInWatcher(
        vault_path=str(vault_dir),
        session_path=str(tmp_path / "linkedin_session"),
        check_interval=300,
        keywords=["urgent", "invoice", "proposal", "opportunity", "project", "meeting", "job", "partnership"],
        headless=True,
        dry_run=False,
        dev_mode=True,
    )


@pytest.fixture
def dry_run_watcher(vault_dir: Path, tmp_path: Path) -> LinkedInWatcher:
    """Create a LinkedInWatcher in dry run mode."""
    return LinkedInWatcher(
        vault_path=str(vault_dir),
        session_path=str(tmp_path / "linkedin_session"),
        check_interval=300,
        keywords=["urgent", "invoice", "proposal", "opportunity", "project", "meeting", "job", "partnership"],
        headless=True,
        dry_run=True,
        dev_mode=True,
    )


@pytest.fixture
def sample_notification_item() -> dict[str, Any]:
    """A parsed LinkedIn notification dict."""
    return {
        "item_type": "notification",
        "sender": "Jane Doe",
        "preview": "Jane Doe mentioned you in a comment about the project proposal",
        "time": "2h",
        "priority": "high",
        "matched_keyword": "proposal",
        "dedup_key": "Jane Doe|Jane Doe mentioned you in a comment about the project proposal|2h",
    }


@pytest.fixture
def sample_message_item() -> dict[str, Any]:
    """A parsed LinkedIn message dict."""
    return {
        "item_type": "message",
        "sender": "John Smith",
        "preview": "Hi, I have an urgent question about the partnership",
        "time": "10:30 AM",
        "priority": "high",
        "matched_keyword": "urgent",
        "dedup_key": "John Smith|Hi, I have an urgent question about the partnership|10:30 AM",
    }


# ── Unit Tests: _slugify ────────────────────────────────────────────


class TestSlugify:
    def test_basic_slugify(self) -> None:
        assert _slugify("Jane Doe") == "jane-doe"

    def test_special_characters(self) -> None:
        assert _slugify("John O'Brien (CEO)") == "john-o-brien-ceo"

    def test_long_name_truncated(self) -> None:
        long_name = "a" * 100
        result = _slugify(long_name, max_length=40)
        assert len(result) <= 40

    def test_empty_string(self) -> None:
        assert _slugify("") == ""

    def test_only_special_chars(self) -> None:
        assert _slugify("+++###") == ""

    def test_preserves_numbers(self) -> None:
        assert _slugify("Team Chat 42") == "team-chat-42"

    def test_strips_trailing_hyphens(self) -> None:
        result = _slugify("hello---", max_length=40)
        assert not result.endswith("-")


# ── Unit Tests: _classify_priority ──────────────────────────────────


class TestClassifyPriority:
    def test_high_priority_urgent(self) -> None:
        priority, kw = _classify_priority("This is URGENT!", ["urgent", "meeting"])
        assert priority == "high"
        assert kw == "urgent"

    def test_high_priority_invoice(self) -> None:
        priority, kw = _classify_priority("Please send invoice", ["invoice", "meeting"])
        assert priority == "high"
        assert kw == "invoice"

    def test_high_priority_proposal(self) -> None:
        priority, kw = _classify_priority("New proposal received", ["proposal", "meeting"])
        assert priority == "high"
        assert kw == "proposal"

    def test_medium_priority_opportunity(self) -> None:
        priority, kw = _classify_priority("Great opportunity here", ["opportunity", "urgent"])
        assert priority == "medium"
        assert kw == "opportunity"

    def test_medium_priority_meeting(self) -> None:
        priority, kw = _classify_priority("About tomorrow's meeting", ["meeting", "urgent"])
        assert priority == "medium"
        assert kw == "meeting"

    def test_medium_priority_job(self) -> None:
        priority, kw = _classify_priority("New job opening", ["job", "urgent"])
        assert priority == "medium"
        assert kw == "job"

    def test_medium_priority_partnership(self) -> None:
        priority, kw = _classify_priority("Partnership discussion", ["partnership"])
        assert priority == "medium"
        assert kw == "partnership"

    def test_no_keyword_match(self) -> None:
        priority, kw = _classify_priority("Hello there", ["urgent", "invoice"])
        assert priority == "low"
        assert kw is None

    def test_case_insensitive(self) -> None:
        priority, kw = _classify_priority("INVOICE needed", ["invoice"])
        assert priority == "high"
        assert kw == "invoice"

    def test_high_takes_precedence(self) -> None:
        priority, kw = _classify_priority(
            "urgent meeting tomorrow",
            ["urgent", "meeting"],
        )
        assert priority == "high"
        assert kw == "urgent"


# ── Unit Tests: _make_dedup_key ─────────────────────────────────────


class TestMakeDedupKey:
    def test_basic_key(self) -> None:
        key = _make_dedup_key("Jane", "Hello", "2h")
        assert key == "Jane|Hello|2h"

    def test_long_message_truncated(self) -> None:
        long_msg = "a" * 200
        key = _make_dedup_key("Jane", long_msg, "2h")
        assert len(key.split("|")[1]) == 100

    def test_empty_components(self) -> None:
        key = _make_dedup_key("", "", "")
        assert key == "||"


# ── Unit Tests: Action File Creation ────────────────────────────────


class TestCreateActionFile:
    async def test_creates_file_in_needs_action(
        self, watcher: LinkedInWatcher, sample_notification_item: dict[str, Any], vault_dir: Path
    ) -> None:
        result = await watcher.create_action_file(sample_notification_item)
        assert result is not None
        assert result.parent == vault_dir / "Needs_Action"
        assert result.exists()

    async def test_file_has_correct_frontmatter(
        self, watcher: LinkedInWatcher, sample_notification_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_notification_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        assert "type: linkedin" in content
        assert "source: linkedin_watcher" in content
        assert "sender: Jane Doe" in content
        assert "priority: high" in content
        assert "status: pending" in content
        assert "item_type: notification" in content

    async def test_file_has_body_sections(
        self, watcher: LinkedInWatcher, sample_notification_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_notification_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        assert "## LinkedIn Notification" in content
        assert "## Content" in content
        assert "## Suggested Actions" in content
        assert "Review on LinkedIn" in content

    async def test_file_contains_preview(
        self, watcher: LinkedInWatcher, sample_notification_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_notification_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        assert "project proposal" in content

    async def test_filename_format_notification(
        self, watcher: LinkedInWatcher, sample_notification_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_notification_item)
        assert result is not None
        assert result.name.startswith("LINKEDIN_jane-doe_")
        assert result.name.endswith(".md")

    async def test_filename_format_message(
        self, watcher: LinkedInWatcher, sample_message_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_message_item)
        assert result is not None
        assert result.name.startswith("LINKEDIN_john-smith_")
        assert result.name.endswith(".md")

    async def test_message_item_frontmatter(
        self, watcher: LinkedInWatcher, sample_message_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_message_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "item_type: message" in content
        assert "## LinkedIn Message" in content

    async def test_file_contains_priority_info(
        self, watcher: LinkedInWatcher, sample_notification_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_notification_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "keyword: proposal" in content

    async def test_dry_run_creates_no_file(
        self, dry_run_watcher: LinkedInWatcher, sample_notification_item: dict[str, Any], vault_dir: Path
    ) -> None:
        result = await dry_run_watcher.create_action_file(sample_notification_item)
        assert result is None
        files = list((vault_dir / "Needs_Action").glob("LINKEDIN_*.md"))
        assert len(files) == 0

    async def test_dry_run_logs_action(
        self, dry_run_watcher: LinkedInWatcher, sample_notification_item: dict[str, Any], vault_dir: Path
    ) -> None:
        await dry_run_watcher.create_action_file(sample_notification_item)
        log_files = list((vault_dir / "Logs" / "actions").glob("*.json"))
        assert len(log_files) == 1
        log_data = json.loads(log_files[0].read_text(encoding="utf-8"))
        entry = log_data["entries"][0]
        assert entry["result"] == "dry_run"
        assert entry["actor"] == "linkedin_watcher"

    async def test_updates_processed_ids(
        self, watcher: LinkedInWatcher, sample_notification_item: dict[str, Any]
    ) -> None:
        await watcher.create_action_file(sample_notification_item)
        assert sample_notification_item["dedup_key"] in watcher._processed_ids

    async def test_logs_success_action(
        self, watcher: LinkedInWatcher, sample_notification_item: dict[str, Any], vault_dir: Path
    ) -> None:
        await watcher.create_action_file(sample_notification_item)
        log_files = list((vault_dir / "Logs" / "actions").glob("*.json"))
        assert len(log_files) == 1
        log_data = json.loads(log_files[0].read_text(encoding="utf-8"))
        entry = log_data["entries"][0]
        assert entry["result"] == "success"
        assert entry["parameters"]["sender"] == "Jane Doe"


# ── Unit Tests: Processed IDs ───────────────────────────────────────


class TestProcessedIds:
    def test_load_empty(self, watcher: LinkedInWatcher) -> None:
        watcher._load_processed_ids()
        assert watcher._processed_ids == {}

    def test_load_existing(self, watcher: LinkedInWatcher, vault_dir: Path) -> None:
        data = {
            "processed_ids": {"Jane|Hello|2h": "2026-02-11T10:00:00Z"},
            "last_cleanup": "2026-02-11T00:00:00Z",
        }
        processed_path = vault_dir / "Logs" / "processed_linkedin.json"
        processed_path.write_text(json.dumps(data), encoding="utf-8")

        watcher._load_processed_ids()
        assert "Jane|Hello|2h" in watcher._processed_ids
        assert watcher._last_cleanup == "2026-02-11T00:00:00Z"

    def test_save_and_reload(self, watcher: LinkedInWatcher) -> None:
        watcher._processed_ids = {"Jane|Test|2h": "2026-02-11T12:00:00Z"}
        watcher._save_processed_ids()

        watcher._processed_ids = {}
        watcher._load_processed_ids()
        assert "Jane|Test|2h" in watcher._processed_ids

    def test_save_creates_valid_json(self, watcher: LinkedInWatcher) -> None:
        watcher._processed_ids = {"a|b|c": "2026-01-01T00:00:00Z"}
        watcher._save_processed_ids()
        data = json.loads(watcher.processed_ids_path.read_text(encoding="utf-8"))
        assert "processed_ids" in data
        assert "last_cleanup" in data

    def test_corrupted_file_handled(self, watcher: LinkedInWatcher, vault_dir: Path) -> None:
        processed_path = vault_dir / "Logs" / "processed_linkedin.json"
        processed_path.write_text("not valid json{{{", encoding="utf-8")
        watcher._load_processed_ids()
        assert watcher._processed_ids == {}


# ── Unit Tests: Session State Detection ─────────────────────────────


class TestSessionState:
    async def test_check_session_ready_via_auth_selector(self, watcher: LinkedInWatcher) -> None:
        """Ready state requires strict authenticated selector to match."""
        mock_page = AsyncMock()

        async def query_selector(selector: str) -> Any:
            if "me-photo" in selector:
                return MagicMock()
            return None

        mock_page.query_selector = query_selector
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.url = "https://www.linkedin.com/feed/"
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "ready"

    async def test_check_session_ready_via_element_count(self, watcher: LinkedInWatcher) -> None:
        """Ready state detected via element count heuristic on /feed/ URL."""
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)

        # Simulate a logged-in page with many elements
        async def query_selector_all(selector: str) -> list:
            if selector == "button":
                return [MagicMock()] * 20
            if selector == "a":
                return [MagicMock()] * 30
            if selector == "img":
                return [MagicMock()] * 10
            return []

        mock_page.query_selector_all = query_selector_all
        mock_page.url = "https://www.linkedin.com/feed/"
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "ready"

    async def test_check_session_login_required_via_url(self, watcher: LinkedInWatcher) -> None:
        """Login page detected via URL."""
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.url = "https://www.linkedin.com/login"
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "login_required"

    async def test_check_session_login_required_via_dom(self, watcher: LinkedInWatcher) -> None:
        """Login page detected via login form selector."""
        mock_page = AsyncMock()

        async def query_selector(selector: str) -> Any:
            if "login__form" in selector or "session_key" in selector:
                return MagicMock()
            return None

        mock_page.query_selector = query_selector
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.url = "https://www.linkedin.com/feed/"
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "login_required"

    async def test_few_elements_not_authenticated(self, watcher: LinkedInWatcher) -> None:
        """A page with few elements is not considered authenticated."""
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)

        # Simulate a public page with few elements
        async def query_selector_all(selector: str) -> list:
            if selector in ("button", "a", "img"):
                return [MagicMock()] * 5
            return []

        mock_page.query_selector_all = query_selector_all
        mock_page.url = "https://www.linkedin.com/feed/"
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "unknown"

    async def test_check_session_captcha_via_url(self, watcher: LinkedInWatcher) -> None:
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.url = "https://www.linkedin.com/checkpoint/challenge"
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "captcha"

    async def test_check_session_captcha_via_dom(self, watcher: LinkedInWatcher) -> None:
        """Only the specific #captcha-internal ID triggers captcha state."""
        mock_page = AsyncMock()

        async def query_selector(selector: str) -> Any:
            if selector == "#captcha-internal":
                return MagicMock()
            return None

        mock_page.query_selector = query_selector
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.url = "https://www.linkedin.com/feed/"
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "captcha"

    async def test_check_session_unknown(self, watcher: LinkedInWatcher) -> None:
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.url = "https://www.linkedin.com/some-other-page"
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "unknown"

    async def test_authwall_url_is_login_required(self, watcher: LinkedInWatcher) -> None:
        """LinkedIn /authwall redirect is treated as login required."""
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)
        mock_page.query_selector_all = AsyncMock(return_value=[])
        mock_page.url = "https://www.linkedin.com/authwall?trk=foo"
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "login_required"


# ── Unit Tests: Selectors ───────────────────────────────────────────


class TestSelectors:
    def test_logged_in_selector_contains_nav(self) -> None:
        assert 'nav[aria-label="Primary"]' in LOGGED_IN_SELECTOR

    def test_logged_in_selector_contains_main(self) -> None:
        assert "main[role='main']" in LOGGED_IN_SELECTOR

    def test_selectors_has_notification_keys(self) -> None:
        assert "notification_card" in SELECTORS
        assert "notification_unread" in SELECTORS
        assert "notification_text" in SELECTORS

    def test_selectors_has_message_keys(self) -> None:
        assert "msg_thread" in SELECTORS
        assert "msg_unread" in SELECTORS
        assert "msg_sender" in SELECTORS
        assert "msg_preview" in SELECTORS

    def test_authenticated_selectors_not_empty(self) -> None:
        assert len(AUTHENTICATED_SELECTORS) >= 3

    def test_authenticated_selectors_include_profile_photo(self) -> None:
        photo_selectors = [s for s in AUTHENTICATED_SELECTORS if "photo" in s]
        assert len(photo_selectors) >= 1


# ── Unit Tests: Error Logging ───────────────────────────────────────


class TestErrorLogging:
    def test_log_error_creates_entry(self, watcher: LinkedInWatcher, vault_dir: Path) -> None:
        watcher._log_error("linkedin", "test_error")
        error_logs = list((vault_dir / "Logs" / "errors").glob("*.json"))
        assert len(error_logs) == 1
        data = json.loads(error_logs[0].read_text(encoding="utf-8"))
        entry = data["entries"][0]
        assert entry["actor"] == "linkedin_watcher"
        assert entry["error"] == "test_error"
        assert entry["result"] == "failure"

    def test_log_error_includes_consecutive_count(
        self, watcher: LinkedInWatcher, vault_dir: Path
    ) -> None:
        watcher._consecutive_errors = 3
        watcher._log_error("linkedin", "repeated_error")
        error_logs = list((vault_dir / "Logs" / "errors").glob("*.json"))
        data = json.loads(error_logs[0].read_text(encoding="utf-8"))
        entry = data["entries"][0]
        assert entry["details"]["consecutive_errors"] == 3


# ── Unit Tests: Watcher Init ───────────────────────────────────────


class TestWatcherInit:
    def test_default_keywords(self, vault_dir: Path) -> None:
        w = LinkedInWatcher(vault_path=str(vault_dir))
        assert "urgent" in w.keywords
        assert "invoice" in w.keywords
        assert "opportunity" in w.keywords
        assert len(w.keywords) == 8

    def test_custom_keywords(self, vault_dir: Path) -> None:
        w = LinkedInWatcher(
            vault_path=str(vault_dir),
            keywords=["custom", "words"],
        )
        assert w.keywords == ["custom", "words"]

    def test_paths_set_correctly(self, watcher: LinkedInWatcher, vault_dir: Path) -> None:
        assert watcher.vault_path == vault_dir
        assert watcher.needs_action == vault_dir / "Needs_Action"
        assert watcher.logs_path == vault_dir / "Logs"

    def test_dry_run_flag(self, dry_run_watcher: LinkedInWatcher) -> None:
        assert dry_run_watcher.dry_run is True

    def test_dev_mode_flag(self, watcher: LinkedInWatcher) -> None:
        assert watcher.dev_mode is True

    def test_processed_ids_path(self, watcher: LinkedInWatcher, vault_dir: Path) -> None:
        assert watcher.processed_ids_path == vault_dir / "Logs" / "processed_linkedin.json"
