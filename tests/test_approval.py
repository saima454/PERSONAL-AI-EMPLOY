"""Tests for approval module (backend.mcp_servers.approval)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.mcp_servers.approval import consume_approval, find_approval


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Create a temporary vault structure."""
    (tmp_path / "Approved").mkdir()
    (tmp_path / "Done").mkdir()
    return tmp_path


def _write_approval(
    vault: Path,
    filename: str,
    type_: str = "email_send",
    status: str = "approved",
    to: str = "john@example.com",
    **extra: str,
) -> Path:
    """Write a mock approval file with YAML frontmatter."""
    fields = {"type": type_, "status": status, "to": to, **extra}
    yaml_lines = [f"{k}: {v}" for k, v in fields.items()]
    content = "---\n" + "\n".join(yaml_lines) + "\n---\n\n## Action Summary\n\nTest approval.\n"
    path = vault / "Approved" / filename
    path.write_text(content, encoding="utf-8")
    return path


class TestFindApproval:
    """Tests for find_approval()."""

    def test_finds_matching_approval(self, vault: Path) -> None:
        """Returns approval when type and to match."""
        _write_approval(vault, "send-john.md", to="john@example.com")

        result = find_approval(str(vault), "email_send", to="john@example.com")

        assert result is not None
        assert result["type"] == "email_send"
        assert result["to"] == "john@example.com"

    def test_returns_none_when_no_match(self, vault: Path) -> None:
        """Returns None when no file matches."""
        _write_approval(vault, "send-john.md", to="john@example.com")

        result = find_approval(str(vault), "email_send", to="jane@example.com")

        assert result is None

    def test_returns_none_when_wrong_type(self, vault: Path) -> None:
        """Returns None when type doesn't match."""
        _write_approval(vault, "send-john.md", type_="email_reply")

        result = find_approval(str(vault), "email_send", to="john@example.com")

        assert result is None

    def test_returns_none_when_not_approved(self, vault: Path) -> None:
        """Returns None when status is not approved."""
        _write_approval(vault, "send-john.md", status="pending")

        result = find_approval(str(vault), "email_send", to="john@example.com")

        assert result is None

    def test_case_insensitive_to_match(self, vault: Path) -> None:
        """Matching is case-insensitive for email addresses."""
        _write_approval(vault, "send-john.md", to="John@Example.com")

        result = find_approval(str(vault), "email_send", to="john@example.com")

        assert result is not None

    def test_most_recent_match_wins(self, vault: Path) -> None:
        """When multiple files match, most recent by approved_at wins."""
        _write_approval(
            vault,
            "send-john-old.md",
            to="john@example.com",
            approved_at="2026-02-10T12:00:00Z",
        )
        _write_approval(
            vault,
            "send-john-new.md",
            to="john@example.com",
            approved_at="2026-02-14T12:00:00Z",
        )

        result = find_approval(str(vault), "email_send", to="john@example.com")

        assert result is not None
        # YAML parses timestamps as datetime objects; compare stringified
        assert str(result["approved_at"]).startswith("2026-02-14")

    def test_returns_none_when_dir_missing(self, tmp_path: Path) -> None:
        """Returns None when Approved directory doesn't exist."""
        result = find_approval(str(tmp_path), "email_send", to="john@example.com")

        assert result is None

    def test_finds_reply_approval_by_thread_id(self, vault: Path) -> None:
        """Finds reply approval matching by thread_id."""
        _write_approval(
            vault,
            "reply-thread.md",
            type_="email_reply",
            thread_id="thread_abc123",
        )

        result = find_approval(str(vault), "email_reply", thread_id="thread_abc123")

        assert result is not None
        assert result["type"] == "email_reply"


class TestConsumeApproval:
    """Tests for consume_approval()."""

    def test_moves_file_to_done(self, vault: Path) -> None:
        """File is moved from Approved to Done."""
        path = _write_approval(vault, "send-john.md")

        consume_approval(path, str(vault))

        assert not (vault / "Approved" / "send-john.md").exists()
        assert (vault / "Done" / "send-john.md").exists()

    def test_creates_done_dir_if_missing(self, tmp_path: Path) -> None:
        """Creates Done directory if it doesn't exist."""
        vault = tmp_path
        (vault / "Approved").mkdir()
        path = _write_approval(vault, "send-john.md")

        # Remove Done dir if it exists
        done_dir = vault / "Done"
        if done_dir.exists():
            done_dir.rmdir()

        consume_approval(path, str(vault))

        assert (vault / "Done" / "send-john.md").exists()
