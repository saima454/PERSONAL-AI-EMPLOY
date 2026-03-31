"""HITL approval file verification for email send/reply operations.

Scans ``vault/Approved/`` for matching markdown files with YAML frontmatter.
Consumed approval files are moved to ``vault/Done/`` after successful execution.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from backend.utils.frontmatter import extract_frontmatter, update_frontmatter
from backend.utils.timestamps import now_iso

logger = logging.getLogger(__name__)


def find_approval(
    vault_path: str,
    action_type: str,
    **match_fields: str,
) -> dict[str, Any] | None:
    """Find a matching approval file in vault/Approved/.

    Scans all ``.md`` files in the Approved directory for one whose YAML
    frontmatter matches the given action type and fields.

    Args:
        vault_path: Root path to the vault directory.
        action_type: Expected ``type`` field value (e.g. ``"email_send"``
            or ``"email_reply"``).
        **match_fields: Additional frontmatter fields to match. Keys are
            field names, values are expected values. Matching is
            case-insensitive for string values.

    Returns:
        Dict with ``path`` (Path object) and all frontmatter fields of the
        most recent matching approval file, or ``None`` if no match found.
    """
    approved_dir = Path(vault_path) / "Approved"
    if not approved_dir.exists():
        logger.debug("Approved directory does not exist: %s", approved_dir)
        return None

    matches: list[dict[str, Any]] = []

    for md_file in sorted(approved_dir.glob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            frontmatter, _ = extract_frontmatter(content)
        except (OSError, UnicodeDecodeError):
            logger.warning("Failed to read approval file: %s", md_file)
            continue

        if not frontmatter:
            continue

        # Check action type
        if frontmatter.get("type") != action_type:
            continue

        # Check status
        if frontmatter.get("status") != "approved":
            continue

        # Check additional match fields
        all_match = True
        for field, expected in match_fields.items():
            actual = frontmatter.get(field, "")
            if isinstance(actual, str) and isinstance(expected, str):
                if actual.lower() != expected.lower():
                    all_match = False
                    break
            elif actual != expected:
                all_match = False
                break

        if all_match:
            matches.append({"path": md_file, **frontmatter})

    if not matches:
        return None

    # Return most recent match (by approved_at or file modification time)
    def _sort_key(m: dict[str, Any]) -> str:
        return m.get("approved_at", m.get("created", ""))

    matches.sort(key=_sort_key, reverse=True)
    logger.info("Found approval file: %s", matches[0]["path"])
    return matches[0]


def consume_approval(file_path: str | Path, vault_path: str) -> None:
    """Move an approval file from Approved to Done after execution.

    Updates the frontmatter with ``completed_at`` timestamp and
    ``status: done`` before moving.

    Args:
        file_path: Path to the approval file in vault/Approved/.
        vault_path: Root path to the vault directory.
    """
    src = Path(file_path)
    done_dir = Path(vault_path) / "Done"
    done_dir.mkdir(parents=True, exist_ok=True)
    dest = done_dir / src.name

    # Update frontmatter before moving
    try:
        update_frontmatter(src, {"status": "done", "completed_at": now_iso()})
    except (FileNotFoundError, OSError):
        logger.warning("Could not update frontmatter on %s before moving", src)

    # Move file
    shutil.move(str(src), str(dest))
    logger.info("Consumed approval: %s → %s", src.name, dest)
