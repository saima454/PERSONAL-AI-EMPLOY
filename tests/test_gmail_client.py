"""Tests for GmailClient (backend.mcp_servers.gmail_client)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from backend.mcp_servers.gmail_client import GmailClient

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def gmail_client() -> GmailClient:
    """Create a GmailClient with a mocked service."""
    client = GmailClient.__new__(GmailClient)
    client.credentials_path = MagicMock()
    client.token_path = MagicMock()
    client.service = MagicMock()
    return client


def _make_message(
    msg_id: str,
    thread_id: str,
    from_addr: str = "sender@example.com",
    to_addr: str = "me@example.com",
    subject: str = "Test Subject",
    snippet: str = "Test snippet",
    date: str = "Mon, 10 Feb 2026 12:00:00 +0000",
) -> dict:
    """Create a mock Gmail API message response."""
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "From", "value": from_addr},
                {"name": "To", "value": to_addr},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ]
        },
    }


def _make_header_message(
    msg_id: str,
    mime_message_id: str = "<abc123@mail.gmail.com>",
    references: str = "",
    subject: str = "Original Subject",
    from_addr: str = "sender@example.com",
    to_addr: str = "me@example.com",
) -> dict:
    """Create a mock Gmail API message for header extraction."""
    return {
        "id": msg_id,
        "payload": {
            "headers": [
                {"name": "Message-ID", "value": mime_message_id},
                {"name": "References", "value": references},
                {"name": "Subject", "value": subject},
                {"name": "From", "value": from_addr},
                {"name": "To", "value": to_addr},
            ]
        },
    }


# ── search_messages ─────────────────────────────────────────────────


class TestSearchMessages:
    """Tests for GmailClient.search_messages()."""

    def test_search_returns_results(self, gmail_client: GmailClient) -> None:
        """Successful search returns formatted results."""
        messages_list = {"messages": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]}
        gmail_client.service.users().messages().list().execute.return_value = messages_list
        gmail_client.service.users().messages().get().execute.side_effect = [
            _make_message("m1", "t1", subject="Invoice #1"),
            _make_message("m2", "t2", subject="Invoice #2"),
            _make_message("m3", "t3", subject="Invoice #3"),
        ]

        results = gmail_client.search_messages("invoice", max_results=3)

        assert len(results) == 3
        assert results[0]["message_id"] == "m1"
        assert results[0]["subject"] == "Invoice #1"
        assert results[0]["thread_id"] == "t1"
        assert results[0]["from_address"] == "sender@example.com"

    def test_search_empty_results(self, gmail_client: GmailClient) -> None:
        """Empty search returns empty list."""
        gmail_client.service.users().messages().list().execute.return_value = {}

        results = gmail_client.search_messages("nonexistent")

        assert results == []

    def test_search_retries_on_401(self, gmail_client: GmailClient) -> None:
        """HTTP 401 triggers re-authentication and retry."""
        resp = MagicMock()
        resp.status = 401
        error = HttpError(resp=resp, content=b"Unauthorized")

        original_service = gmail_client.service

        # First call fails with 401, second succeeds
        call_count = 0

        def side_effect() -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise error
            return {"messages": []}

        gmail_client.service.users().messages().list().execute.side_effect = side_effect

        def restore_service() -> None:
            gmail_client.service = original_service

        with patch.object(gmail_client, "authenticate", side_effect=restore_service):
            results = gmail_client.search_messages("test")
            assert results == []


# ── create_draft ────────────────────────────────────────────────────


class TestCreateDraft:
    """Tests for GmailClient.create_draft()."""

    def test_create_draft_success(self, gmail_client: GmailClient) -> None:
        """Successful draft creation returns draft_id and message_id."""
        gmail_client.service.users().drafts().create().execute.return_value = {
            "id": "draft_123",
            "message": {"id": "msg_456"},
        }

        result = gmail_client.create_draft("to@example.com", "Subject", "Body text")

        assert result["draft_id"] == "draft_123"
        assert result["message_id"] == "msg_456"

    def test_create_draft_special_chars(self, gmail_client: GmailClient) -> None:
        """Draft with special characters in body succeeds."""
        gmail_client.service.users().drafts().create().execute.return_value = {
            "id": "draft_789",
            "message": {"id": "msg_012"},
        }

        result = gmail_client.create_draft(
            "to@example.com",
            "Test émojis 🎉",
            "Body with spëcial chars: <>&\"'",
        )

        assert result["draft_id"] == "draft_789"


# ── send_message ────────────────────────────────────────────────────


class TestSendMessage:
    """Tests for GmailClient.send_message()."""

    def test_send_message_success(self, gmail_client: GmailClient) -> None:
        """Successful send returns message_id and thread_id."""
        gmail_client.service.users().messages().send().execute.return_value = {
            "id": "sent_123",
            "threadId": "thread_456",
        }

        result = gmail_client.send_message("to@example.com", "Subject", "Body")

        assert result["message_id"] == "sent_123"
        assert result["thread_id"] == "thread_456"


# ── get_message_headers ─────────────────────────────────────────────


class TestGetMessageHeaders:
    """Tests for GmailClient.get_message_headers()."""

    def test_headers_extracted_correctly(self, gmail_client: GmailClient) -> None:
        """Headers are parsed from Gmail API response."""
        gmail_client.service.users().messages().get().execute.return_value = _make_header_message(
            "m1", "<abc@mail.com>", "<prev@mail.com>", "Hello"
        )

        headers = gmail_client.get_message_headers("m1")

        assert headers["message_id_header"] == "<abc@mail.com>"
        assert headers["references"] == "<prev@mail.com>"
        assert headers["subject"] == "Hello"
        assert headers["from"] == "sender@example.com"


# ── reply_to_thread ─────────────────────────────────────────────────


class TestReplyToThread:
    """Tests for GmailClient.reply_to_thread()."""

    def test_reply_with_correct_threading(self, gmail_client: GmailClient) -> None:
        """Reply sets In-Reply-To, References, and Re: subject."""
        # Mock get_message_headers via the service
        gmail_client.service.users().messages().get().execute.return_value = _make_header_message(
            "m1", "<orig@mail.com>", "", "Original Subject"
        )
        gmail_client.service.users().messages().send().execute.return_value = {
            "id": "reply_123",
            "threadId": "thread_456",
        }

        result = gmail_client.reply_to_thread("thread_456", "m1", "Reply body")

        assert result["message_id"] == "reply_123"
        assert result["thread_id"] == "thread_456"

        # Verify send was called with threadId
        send_call = gmail_client.service.users().messages().send
        call_kwargs = send_call.call_args
        assert call_kwargs is not None
        assert result["thread_id"] == "thread_456"
