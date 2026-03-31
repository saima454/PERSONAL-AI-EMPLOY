"""YAML frontmatter parsing utilities for Obsidian vault files.

This module provides functions to parse, extract, and update YAML frontmatter
in markdown files used by the AI Employee vault system.
"""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# Regex to match YAML frontmatter block (--- at start and end)
FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def extract_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body from markdown content.

    Args:
        content: The full markdown file content.

    Returns:
        A tuple of (frontmatter_dict, body_content).
        If no frontmatter is found, returns ({}, original_content).

    Examples:
        >>> fm, body = extract_frontmatter("---\\ntype: email\\n---\\n# Title")
        >>> fm
        {'type': 'email'}
        >>> body
        '# Title'
    """
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return {}, content

    yaml_content = match.group(1)
    body = content[match.end() :]

    try:
        frontmatter = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        return {}, content

    return frontmatter, body


def parse_frontmatter(file_path: str | Path) -> dict[str, Any]:
    """Parse YAML frontmatter from a markdown file.

    Args:
        file_path: Path to the markdown file.

    Returns:
        Dictionary containing the frontmatter fields.
        Returns empty dict if file doesn't exist or has no frontmatter.

    Raises:
        FileNotFoundError: If the file does not exist.

    Examples:
        >>> fm = parse_frontmatter("vault/Needs_Action/task.md")
        >>> fm.get("type")
        'task'
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    content = path.read_text(encoding="utf-8")
    frontmatter, _ = extract_frontmatter(content)
    return frontmatter


def update_frontmatter(file_path: str | Path, updates: dict[str, Any]) -> None:
    """Update specific fields in a file's YAML frontmatter.

    This function preserves all existing frontmatter fields and body content,
    only updating the specified fields.

    Args:
        file_path: Path to the markdown file.
        updates: Dictionary of fields to update or add.

    Raises:
        FileNotFoundError: If the file does not exist.

    Examples:
        >>> update_frontmatter("vault/Plans/plan.md", {"status": "approved"})
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    content = path.read_text(encoding="utf-8")
    frontmatter, body = extract_frontmatter(content)

    # Merge updates into existing frontmatter
    frontmatter.update(updates)

    # Reconstruct the file
    new_content = format_with_frontmatter(frontmatter, body)
    path.write_text(new_content, encoding="utf-8")


def format_with_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Format frontmatter and body into a complete markdown file.

    Args:
        frontmatter: Dictionary of frontmatter fields.
        body: The markdown body content.

    Returns:
        Complete file content with YAML frontmatter block.

    Examples:
        >>> content = format_with_frontmatter({"type": "task"}, "# My Task")
        >>> print(content)
        ---
        type: task
        ---
        # My Task
    """
    if not frontmatter:
        return body

    yaml_str = yaml.dump(
        frontmatter,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )

    # Ensure body starts with newline for proper separation
    if body and not body.startswith("\n"):
        body = "\n" + body

    return f"---\n{yaml_str}---{body}"


def create_file_with_frontmatter(
    file_path: str | Path,
    frontmatter: dict[str, Any],
    body: str,
) -> None:
    """Create a new markdown file with frontmatter.

    If the file already exists, logs a debug message and returns without
    overwriting.

    Args:
        file_path: Path where the file should be created.
        frontmatter: Dictionary of frontmatter fields.
        body: The markdown body content.

    Examples:
        >>> create_file_with_frontmatter(
        ...     "vault/Needs_Action/task.md",
        ...     {"type": "task", "priority": "high"},
        ...     "# Follow up with client"
        ... )
    """
    path = Path(file_path)
    if path.exists():
        logger.debug("File already exists, skipping creation: %s", file_path)
        return

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    content = format_with_frontmatter(frontmatter, body)
    path.write_text(content, encoding="utf-8")
