"""Tests for the Gmail watcher module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from backend.watchers.gmail_watcher import (
    GmailWatcher,
    _get_header,
    _load_gmail_config,
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
def gmail_config() -> dict[str, Any]:
    """Standard Gmail config for testing."""
    return {
        "query": "is:unread is:important",
        "priority_keywords": {
            "high": ["urgent", "asap", "critical", "payment", "invoice"],
            "medium": ["important", "request", "review", "deadline"],
            "low": [],
        },
        "exclude_senders": ["noreply@", "newsletter@", "no-reply@"],
        "max_results": 10,
        "poll_interval_seconds": 120,
        "processed_ids_retention_days": 30,
        "snippet_max_length": 1000,
    }


@pytest.fixture
def watcher(vault_dir: Path, gmail_config: dict[str, Any]) -> GmailWatcher:
    """Create a GmailWatcher instance with test config."""
    return GmailWatcher(
        vault_path=str(vault_dir),
        credentials_path="config/credentials.json",
        token_path="config/token.json",
        check_interval=60,
        gmail_config=gmail_config,
        dry_run=False,
        dev_mode=True,
    )


@pytest.fixture
def dry_run_watcher(vault_dir: Path, gmail_config: dict[str, Any]) -> GmailWatcher:
    """Create a GmailWatcher in dry run mode."""
    return GmailWatcher(
        vault_path=str(vault_dir),
        credentials_path="config/credentials.json",
        token_path="config/token.json",
        check_interval=60,
        gmail_config=gmail_config,
        dry_run=True,
        dev_mode=True,
    )


@pytest.fixture
def sample_email_item() -> dict[str, Any]:
    """A parsed email dict as returned by check_for_updates."""
    return {
        "message_id": "msg_abc123",
        "thread_id": "thread_xyz789",
        "from": "sender@example.com",
        "to": "user@gmail.com",
        "subject": "Invoice for January",
        "received": "2026-01-07T10:30:00Z",
        "snippet": "Please review the attached invoice for January services.",
        "labels": ["INBOX", "IMPORTANT", "UNREAD"],
        "priority": "high",
    }


@pytest.fixture
def sample_gmail_message() -> dict[str, Any]:
    """A raw Gmail API message response."""
    return {
        "id": "msg_abc123",
        "threadId": "thread_xyz789",
        "snippet": "Please review the attached invoice for January services.",
        "labelIds": ["INBOX", "IMPORTANT", "UNREAD"],
        "payload": {
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "user@gmail.com"},
                {"name": "Subject", "value": "Invoice for January"},
                {"name": "Date", "value": "Mon, 7 Jan 2026 10:30:00 +0000"},
            ],
        },
    }


# ── Unit Tests: _slugify ────────────────────────────────────────────


class TestSlugify:
    def test_basic_slugify(self) -> None:
        assert _slugify("Hello World") == "hello-world"

    def test_special_characters(self) -> None:
        assert _slugify("RE: Invoice #123!") == "re-invoice-123"

    def test_long_subject_truncated(self) -> None:
        long_text = "a" * 100
        result = _slugify(long_text, max_length=50)
        assert len(result) <= 50

    def test_empty_string(self) -> None:
        assert _slugify("") == ""

    def test_only_special_chars(self) -> None:
        assert _slugify("!!!###") == ""

    def test_preserves_numbers(self) -> None:
        assert _slugify("Task 42 urgent") == "task-42-urgent"

    def test_strips_trailing_hyphens(self) -> None:
        result = _slugify("hello---", max_length=50)
        assert not result.endswith("-")


# ── Unit Tests: _get_header ─────────────────────────────────────────


class TestGetHeader:
    def test_finds_header(self) -> None:
        headers = [
            {"name": "From", "value": "sender@example.com"},
            {"name": "Subject", "value": "Test"},
        ]
        assert _get_header(headers, "From") == "sender@example.com"

    def test_case_insensitive(self) -> None:
        headers = [{"name": "SUBJECT", "value": "Test"}]
        assert _get_header(headers, "subject") == "Test"

    def test_missing_header(self) -> None:
        headers = [{"name": "From", "value": "test@test.com"}]
        assert _get_header(headers, "Subject") == ""

    def test_empty_headers(self) -> None:
        assert _get_header([], "From") == ""


# ── Unit Tests: Priority Classification ─────────────────────────────


class TestClassifyPriority:
    def test_high_priority_urgent(self, watcher: GmailWatcher) -> None:
        assert watcher._classify_priority("URGENT: Review needed", "") == "high"

    def test_high_priority_invoice(self, watcher: GmailWatcher) -> None:
        assert watcher._classify_priority("Invoice for January", "") == "high"

    def test_high_priority_in_snippet(self, watcher: GmailWatcher) -> None:
        assert watcher._classify_priority("Hello", "this is urgent please") == "high"

    def test_medium_priority_review(self, watcher: GmailWatcher) -> None:
        assert watcher._classify_priority("Please review this document", "") == "medium"

    def test_medium_priority_deadline(self, watcher: GmailWatcher) -> None:
        assert watcher._classify_priority("", "the deadline is tomorrow") == "medium"

    def test_low_priority_default(self, watcher: GmailWatcher) -> None:
        assert watcher._classify_priority("Hello there", "How are you?") == "low"

    def test_case_insensitive(self, watcher: GmailWatcher) -> None:
        assert watcher._classify_priority("PAYMENT Required", "") == "high"

    def test_high_takes_precedence(self, watcher: GmailWatcher) -> None:
        """When both high and medium keywords present, high wins."""
        assert watcher._classify_priority("urgent review needed", "") == "high"


# ── Unit Tests: Sender Filtering ────────────────────────────────────


class TestSenderFiltering:
    def test_exclude_noreply(self) -> None:
        assert GmailWatcher._is_excluded_sender("noreply@company.com", ["noreply@"])

    def test_exclude_newsletter(self) -> None:
        assert GmailWatcher._is_excluded_sender("newsletter@site.com", ["newsletter@"])

    def test_include_regular_sender(self) -> None:
        assert not GmailWatcher._is_excluded_sender("john@company.com", ["noreply@", "newsletter@"])

    def test_case_insensitive(self) -> None:
        assert GmailWatcher._is_excluded_sender("NoReply@company.com", ["noreply@"])

    def test_empty_exclude_list(self) -> None:
        assert not GmailWatcher._is_excluded_sender("anyone@example.com", [])

    def test_partial_match(self) -> None:
        assert GmailWatcher._is_excluded_sender("Some Name <no-reply@company.com>", ["no-reply@"])


# ── Unit Tests: Action File Creation ────────────────────────────────


class TestCreateActionFile:
    async def test_creates_file_in_needs_action(
        self, watcher: GmailWatcher, sample_email_item: dict[str, Any], vault_dir: Path
    ) -> None:
        result = await watcher.create_action_file(sample_email_item)
        assert result is not None
        assert result.parent == vault_dir / "Needs_Action"
        assert result.exists()

    async def test_file_has_correct_frontmatter(
        self, watcher: GmailWatcher, sample_email_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_email_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        assert "type: email" in content
        assert "source: gmail_watcher" in content
        assert "from: sender@example.com" in content
        assert "subject: Invoice for January" in content
        assert "priority: high" in content
        assert "status: pending" in content
        assert "message_id: msg_abc123" in content
        assert "thread_id: thread_xyz789" in content

    async def test_file_has_body_sections(
        self, watcher: GmailWatcher, sample_email_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_email_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")

        assert "## Email Content" in content
        assert "## Metadata" in content
        assert "## Suggested Actions" in content
        assert "Reply to sender" in content

    async def test_file_contains_snippet(
        self, watcher: GmailWatcher, sample_email_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_email_item)
        assert result is not None
        content = result.read_text(encoding="utf-8")
        assert "Please review the attached invoice" in content

    async def test_filename_format(
        self, watcher: GmailWatcher, sample_email_item: dict[str, Any]
    ) -> None:
        result = await watcher.create_action_file(sample_email_item)
        assert result is not None
        assert result.name.startswith("email-invoice-for-january-")
        assert result.name.endswith(".md")

    async def test_dry_run_creates_no_file(
        self, dry_run_watcher: GmailWatcher, sample_email_item: dict[str, Any], vault_dir: Path
    ) -> None:
        result = await dry_run_watcher.create_action_file(sample_email_item)
        assert result is None
        files = list((vault_dir / "Needs_Action").glob("email-*.md"))
        assert len(files) == 0

    async def test_dry_run_logs_action(
        self, dry_run_watcher: GmailWatcher, sample_email_item: dict[str, Any], vault_dir: Path
    ) -> None:
        await dry_run_watcher.create_action_file(sample_email_item)
        log_files = list((vault_dir / "Logs" / "actions").glob("*.json"))
        assert len(log_files) == 1
        log_data = json.loads(log_files[0].read_text(encoding="utf-8"))
        entry = log_data["entries"][0]
        assert entry["result"] == "dry_run"
        assert entry["actor"] == "gmail_watcher"

    async def test_updates_processed_ids(
        self, watcher: GmailWatcher, sample_email_item: dict[str, Any]
    ) -> None:
        await watcher.create_action_file(sample_email_item)
        assert "msg_abc123" in watcher._processed_ids

    async def test_logs_success_action(
        self, watcher: GmailWatcher, sample_email_item: dict[str, Any], vault_dir: Path
    ) -> None:
        await watcher.create_action_file(sample_email_item)
        log_files = list((vault_dir / "Logs" / "actions").glob("*.json"))
        assert len(log_files) == 1
        log_data = json.loads(log_files[0].read_text(encoding="utf-8"))
        entry = log_data["entries"][0]
        assert entry["result"] == "success"
        assert entry["parameters"]["message_id"] == "msg_abc123"


# ── Unit Tests: Processed IDs ───────────────────────────────────────


class TestProcessedIds:
    def test_load_empty(self, watcher: GmailWatcher) -> None:
        watcher._load_processed_ids()
        assert watcher._processed_ids == {}

    def test_load_existing(self, watcher: GmailWatcher, vault_dir: Path) -> None:
        data = {
            "processed_ids": {"msg_1": "2026-01-07T10:00:00Z"},
            "last_cleanup": "2026-01-07T00:00:00Z",
        }
        processed_path = vault_dir / "Logs" / "processed_emails.json"
        processed_path.write_text(json.dumps(data), encoding="utf-8")

        watcher._load_processed_ids()
        assert "msg_1" in watcher._processed_ids
        assert watcher._last_cleanup == "2026-01-07T00:00:00Z"

    def test_save_and_reload(self, watcher: GmailWatcher) -> None:
        watcher._processed_ids = {"msg_test": "2026-01-07T12:00:00Z"}
        watcher._save_processed_ids()

        watcher._processed_ids = {}
        watcher._load_processed_ids()
        assert "msg_test" in watcher._processed_ids

    def test_save_creates_valid_json(self, watcher: GmailWatcher) -> None:
        watcher._processed_ids = {"a": "2026-01-01T00:00:00Z"}
        watcher._save_processed_ids()
        data = json.loads(watcher.processed_ids_path.read_text(encoding="utf-8"))
        assert "processed_ids" in data
        assert "last_cleanup" in data

    def test_corrupted_file_handled(self, watcher: GmailWatcher, vault_dir: Path) -> None:
        processed_path = vault_dir / "Logs" / "processed_emails.json"
        processed_path.write_text("not valid json{{{", encoding="utf-8")
        watcher._load_processed_ids()
        assert watcher._processed_ids == {}


# ── Unit Tests: Config Loading ──────────────────────────────────────


class TestLoadConfig:
    def test_missing_config_returns_empty(self, tmp_path: Path) -> None:
        result = _load_gmail_config(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_valid_config(self, tmp_path: Path) -> None:
        config = {"query": "is:unread", "max_results": 5}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")
        result = _load_gmail_config(str(config_file))
        assert result["query"] == "is:unread"
        assert result["max_results"] == 5


# ── Integration Tests: Mock Gmail API ───────────────────────────────


class TestCheckForUpdatesIntegration:
    def _build_mock_service(
        self, messages: list[dict[str, Any]], full_messages: dict[str, dict[str, Any]]
    ) -> MagicMock:
        """Build a mock Gmail API service."""
        service = MagicMock()
        users = service.users.return_value
        messages_api = users.messages.return_value

        # Mock list response
        list_execute = MagicMock(return_value={"messages": messages})
        messages_api.list.return_value.execute = list_execute

        # Mock get response (per message ID)
        def get_side_effect(**kwargs: Any) -> MagicMock:
            mock = MagicMock()
            mock.execute.return_value = full_messages.get(kwargs.get("id", ""), {})
            return mock

        messages_api.get.side_effect = get_side_effect

        return service

    async def test_fetches_and_parses_emails(
        self, watcher: GmailWatcher, sample_gmail_message: dict[str, Any]
    ) -> None:
        messages = [{"id": "msg_abc123"}]
        full_messages = {"msg_abc123": sample_gmail_message}

        watcher.service = self._build_mock_service(messages, full_messages)

        items = await watcher.check_for_updates()
        assert len(items) == 1
        assert items[0]["message_id"] == "msg_abc123"
        assert items[0]["from"] == "sender@example.com"
        assert items[0]["subject"] == "Invoice for January"
        assert items[0]["priority"] == "high"

    async def test_empty_inbox(self, watcher: GmailWatcher) -> None:
        watcher.service = self._build_mock_service([], {})
        items = await watcher.check_for_updates()
        assert items == []

    async def test_skips_already_processed(
        self, watcher: GmailWatcher, sample_gmail_message: dict[str, Any]
    ) -> None:
        # Write processed IDs to disk so _load_processed_ids picks them up
        watcher._processed_ids = {"msg_abc123": "2026-01-07T10:00:00Z"}
        watcher._save_processed_ids()

        messages = [{"id": "msg_abc123"}]
        full_messages = {"msg_abc123": sample_gmail_message}
        watcher.service = self._build_mock_service(messages, full_messages)

        items = await watcher.check_for_updates()
        assert len(items) == 0

    async def test_skips_excluded_senders(self, watcher: GmailWatcher) -> None:
        noreply_msg = {
            "id": "msg_noreply",
            "threadId": "thread_1",
            "snippet": "Automated notification",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "noreply@company.com"},
                    {"name": "Subject", "value": "Notification"},
                    {"name": "To", "value": "user@gmail.com"},
                    {"name": "Date", "value": "Mon, 7 Jan 2026 10:00:00 +0000"},
                ],
            },
        }
        messages = [{"id": "msg_noreply"}]
        full_messages = {"msg_noreply": noreply_msg}
        watcher.service = self._build_mock_service(messages, full_messages)

        items = await watcher.check_for_updates()
        assert len(items) == 0

    async def test_multiple_emails(self, watcher: GmailWatcher) -> None:
        msg1 = {
            "id": "msg_1",
            "threadId": "t1",
            "snippet": "Urgent matter",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "alice@company.com"},
                    {"name": "Subject", "value": "Urgent: Contract"},
                    {"name": "To", "value": "user@gmail.com"},
                    {"name": "Date", "value": "Mon, 7 Jan 2026 10:00:00 +0000"},
                ],
            },
        }
        msg2 = {
            "id": "msg_2",
            "threadId": "t2",
            "snippet": "Regular message",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "bob@company.com"},
                    {"name": "Subject", "value": "Hello"},
                    {"name": "To", "value": "user@gmail.com"},
                    {"name": "Date", "value": "Mon, 7 Jan 2026 11:00:00 +0000"},
                ],
            },
        }
        messages = [{"id": "msg_1"}, {"id": "msg_2"}]
        full_messages = {"msg_1": msg1, "msg_2": msg2}
        watcher.service = self._build_mock_service(messages, full_messages)

        items = await watcher.check_for_updates()
        assert len(items) == 2
        assert items[0]["priority"] == "high"  # "urgent" keyword
        assert items[1]["priority"] == "low"  # no keywords

    async def test_full_cycle_dry_run(
        self,
        dry_run_watcher: GmailWatcher,
        sample_gmail_message: dict[str, Any],
        vault_dir: Path,
    ) -> None:
        messages = [{"id": "msg_abc123"}]
        full_messages = {"msg_abc123": sample_gmail_message}
        dry_run_watcher.service = self._build_mock_service(messages, full_messages)

        items = await dry_run_watcher.check_for_updates()
        for item in items:
            await dry_run_watcher.create_action_file(item)

        # No action files created
        action_files = list((vault_dir / "Needs_Action").glob("email-*.md"))
        assert len(action_files) == 0

        # But log was written
        log_files = list((vault_dir / "Logs" / "actions").glob("*.json"))
        assert len(log_files) == 1

    async def test_full_cycle_creates_file(
        self,
        watcher: GmailWatcher,
        sample_gmail_message: dict[str, Any],
        vault_dir: Path,
    ) -> None:
        messages = [{"id": "msg_abc123"}]
        full_messages = {"msg_abc123": sample_gmail_message}
        watcher.service = self._build_mock_service(messages, full_messages)

        items = await watcher.check_for_updates()
        for item in items:
            await watcher.create_action_file(item)

        action_files = list((vault_dir / "Needs_Action").glob("email-*.md"))
        assert len(action_files) == 1

        content = action_files[0].read_text(encoding="utf-8")
        assert "Invoice for January" in content
        assert "sender@example.com" in content


# ── Integration Tests: Error Handling ───────────────────────────────


class TestErrorHandling:
    async def test_rate_limit_retries(self, watcher: GmailWatcher) -> None:
        """Mock a 429 response and verify retry behavior."""
        mock_resp = MagicMock()
        mock_resp.status = 429
        http_error = HttpError(resp=mock_resp, content=b"Rate limit exceeded")

        call_count = 0

        def side_effect(**_kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count <= 2:
                mock.execute.side_effect = http_error
            else:
                mock.execute.return_value = {"messages": []}
            return mock

        service = MagicMock()
        service.users.return_value.messages.return_value.list.side_effect = side_effect
        watcher.service = service
        watcher._backoff_delay = 0.01  # Speed up test

        items = await watcher.check_for_updates()
        assert items == []
        assert call_count == 3  # 2 failures + 1 success

    async def test_auth_error_triggers_reauth(self, watcher: GmailWatcher) -> None:
        """Mock a 401 and verify token refresh is attempted."""
        mock_resp = MagicMock()
        mock_resp.status = 401
        http_error = HttpError(resp=mock_resp, content=b"Unauthorized")

        call_count = 0

        def list_side_effect(**_kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock = MagicMock()
            if call_count == 1:
                mock.execute.side_effect = http_error
            else:
                mock.execute.return_value = {"messages": []}
            return mock

        service = MagicMock()
        service.users.return_value.messages.return_value.list.side_effect = list_side_effect
        watcher.service = service

        with patch.object(watcher, "_authenticate") as mock_auth:
            await watcher.check_for_updates()

        mock_auth.assert_called()

    async def test_network_error_returns_empty(self, watcher: GmailWatcher) -> None:
        """Network errors should not crash, return empty list."""
        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
            ConnectionError("Network unreachable")
        )
        watcher.service = service
        watcher._backoff_delay = 0.01

        items = await watcher.check_for_updates()
        assert items == []
        assert watcher._consecutive_errors == 1

    async def test_error_logged_to_vault(self, watcher: GmailWatcher, vault_dir: Path) -> None:
        """Errors should be logged to vault/Logs/errors/."""
        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
            ConnectionError("fail")
        )
        watcher.service = service
        watcher._backoff_delay = 0.01

        await watcher.check_for_updates()

        error_logs = list((vault_dir / "Logs" / "errors").glob("*.json"))
        assert len(error_logs) == 1
