"""Tests for backend.utils.frontmatter module."""

import tempfile
from pathlib import Path

import pytest

from backend.utils.frontmatter import (
    create_file_with_frontmatter,
    extract_frontmatter,
    format_with_frontmatter,
    parse_frontmatter,
    update_frontmatter,
)


class TestExtractFrontmatter:
    """Tests for extract_frontmatter function."""

    def test_extracts_valid_frontmatter(self) -> None:
        """Should extract YAML frontmatter from markdown content."""
        content = "---\ntype: email\npriority: high\n---\n# Title\n\nBody content"
        frontmatter, body = extract_frontmatter(content)

        assert frontmatter == {"type": "email", "priority": "high"}
        assert body == "# Title\n\nBody content"

    def test_handles_no_frontmatter(self) -> None:
        """Should return empty dict when no frontmatter present."""
        content = "# Title\n\nJust body content"
        frontmatter, body = extract_frontmatter(content)

        assert frontmatter == {}
        assert body == content

    def test_handles_empty_frontmatter(self) -> None:
        """Should handle empty frontmatter block."""
        content = "---\n---\n# Title"
        frontmatter, body = extract_frontmatter(content)

        # Empty frontmatter returns empty dict and original content
        # (edge case - we don't expect empty frontmatter in practice)
        assert frontmatter == {}
        # Body contains everything after extraction attempt
        assert "# Title" in body

    def test_handles_multiline_values(self) -> None:
        """Should handle multiline YAML values."""
        content = "---\ntags:\n  - one\n  - two\n---\n# Title"
        frontmatter, body = extract_frontmatter(content)

        assert frontmatter == {"tags": ["one", "two"]}

    def test_handles_invalid_yaml(self) -> None:
        """Should return empty dict for invalid YAML."""
        content = "---\ninvalid: yaml: content:\n---\n# Title"
        frontmatter, body = extract_frontmatter(content)

        assert frontmatter == {}
        assert body == content


class TestParseFrontmatter:
    """Tests for parse_frontmatter function."""

    def test_parses_file_frontmatter(self, tmp_path: Path) -> None:
        """Should parse frontmatter from a file."""
        test_file = tmp_path / "test.md"
        test_file.write_text("---\ntype: task\n---\n# Task")

        result = parse_frontmatter(test_file)

        assert result == {"type": "task"}

    def test_raises_for_missing_file(self) -> None:
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_frontmatter("/nonexistent/file.md")

    def test_returns_empty_for_no_frontmatter(self, tmp_path: Path) -> None:
        """Should return empty dict for file without frontmatter."""
        test_file = tmp_path / "test.md"
        test_file.write_text("# Just a title")

        result = parse_frontmatter(test_file)

        assert result == {}


class TestUpdateFrontmatter:
    """Tests for update_frontmatter function."""

    def test_updates_existing_fields(self, tmp_path: Path) -> None:
        """Should update existing frontmatter fields."""
        test_file = tmp_path / "test.md"
        test_file.write_text("---\nstatus: pending\npriority: low\n---\n# Task")

        update_frontmatter(test_file, {"status": "done"})

        result = parse_frontmatter(test_file)
        assert result["status"] == "done"
        assert result["priority"] == "low"  # Unchanged

    def test_adds_new_fields(self, tmp_path: Path) -> None:
        """Should add new fields to frontmatter."""
        test_file = tmp_path / "test.md"
        test_file.write_text("---\ntype: task\n---\n# Task")

        update_frontmatter(test_file, {"priority": "high"})

        result = parse_frontmatter(test_file)
        assert result["type"] == "task"
        assert result["priority"] == "high"

    def test_preserves_body_content(self, tmp_path: Path) -> None:
        """Should preserve body content when updating frontmatter."""
        test_file = tmp_path / "test.md"
        original_body = "# Task\n\nThis is the body content."
        test_file.write_text(f"---\ntype: task\n---\n{original_body}")

        update_frontmatter(test_file, {"status": "done"})

        content = test_file.read_text()
        assert original_body in content

    def test_raises_for_missing_file(self) -> None:
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            update_frontmatter("/nonexistent/file.md", {"status": "done"})


class TestFormatWithFrontmatter:
    """Tests for format_with_frontmatter function."""

    def test_formats_frontmatter_and_body(self) -> None:
        """Should format frontmatter and body into valid markdown."""
        frontmatter = {"type": "task", "priority": "high"}
        body = "# My Task\n\nDescription here."

        result = format_with_frontmatter(frontmatter, body)

        assert result.startswith("---\n")
        assert "type: task" in result
        assert "priority: high" in result
        assert "---\n" in result
        assert "# My Task" in result

    def test_handles_empty_frontmatter(self) -> None:
        """Should return just body when frontmatter is empty."""
        result = format_with_frontmatter({}, "# Just body")

        assert result == "# Just body"


class TestCreateFileWithFrontmatter:
    """Tests for create_file_with_frontmatter function."""

    def test_creates_new_file(self, tmp_path: Path) -> None:
        """Should create a new file with frontmatter."""
        test_file = tmp_path / "new_task.md"
        frontmatter = {"type": "task", "priority": "medium"}
        body = "# New Task"

        create_file_with_frontmatter(test_file, frontmatter, body)

        assert test_file.exists()
        result = parse_frontmatter(test_file)
        assert result["type"] == "task"
        assert result["priority"] == "medium"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if they don't exist."""
        test_file = tmp_path / "deep" / "nested" / "task.md"

        create_file_with_frontmatter(test_file, {"type": "task"}, "# Task")

        assert test_file.exists()

    def test_skips_existing_file(self, tmp_path: Path) -> None:
        """Should skip silently if file already exists, preserving original content."""
        test_file = tmp_path / "existing.md"
        test_file.write_text("existing content")

        create_file_with_frontmatter(test_file, {"type": "task"}, "# Task")

        # Original content should be preserved (not overwritten)
        assert test_file.read_text() == "existing content"
