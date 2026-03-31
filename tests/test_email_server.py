"""Tests for email MCP server tools (backend.mcp_servers.email_server)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.mcp_servers.email_server import redact_email

# ── Helper Tests ────────────────────────────────────────────────────


class TestRedactEmail:
    """Tests for the redact_email helper."""

    def test_redacts_normal_email(self) -> None:
        assert redact_email("john@example.com") == "j***@example.com"

    def test_redacts_short_local(self) -> None:
        assert redact_email("a@example.com") == "a***@example.com"

    def test_redacts_no_at(self) -> None:
        assert redact_email("not-an-email") == "***"

    def test_redacts_empty(self) -> None:
        assert redact_email("") == "***"


# ── Tool Tests (via direct function calls) ──────────────────────────
# These test the tool functions by mocking the AppContext and
# calling them as regular async functions.


@pytest.fixture()
def mock_app():
    """Create a mock AppContext for tool testing."""
    app = MagicMock()
    app.gmail = MagicMock()
    app.rate_limiter = MagicMock()
    app.rate_limiter.check.return_value = (True, 0)
    app.rate_limiter.max_sends = 10
    return app


@pytest.fixture()
def mock_context(mock_app):
    """Set up mocked MCP context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = mock_app
    return ctx


class TestSearchEmailTool:
    """Tests for the search_email tool."""

    async def test_search_returns_formatted_results(self, mock_app, mock_context) -> None:
        """Search tool formats results correctly."""
        mock_app.gmail.search_messages.return_value = [
            {
                "message_id": "m1",
                "thread_id": "t1",
                "from_address": "sender@example.com",
                "to_address": "me@example.com",
                "subject": "Test Invoice",
                "snippet": "Please find attached...",
                "date": "Mon, 10 Feb 2026",
            }
        ]

        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import search_email

            result = await search_email("invoice", 5)

        assert "Test Invoice" in result
        assert "sender@example.com" in result
        assert "m1" in result

    async def test_search_empty_results(self, mock_app, mock_context) -> None:
        """Search tool returns message for no results."""
        mock_app.gmail.search_messages.return_value = []

        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import search_email

            result = await search_email("nonexistent", 5)

        assert "No emails found matching: nonexistent" in result


class TestDraftEmailTool:
    """Tests for the draft_email tool."""

    async def test_draft_dev_mode(self, mock_app, mock_context) -> None:  # noqa: ARG002
        """Draft tool returns DEV_MODE message when active."""
        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server.DEV_MODE", True),
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import draft_email

            result = await draft_email("to@example.com", "Subject", "Body")

        assert "[DEV_MODE]" in result
        assert "t***@example.com" in result

    async def test_draft_invalid_email(self, mock_app, mock_context) -> None:  # noqa: ARG002
        """Draft tool rejects invalid email address."""
        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import draft_email

            result = await draft_email("not-an-email", "Subject", "Body")

        assert "Invalid email address" in result

    async def test_draft_success(self, mock_app, mock_context) -> None:
        """Draft tool creates draft when not in DEV_MODE."""
        mock_app.gmail.create_draft.return_value = {
            "draft_id": "d123",
            "message_id": "m456",
        }

        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server.DEV_MODE", False),
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import draft_email

            result = await draft_email("to@example.com", "Subject", "Body")

        assert "Draft created successfully" in result
        assert "d123" in result


class TestSendEmailTool:
    """Tests for the send_email tool."""

    async def test_send_dev_mode(self, mock_app, mock_context) -> None:  # noqa: ARG002
        """Send tool returns DEV_MODE message when active."""
        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server.DEV_MODE", True),
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import send_email

            result = await send_email("to@example.com", "Subject", "Body")

        assert "[DEV_MODE]" in result

    async def test_send_no_approval(self, mock_app, mock_context) -> None:  # noqa: ARG002
        """Send tool rejects when no approval file exists."""
        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server.DEV_MODE", False),
            patch("backend.mcp_servers.email_server.find_approval", return_value=None),
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import send_email

            result = await send_email("to@example.com", "Subject", "Body")

        assert "Rejected" in result
        assert "approval" in result.lower()

    async def test_send_rate_limited(self, mock_app, mock_context) -> None:
        """Send tool rejects when rate limited."""
        mock_app.rate_limiter.check.return_value = (False, 600)

        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server.DEV_MODE", False),
            patch(
                "backend.mcp_servers.email_server.find_approval",
                return_value={"path": "/fake/path.md", "type": "email_send"},
            ),
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import send_email

            result = await send_email("to@example.com", "Subject", "Body")

        assert "Rate limit exceeded" in result
        assert "600" in result

    async def test_send_success(self, mock_app, mock_context) -> None:
        """Send tool sends email when approved and under limit."""
        mock_app.gmail.send_message.return_value = {
            "message_id": "sent_123",
            "thread_id": "thread_456",
        }

        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server.DEV_MODE", False),
            patch(
                "backend.mcp_servers.email_server.find_approval",
                return_value={"path": "/fake/path.md", "type": "email_send"},
            ),
            patch("backend.mcp_servers.email_server.consume_approval"),
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import send_email

            result = await send_email("to@example.com", "Subject", "Body")

        assert "sent successfully" in result
        assert "sent_123" in result


class TestReplyEmailTool:
    """Tests for the reply_email tool."""

    async def test_reply_dev_mode(self, mock_app, mock_context) -> None:  # noqa: ARG002
        """Reply tool returns DEV_MODE message when active."""
        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server.DEV_MODE", True),
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import reply_email

            result = await reply_email("thread_1", "msg_1", "Reply body")

        assert "[DEV_MODE]" in result

    async def test_reply_no_approval(self, mock_app, mock_context) -> None:  # noqa: ARG002
        """Reply tool rejects when no approval file exists."""
        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server.DEV_MODE", False),
            patch("backend.mcp_servers.email_server.find_approval", return_value=None),
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import reply_email

            result = await reply_email("thread_1", "msg_1", "Reply body")

        assert "Rejected" in result
        assert "approval" in result.lower()

    async def test_reply_success(self, mock_app, mock_context) -> None:
        """Reply tool sends reply when approved."""
        mock_app.gmail.reply_to_thread.return_value = {
            "message_id": "reply_123",
            "thread_id": "thread_456",
        }

        with (
            patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.email_server.DEV_MODE", False),
            patch(
                "backend.mcp_servers.email_server.find_approval",
                return_value={"path": "/fake/path.md", "type": "email_reply"},
            ),
            patch("backend.mcp_servers.email_server.consume_approval"),
            patch("backend.mcp_servers.email_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context

            from backend.mcp_servers.email_server import reply_email

            result = await reply_email("thread_456", "msg_1", "Reply body")

        assert "sent successfully" in result
        assert "reply_123" in result
