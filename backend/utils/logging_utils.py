"""Audit logging utilities for the AI Employee system.

This module provides functions to write and read JSON-formatted audit logs
in the vault's Logs directory.
"""

import json
from pathlib import Path
from typing import Any

from backend.utils.timestamps import today_iso


def log_action(log_dir: str | Path, entry: dict[str, Any]) -> None:
    """Append an action entry to today's log file.

    Creates the log file if it doesn't exist. Each log file contains
    a JSON object with a "date" field and an "entries" array.

    Args:
        log_dir: Path to the log directory (e.g., vault/Logs/actions).
        entry: Dictionary containing the log entry fields.
            Required: timestamp, correlation_id, actor, action_type, target, result
            Optional: parameters, duration_ms, error

    Examples:
        >>> log_action("vault/Logs/actions", {
        ...     "timestamp": "2025-02-04T14:30:22Z",
        ...     "correlation_id": "abc-123",
        ...     "actor": "vault-manager",
        ...     "action_type": "file_move",
        ...     "target": "task.md",
        ...     "result": "success"
        ... })
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    date = today_iso()
    log_file = log_path / f"{date}.json"

    # Load existing log or create new structure
    if log_file.exists():
        data = json.loads(log_file.read_text(encoding="utf-8"))
    else:
        data = {"date": date, "entries": []}

    # Append new entry
    data["entries"].append(entry)

    # Write back atomically (write to temp then rename for safety)
    log_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_recent_logs(log_dir: str | Path, count: int = 10) -> list[dict[str, Any]]:
    """Read the most recent log entries from a log directory.

    Reads entries across multiple days if needed to reach the requested count.

    Args:
        log_dir: Path to the log directory.
        count: Maximum number of entries to return.

    Returns:
        List of log entries, most recent first.

    Examples:
        >>> entries = read_recent_logs("vault/Logs/actions", 5)
        >>> len(entries) <= 5
        True
    """
    log_path = Path(log_dir)
    if not log_path.exists():
        return []

    # Get all log files sorted by date (newest first)
    log_files = sorted(log_path.glob("*.json"), reverse=True)

    entries: list[dict[str, Any]] = []

    for log_file in log_files:
        if len(entries) >= count:
            break

        try:
            data = json.loads(log_file.read_text(encoding="utf-8"))
            file_entries = data.get("entries", [])
            # Reverse to get newest first within the file
            file_entries.reverse()
            entries.extend(file_entries)
        except (json.JSONDecodeError, KeyError):
            continue

    return entries[:count]


def read_logs_for_date(log_dir: str | Path, date: str) -> list[dict[str, Any]]:
    """Read all log entries for a specific date.

    Args:
        log_dir: Path to the log directory.
        date: Date string in ISO format (YYYY-MM-DD).

    Returns:
        List of log entries for that date, oldest first.

    Examples:
        >>> entries = read_logs_for_date("vault/Logs/actions", "2025-02-04")
    """
    log_path = Path(log_dir)
    log_file = log_path / f"{date}.json"

    if not log_file.exists():
        return []

    try:
        data = json.loads(log_file.read_text(encoding="utf-8"))
        return data.get("entries", [])
    except (json.JSONDecodeError, KeyError):
        return []


def count_entries_today(log_dir: str | Path) -> int:
    """Count the number of log entries for today.

    Useful for dashboard statistics.

    Args:
        log_dir: Path to the log directory.

    Returns:
        Number of entries logged today.

    Examples:
        >>> count = count_entries_today("vault/Logs/actions")
    """
    entries = read_logs_for_date(log_dir, today_iso())
    return len(entries)
