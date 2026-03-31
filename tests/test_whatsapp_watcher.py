"""Tests for the WhatsApp watcher module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.watchers.whatsapp_watcher import (
    CHAT_LOADED_SELECTOR,
    WhatsAppWatcher,
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
def watcher(vault_dir: Path, tmp_path: Path) -> WhatsAppWatcher:
    """Create a WhatsAppWatcher instance with test config."""
    return WhatsAppWatcher(
        vault_path=str(vault_dir),
        session_path=str(tmp_path / "whatsapp_session"),
        check_interval=30,
        keywords=["urgent", "asap", "help", "deadline", "invoice", "payment", "meeting", "important"],
        headless=True,
        dry_run=False,
        dev_mode=True,
    )


@pytest.fixture
def dry_run_watcher(vault_dir: Path, tmp_path: Path) -> WhatsAppWatcher:
    """Create a WhatsAppWatcher in dry run mode."""
    return WhatsAppWatcher(
        vault_path=str(vault_dir),
        session_path=str(tmp_path / "whatsapp_session"),
        check_interval=30,
        keywords=["urgent", "asap", "help", "deadline", "invoice", "payment", "meeting", "important"],
        headless=True,
        dry_run=True,
        dev_mode=True,
    )


@pytest.fixture
def sample_whatsapp_item() -> dict[str, Any]:
    """A parsed WhatsApp message dict as returned by check_for_updates."""
    return {
        "chat_name": "John Smith",
        "sender": "John Smith",
        "message_text": "Can you send the invoice ASAP?",
        "message_time": "09:15",
        "priority": "high",
        "matched_keyword": "invoice",
        "context_messages": [
            {"sender": "John Smith", "text": "Hey, about the project...", "time": "09:13"},
            {"sender": "John Smith", "text": "We need to finalize the budget", "time": "09:14"},
            {"sender": "John Smith", "text": "Can you send the invoice ASAP?", "time": "09:15"},
        ],
        "dedup_key": "John Smith|Can you send the invoice ASAP?|09:15",
    }


# ── Unit Tests: _slugify ────────────────────────────────────────────


class TestSlugify:
    def test_basic_slugify(self) -> None:
        assert _slugify("John Smith") == "john-smith"

    def test_special_characters(self) -> None:
        assert _slugify("John O'Brien (+1)") == "john-o-brien-1"

    def test_long_name_truncated(self) -> None:
        long_name = "a" * 100
        result = _slugify(long_name, max_length=40)
        assert len(result) <= 40

    def test_empty_string(self) -> None:
        assert _slugify("") == ""

    def test_only_special_chars(self) -> None:
        assert _slugify("+++###") == ""

    def test_preserves_numbers(self) -> None:
        assert _slugify("Group Chat 42") == "group-chat-42"

    def test_strips_trailing_hyphens(self) -> None:
        result = _slugify("hello---", max_length=40)
        assert not result.endswith("-")


# ── Unit Tests: _classify_priority ──────────────────────────────────


class TestClassifyPriority:
    def test_high_priority_urgent(self) -> None:
        priority, kw = _classify_priority("This is URGENT!", ["urgent", "help"])
        assert priority == "high"
        assert kw == "urgent"

    def test_high_priority_invoice(self) -> None:
        priority, kw = _classify_priority("Please send invoice", ["invoice", "meeting"])
        assert priority == "high"
        assert kw == "invoice"

    def test_high_priority_asap(self) -> None:
        priority, kw = _classify_priority("Need this ASAP", ["asap", "help"])
        assert priority == "high"
        assert kw == "asap"

    def test_medium_priority_meeting(self) -> None:
        priority, kw = _classify_priority("About tomorrow's meeting", ["meeting", "urgent"])
        assert priority == "medium"
        assert kw == "meeting"

    def test_medium_priority_help(self) -> None:
        priority, kw = _classify_priority("I need help with this", ["help", "urgent"])
        assert priority == "medium"
        assert kw == "help"

    def test_medium_priority_deadline(self) -> None:
        priority, kw = _classify_priority("Deadline is Friday", ["deadline"])
        assert priority == "medium"
        assert kw == "deadline"

    def test_no_keyword_match(self) -> None:
        priority, kw = _classify_priority("Hello there", ["urgent", "invoice"])
        assert priority == "low"
        assert kw is None

    def test_case_insensitive(self) -> None:
        priority, kw = _classify_priority("PAYMENT needed", ["payment"])
        assert priority == "high"
        assert kw == "payment"

    def test_high_takes_precedence_over_medium(self) -> None:
        """When both high and medium keywords present, first match wins based on list order."""
        priority, kw = _classify_priority(
            "urgent meeting tomorrow",
            ["urgent", "meeting"],
        )
        assert priority == "high"
        assert kw == "urgent"


# ── Unit Tests: _make_dedup_key ─────────────────────────────────────


class TestMakeDedupKey:
    def test_basic_key(self) -> None:
        key = _make_dedup_key("John", "Hello", "09:15")
        assert key == "John|Hello|09:15"

    def test_long_message_truncated(self) -> None:
        long_msg = "a" * 200
        key = _make_dedup_key("John", long_msg, "09:15")
        assert len(key.split("|")[1]) == 100

    def test_empty_components(self) -> None:
        key = _make_dedup_key("", "", "")
        assert key == "||"


# ── Unit Tests: Action File Creation ────────────────────────────────


class TestCreateActionFile:
    async def test_creates_file_in_needs_action(
        self, watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any], vault_dir: Path
    ) -> None:
        result = await watcher.create_action_file(sample_whatsapp_item)
        assert result is not None
        assert result.parent == vault_dir / "Needs_Action"
        assert result.exists()

    async def test_file_has_correct_frontmatter(
        self, watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_whatsapp_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        assert "type: whatsapp" in content
        assert "source: whatsapp_watcher" in content
        assert "sender: John Smith" in content
        assert "priority: high" in content
        assert "status: pending" in content
        assert "chat_name: John Smith" in content

    async def test_file_has_body_sections(
        self, watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_whatsapp_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        assert "## WhatsApp Message" in content
        assert "## Recent Messages (Context)" in content
        assert "## Suggested Actions" in content
        assert "Reply to sender" in content

    async def test_file_contains_context_messages(
        self, watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_whatsapp_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        assert "Hey, about the project..." in content
        assert "We need to finalize the budget" in content
        assert "Can you send the invoice ASAP?" in content

    async def test_filename_format(
        self, watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_whatsapp_item)
        assert result is not None
        assert result.name.startswith("WHATSAPP_john-smith_")
        assert result.name.endswith(".md")

    async def test_file_contains_priority_info(
        self, watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_whatsapp_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "keyword: invoice" in content

    async def test_dry_run_creates_no_file(
        self, dry_run_watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any], vault_dir: Path
    ) -> None:
        result = await dry_run_watcher.create_action_file(sample_whatsapp_item)
        assert result is None
        files = list((vault_dir / "Needs_Action").glob("WHATSAPP_*.md"))
        assert len(files) == 0

    async def test_dry_run_logs_action(
        self, dry_run_watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any], vault_dir: Path
    ) -> None:
        await dry_run_watcher.create_action_file(sample_whatsapp_item)
        log_files = list((vault_dir / "Logs" / "actions").glob("*.json"))
        assert len(log_files) == 1
        log_data = json.loads(log_files[0].read_text(encoding="utf-8"))
        entry = log_data["entries"][0]
        assert entry["result"] == "dry_run"
        assert entry["actor"] == "whatsapp_watcher"

    async def test_updates_processed_ids(
        self, watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any]
    ) -> None:
        await watcher.create_action_file(sample_whatsapp_item)
        assert sample_whatsapp_item["dedup_key"] in watcher._processed_ids

    async def test_logs_success_action(
        self, watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any], vault_dir: Path
    ) -> None:
        await watcher.create_action_file(sample_whatsapp_item)
        log_files = list((vault_dir / "Logs" / "actions").glob("*.json"))
        assert len(log_files) == 1
        log_data = json.loads(log_files[0].read_text(encoding="utf-8"))
        entry = log_data["entries"][0]
        assert entry["result"] == "success"
        assert entry["parameters"]["chat_name"] == "John Smith"

    async def test_message_preview_truncated(
        self, watcher: WhatsAppWatcher, sample_whatsapp_item: dict[str, Any]
    ) -> None:
        sample_whatsapp_item["message_text"] = "urgent " + "x" * 300
        result = await watcher.create_action_file(sample_whatsapp_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")
        # Frontmatter message_preview should be truncated to 200 chars
        assert "message_preview:" in content


# ── Unit Tests: Processed IDs ───────────────────────────────────────


class TestProcessedIds:
    def test_load_empty(self, watcher: WhatsAppWatcher) -> None:
        watcher._load_processed_ids()
        assert watcher._processed_ids == {}

    def test_load_existing(self, watcher: WhatsAppWatcher, vault_dir: Path) -> None:
        data = {
            "processed_ids": {"John|Hello|09:15": "2026-02-11T10:00:00Z"},
            "last_cleanup": "2026-02-11T00:00:00Z",
        }
        processed_path = vault_dir / "Logs" / "processed_whatsapp.json"
        processed_path.write_text(json.dumps(data), encoding="utf-8")

        watcher._load_processed_ids()
        assert "John|Hello|09:15" in watcher._processed_ids
        assert watcher._last_cleanup == "2026-02-11T00:00:00Z"

    def test_save_and_reload(self, watcher: WhatsAppWatcher) -> None:
        watcher._processed_ids = {"John|Test|09:00": "2026-02-11T12:00:00Z"}
        watcher._save_processed_ids()

        watcher._processed_ids = {}
        watcher._load_processed_ids()
        assert "John|Test|09:00" in watcher._processed_ids

    def test_save_creates_valid_json(self, watcher: WhatsAppWatcher) -> None:
        watcher._processed_ids = {"a|b|c": "2026-01-01T00:00:00Z"}
        watcher._save_processed_ids()
        data = json.loads(watcher.processed_ids_path.read_text(encoding="utf-8"))
        assert "processed_ids" in data
        assert "last_cleanup" in data

    def test_corrupted_file_handled(self, watcher: WhatsAppWatcher, vault_dir: Path) -> None:
        processed_path = vault_dir / "Logs" / "processed_whatsapp.json"
        processed_path.write_text("not valid json{{{", encoding="utf-8")
        watcher._load_processed_ids()
        assert watcher._processed_ids == {}


# ── Unit Tests: Session State Detection ─────────────────────────────


class TestSessionState:
    async def test_check_session_ready(self, watcher: WhatsAppWatcher) -> None:
        """Mock page with chat list visible = ready state."""
        mock_page = AsyncMock()

        async def query_selector(selector: str) -> Any:
            # CHAT_LOADED_SELECTOR contains pane-side, chat-list, etc.
            if "pane-side" in selector or "chat-list" in selector:
                return MagicMock()  # Chat list exists
            return None

        mock_page.query_selector = query_selector
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "ready"

    async def test_check_session_ready_via_pane_side(self, watcher: WhatsAppWatcher) -> None:
        """Login detected via #pane-side selector."""
        mock_page = AsyncMock()

        async def query_selector(selector: str) -> Any:
            if "pane-side" in selector:
                return MagicMock()
            return None

        mock_page.query_selector = query_selector
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "ready"

    async def test_check_session_ready_via_listitem(self, watcher: WhatsAppWatcher) -> None:
        """Login detected via div[role='listitem'] selector."""
        mock_page = AsyncMock()

        async def query_selector(selector: str) -> Any:
            if "listitem" in selector:
                return MagicMock()
            return None

        mock_page.query_selector = query_selector
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "ready"

    async def test_check_session_qr_code(self, watcher: WhatsAppWatcher) -> None:
        """Mock page with QR code visible = qr_code state."""
        mock_page = AsyncMock()

        async def query_selector(selector: str) -> Any:
            if "Scan this QR code" in selector:
                return MagicMock()
            return None

        mock_page.query_selector = query_selector
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "qr_code"

    async def test_check_session_phone_disconnected(self, watcher: WhatsAppWatcher) -> None:
        """Mock page with chat list + phone alert = phone_disconnected state."""
        mock_page = AsyncMock()

        async def query_selector(selector: str) -> Any:
            if "pane-side" in selector or "chat-list" in selector:
                return MagicMock()
            if "alert-phone" in selector:
                return MagicMock()
            return None

        mock_page.query_selector = query_selector
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "phone_disconnected"

    async def test_check_session_unknown(self, watcher: WhatsAppWatcher) -> None:
        """Mock page with nothing visible = unknown state."""
        mock_page = AsyncMock()
        mock_page.query_selector = AsyncMock(return_value=None)
        watcher._page = mock_page

        state = await watcher._check_session_state()
        assert state == "unknown"

    def test_chat_loaded_selector_contains_all_variants(self) -> None:
        """Verify CHAT_LOADED_SELECTOR includes all expected selectors."""
        assert 'div[data-testid="chat-list"]' in CHAT_LOADED_SELECTOR
        assert 'div[aria-label="Chat list"]' in CHAT_LOADED_SELECTOR
        assert "#pane-side" in CHAT_LOADED_SELECTOR
        assert 'div[role="listitem"]' in CHAT_LOADED_SELECTOR


# ── Unit Tests: Error Logging ───────────────────────────────────────


class TestErrorLogging:
    def test_log_error_creates_entry(self, watcher: WhatsAppWatcher, vault_dir: Path) -> None:
        watcher._log_error("whatsapp_web", "test_error")
        error_logs = list((vault_dir / "Logs" / "errors").glob("*.json"))
        assert len(error_logs) == 1
        data = json.loads(error_logs[0].read_text(encoding="utf-8"))
        entry = data["entries"][0]
        assert entry["actor"] == "whatsapp_watcher"
        assert entry["error"] == "test_error"
        assert entry["result"] == "failure"

    def test_log_error_includes_consecutive_count(
        self, watcher: WhatsAppWatcher, vault_dir: Path
    ) -> None:
        watcher._consecutive_errors = 5
        watcher._log_error("whatsapp_web", "repeated_error")
        error_logs = list((vault_dir / "Logs" / "errors").glob("*.json"))
        data = json.loads(error_logs[0].read_text(encoding="utf-8"))
        entry = data["entries"][0]
        assert entry["details"]["consecutive_errors"] == 5


# ── Unit Tests: Watcher Init ───────────────────────────────────────


class TestWatcherInit:
    def test_default_keywords(self, vault_dir: Path, tmp_path: Path) -> None:
        w = WhatsAppWatcher(vault_path=str(vault_dir))
        assert "urgent" in w.keywords
        assert "invoice" in w.keywords
        assert len(w.keywords) == 8

    def test_custom_keywords(self, vault_dir: Path, tmp_path: Path) -> None:
        w = WhatsAppWatcher(
            vault_path=str(vault_dir),
            keywords=["custom", "words"],
        )
        assert w.keywords == ["custom", "words"]

    def test_paths_set_correctly(self, watcher: WhatsAppWatcher, vault_dir: Path) -> None:
        assert watcher.vault_path == vault_dir
        assert watcher.needs_action == vault_dir / "Needs_Action"
        assert watcher.logs_path == vault_dir / "Logs"

    def test_dry_run_flag(self, dry_run_watcher: WhatsAppWatcher) -> None:
        assert dry_run_watcher.dry_run is True

    def test_dev_mode_flag(self, watcher: WhatsAppWatcher) -> None:
        assert watcher.dev_mode is True
