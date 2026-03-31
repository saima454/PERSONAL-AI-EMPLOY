"""Tests for validate_frontmatter.py script."""

import sys
from pathlib import Path

import pytest

# Add scripts to path
SCRIPTS_DIR = Path(__file__).parent.parent / "skills" / "vault-manager" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from validate_frontmatter import detect_schema, validate_frontmatter


class TestDetectSchema:
    """Tests for schema auto-detection."""

    def test_detects_action_for_inbox(self) -> None:
        """Should detect action schema for Inbox folder."""
        assert detect_schema("vault/Inbox/email.md") == "action"
        assert detect_schema("/path/to/vault/Inbox/task.md") == "action"

    def test_detects_action_for_needs_action(self) -> None:
        """Should detect action schema for Needs_Action folder."""
        assert detect_schema("vault/Needs_Action/email.md") == "action"

    def test_detects_done_for_done_folder(self) -> None:
        """Should detect done schema for Done folder."""
        assert detect_schema("vault/Done/completed.md") == "done"

    def test_detects_rejected_for_rejected_folder(self) -> None:
        """Should detect rejected schema for Rejected folder."""
        assert detect_schema("vault/Rejected/declined.md") == "rejected"

    def test_detects_plan_for_plans_folder(self) -> None:
        """Should detect plan schema for Plans folder."""
        assert detect_schema("vault/Plans/plan.md") == "plan"

    def test_detects_plan_for_pending_approval(self) -> None:
        """Should detect plan schema for Pending_Approval folder."""
        assert detect_schema("vault/Pending_Approval/plan.md") == "plan"

    def test_detects_plan_for_approved(self) -> None:
        """Should detect plan schema for Approved folder."""
        assert detect_schema("vault/Approved/plan.md") == "plan"

    def test_handles_windows_paths(self) -> None:
        """Should handle Windows-style paths."""
        assert detect_schema("vault\\Inbox\\email.md") == "action"
        assert detect_schema("C:\\Users\\test\\vault\\Done\\task.md") == "done"


class TestValidateFrontmatter:
    """Tests for frontmatter validation."""

    def test_validates_valid_action_file(self, tmp_path: Path) -> None:
        """Should pass validation for valid action file."""
        test_file = tmp_path / "Needs_Action" / "task.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "type: task\n"
            "source: manual\n"
            "created: 2025-02-04T17:00:00Z\n"
            "priority: high\n"
            "status: needs_action\n"
            "---\n"
            "# Task"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is True
        assert result["schema"] == "action"
        assert len(result["errors"]) == 0

    def test_fails_for_missing_required_field(self, tmp_path: Path) -> None:
        """Should fail when required field is missing."""
        test_file = tmp_path / "Needs_Action" / "task.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "type: task\n"
            "source: manual\n"
            # missing: created, priority, status
            "---\n"
            "# Task"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is False
        assert any("created" in err for err in result["errors"])
        assert any("priority" in err for err in result["errors"])
        assert any("status" in err for err in result["errors"])

    def test_fails_for_invalid_enum_value(self, tmp_path: Path) -> None:
        """Should fail when enum value is invalid."""
        test_file = tmp_path / "Needs_Action" / "task.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "type: task\n"
            "source: manual\n"
            "created: 2025-02-04T17:00:00Z\n"
            "priority: urgent\n"  # Invalid - should be high/medium/low
            "status: needs_action\n"
            "---\n"
            "# Task"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is False
        assert any("priority" in err and "urgent" in err for err in result["errors"])

    def test_fails_for_missing_conditional_field(self, tmp_path: Path) -> None:
        """Should fail when conditional field is missing."""
        test_file = tmp_path / "Needs_Action" / "email.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "type: email\n"  # Email requires 'from' and 'subject'
            "source: gmail_watcher\n"
            "created: 2025-02-04T17:00:00Z\n"
            "priority: high\n"
            "status: needs_action\n"
            # missing: from, subject, received
            "---\n"
            "# Email"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is False
        assert any("from" in err for err in result["errors"])
        assert any("subject" in err for err in result["errors"])

    def test_validates_valid_plan_file(self, tmp_path: Path) -> None:
        """Should pass validation for valid plan file."""
        test_file = tmp_path / "Plans" / "plan.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "created: 2025-02-04T17:00:00Z\n"
            "status: draft\n"
            "objective: Test the system\n"
            "---\n"
            "# Plan"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is True
        assert result["schema"] == "plan"

    def test_warns_for_unknown_fields(self, tmp_path: Path) -> None:
        """Should warn about unknown fields."""
        test_file = tmp_path / "Needs_Action" / "task.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "type: task\n"
            "source: manual\n"
            "created: 2025-02-04T17:00:00Z\n"
            "priority: high\n"
            "status: needs_action\n"
            "unknown_field: some value\n"  # Unknown field
            "---\n"
            "# Task"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is True  # Warnings don't fail validation
        assert any("unknown_field" in warn for warn in result["warnings"])

    def test_schema_override(self, tmp_path: Path) -> None:
        """Should use schema override when provided."""
        test_file = tmp_path / "somewhere" / "file.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "type: task\n"
            "source: manual\n"
            "created: 2025-02-04T17:00:00Z\n"
            "priority: high\n"
            "status: needs_action\n"
            "---\n"
            "# Task"
        )

        result = validate_frontmatter(str(test_file), schema_name="action")

        assert result["schema"] == "action"
        assert result["valid"] is True

    def test_handles_missing_file(self) -> None:
        """Should handle missing file gracefully."""
        result = validate_frontmatter("/nonexistent/file.md")

        assert result["valid"] is False
        assert any("not found" in err.lower() for err in result["errors"])

    def test_handles_no_frontmatter(self, tmp_path: Path) -> None:
        """Should fail for file without frontmatter."""
        test_file = tmp_path / "Needs_Action" / "task.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("# Just a title\n\nNo frontmatter here.")

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is False
        assert any("no frontmatter" in err.lower() for err in result["errors"])


class TestValidateDoneSchema:
    """Tests for done file validation."""

    def test_validates_valid_done_file(self, tmp_path: Path) -> None:
        """Should pass validation for valid done file."""
        test_file = tmp_path / "Done" / "completed.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "created: 2025-02-04T17:00:00Z\n"
            "status: done\n"
            "objective: Complete the task\n"
            "completed_at: 2025-02-04T18:00:00Z\n"
            "result: success\n"
            "---\n"
            "# Done"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is True
        assert result["schema"] == "done"

    def test_fails_without_completed_at(self, tmp_path: Path) -> None:
        """Should fail when completed_at is missing."""
        test_file = tmp_path / "Done" / "completed.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "created: 2025-02-04T17:00:00Z\n"
            "status: done\n"
            "objective: Complete the task\n"
            "result: success\n"
            "---\n"
            "# Done"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is False
        assert any("completed_at" in err for err in result["errors"])


class TestValidateRejectedSchema:
    """Tests for rejected file validation."""

    def test_validates_valid_rejected_file(self, tmp_path: Path) -> None:
        """Should pass validation for valid rejected file."""
        test_file = tmp_path / "Rejected" / "declined.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "created: 2025-02-04T17:00:00Z\n"
            "status: rejected\n"
            "objective: Do something risky\n"
            "rejected_at: 2025-02-04T18:00:00Z\n"
            "rejection_reason: Too risky\n"
            "---\n"
            "# Rejected"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is True
        assert result["schema"] == "rejected"

    def test_fails_without_rejection_reason(self, tmp_path: Path) -> None:
        """Should fail when rejection_reason is missing."""
        test_file = tmp_path / "Rejected" / "declined.md"
        test_file.parent.mkdir(parents=True)
        test_file.write_text(
            "---\n"
            "created: 2025-02-04T17:00:00Z\n"
            "status: rejected\n"
            "objective: Do something\n"
            "rejected_at: 2025-02-04T18:00:00Z\n"
            "---\n"
            "# Rejected"
        )

        result = validate_frontmatter(str(test_file))

        assert result["valid"] is False
        assert any("rejection_reason" in err for err in result["errors"])
