#!/usr/bin/env python3
"""Validate YAML frontmatter in vault markdown files.

This script validates frontmatter against defined schemas for different
file types in the AI Employee vault system.

Usage:
    python validate_frontmatter.py <file_path> [--schema <type>] [--dry-run]

Arguments:
    file_path   Path to the markdown file to validate
    --schema    Override auto-detected schema (action|plan|done|rejected)
    --dry-run   Only report, don't modify anything (currently read-only anyway)

Output:
    JSON object with validation results:
    {
        "valid": true|false,
        "file": "path/to/file.md",
        "schema": "action|plan|done|rejected",
        "errors": ["list of error messages"],
        "warnings": ["list of warning messages"]
    }

Examples:
    python validate_frontmatter.py vault/Needs_Action/task.md
    python validate_frontmatter.py vault/Plans/plan.md --schema plan
    python validate_frontmatter.py vault/Inbox/email.md --dry-run
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.utils.frontmatter import parse_frontmatter  # noqa: E402


# Schema definitions for each file type
SCHEMAS: dict[str, dict[str, Any]] = {
    "action": {
        "required": ["type", "source", "created", "priority", "status"],
        "optional": ["id", "from", "subject", "received", "tags", "related", "due"],
        "enums": {
            "type": [
                "email",
                "whatsapp",
                "calendar",
                "file",
                "task",
                "payment",
                "social",
                "other",
            ],
            "source": [
                "gmail_watcher",
                "whatsapp_watcher",
                "calendar_watcher",
                "manual",
            ],
            "priority": ["high", "medium", "low"],
            "status": ["pending", "needs_action", "in_progress"],
        },
        "conditional": {
            "from": {"when_type": ["email", "whatsapp", "calendar"]},
            "subject": {"when_type": ["email", "calendar"]},
            "received": {"when_type": ["email", "whatsapp"]},
        },
    },
    "plan": {
        "required": ["created", "status", "objective"],
        "optional": [
            "action_summary",
            "requires_approval",
            "sensitivity",
            "source_file",
            "risk_assessment",
            "rollback_plan",
            "approved_at",
            "approved_by",
            "rejection_reason",
        ],
        "enums": {
            "status": [
                "draft",
                "pending_approval",
                "approved",
                "rejected",
                "in_progress",
                "done",
            ],
            "sensitivity": ["low", "medium", "high"],
        },
        "conditional": {},
    },
    "done": {
        "required": ["created", "status", "objective", "completed_at", "result"],
        "optional": [
            "action_summary",
            "requires_approval",
            "sensitivity",
            "source_file",
            "risk_assessment",
            "rollback_plan",
            "approved_at",
            "approved_by",
            "execution_log",
            "outcome_summary",
        ],
        "enums": {
            "status": ["done"],
            "result": ["success", "partial", "failed"],
            "sensitivity": ["low", "medium", "high"],
        },
        "conditional": {},
    },
    "rejected": {
        "required": ["created", "status", "objective", "rejected_at", "rejection_reason"],
        "optional": [
            "action_summary",
            "requires_approval",
            "sensitivity",
            "source_file",
            "risk_assessment",
            "rollback_plan",
            "rejected_by",
        ],
        "enums": {
            "status": ["rejected"],
            "sensitivity": ["low", "medium", "high"],
        },
        "conditional": {},
    },
}


def detect_schema(file_path: str) -> str:
    """Auto-detect the appropriate schema based on file path.

    Args:
        file_path: Path to the file.

    Returns:
        Schema name: 'action', 'plan', 'done', or 'rejected'.
    """
    path_str = str(file_path).replace("\\", "/")

    if "/Inbox/" in path_str or "/Needs_Action/" in path_str:
        return "action"
    elif "/Done/" in path_str:
        return "done"
    elif "/Rejected/" in path_str:
        return "rejected"
    else:
        # Plans/, Pending_Approval/, Approved/ all use plan schema
        return "plan"


def validate_frontmatter(
    file_path: str,
    schema_name: str | None = None,
) -> dict[str, Any]:
    """Validate a file's frontmatter against its schema.

    Args:
        file_path: Path to the markdown file.
        schema_name: Optional schema override. If None, auto-detects.

    Returns:
        Validation result dictionary with keys:
        - valid: bool
        - file: str
        - schema: str
        - errors: list[str]
        - warnings: list[str]
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Determine schema
    if schema_name is None:
        schema_name = detect_schema(file_path)

    if schema_name not in SCHEMAS:
        return {
            "valid": False,
            "file": file_path,
            "schema": schema_name,
            "errors": [f"Unknown schema: {schema_name}"],
            "warnings": [],
        }

    schema = SCHEMAS[schema_name]

    # Parse frontmatter
    try:
        frontmatter = parse_frontmatter(file_path)
    except FileNotFoundError:
        return {
            "valid": False,
            "file": file_path,
            "schema": schema_name,
            "errors": [f"File not found: {file_path}"],
            "warnings": [],
        }
    except Exception as e:
        return {
            "valid": False,
            "file": file_path,
            "schema": schema_name,
            "errors": [f"Failed to parse frontmatter: {e}"],
            "warnings": [],
        }

    if not frontmatter:
        return {
            "valid": False,
            "file": file_path,
            "schema": schema_name,
            "errors": ["No frontmatter found in file"],
            "warnings": [],
        }

    # Check required fields
    for field in schema["required"]:
        if field not in frontmatter:
            errors.append(f"Missing required field: {field}")
        elif frontmatter[field] is None or frontmatter[field] == "":
            errors.append(f"Required field is empty: {field}")

    # Check enum values
    for field, allowed_values in schema["enums"].items():
        if field in frontmatter and frontmatter[field] is not None:
            value = frontmatter[field]
            if value not in allowed_values:
                errors.append(
                    f"Invalid value for '{field}': '{value}'. "
                    f"Allowed: {', '.join(allowed_values)}"
                )

    # Check conditional fields
    for field, conditions in schema.get("conditional", {}).items():
        if "when_type" in conditions:
            file_type = frontmatter.get("type")
            if file_type in conditions["when_type"]:
                if field not in frontmatter or not frontmatter[field]:
                    errors.append(
                        f"Field '{field}' is required when type is '{file_type}'"
                    )

    # Check for unknown fields (warning only)
    known_fields = set(schema["required"]) | set(schema["optional"])
    for field in frontmatter:
        if field not in known_fields:
            warnings.append(f"Unknown field: {field}")

    # Check for empty optional fields (warning only)
    for field in schema["optional"]:
        if field in frontmatter and frontmatter[field] == "":
            warnings.append(f"Optional field is empty: {field}")

    return {
        "valid": len(errors) == 0,
        "file": file_path,
        "schema": schema_name,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    """Main entry point for the CLI.

    Returns:
        Exit code: 0 if valid, 1 if invalid or error.
    """
    parser = argparse.ArgumentParser(
        description="Validate YAML frontmatter in vault markdown files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python validate_frontmatter.py vault/Needs_Action/task.md
    python validate_frontmatter.py vault/Plans/plan.md --schema plan
    python validate_frontmatter.py vault/Inbox/email.md --dry-run
        """,
    )
    parser.add_argument("file_path", help="Path to the markdown file to validate")
    parser.add_argument(
        "--schema",
        choices=["action", "plan", "done", "rejected"],
        help="Override auto-detected schema",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report, don't modify anything",
    )

    args = parser.parse_args()

    result = validate_frontmatter(args.file_path, args.schema)

    # Output as JSON
    print(json.dumps(result, indent=2))

    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
