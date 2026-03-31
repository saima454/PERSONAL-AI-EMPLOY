"""ISO 8601 timestamp utilities for the AI Employee system.

This module provides consistent timestamp formatting for all vault files
and log entries.
"""

from datetime import UTC, datetime


def now_iso() -> str:
    """Get the current UTC timestamp in ISO 8601 format.

    Returns:
        Current timestamp as ISO 8601 string (YYYY-MM-DDTHH:MM:SSZ).

    Examples:
        >>> ts = now_iso()
        >>> ts  # e.g., "2025-02-04T14:30:22Z"
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(timestamp: str) -> datetime:
    """Parse an ISO 8601 timestamp string to a datetime object.

    Handles both 'Z' suffix and '+00:00' timezone formats.

    Args:
        timestamp: ISO 8601 formatted timestamp string.

    Returns:
        Timezone-aware datetime object in UTC.

    Raises:
        ValueError: If the timestamp format is invalid.

    Examples:
        >>> dt = parse_iso("2025-02-04T14:30:22Z")
        >>> dt.year
        2025
    """
    # Normalize timezone suffix
    normalized = timestamp.replace("Z", "+00:00")

    # Handle case where there's no timezone
    if "+" not in normalized and "-" not in normalized[10:]:
        normalized = normalized + "+00:00"

    return datetime.fromisoformat(normalized)


def format_filename_timestamp() -> str:
    """Get current timestamp formatted for filenames.

    Returns a compact timestamp without separators, suitable for use
    in filenames: YYYYMMDDTHHMMSS

    Returns:
        Filename-safe timestamp string.

    Examples:
        >>> ts = format_filename_timestamp()
        >>> ts  # e.g., "20250204T143022"
    """
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def today_iso() -> str:
    """Get today's date in ISO format (YYYY-MM-DD).

    Useful for daily log file naming.

    Returns:
        Today's date as ISO string.

    Examples:
        >>> date = today_iso()
        >>> date  # e.g., "2025-02-04"
    """
    return datetime.now(UTC).strftime("%Y-%m-%d")


def is_within_hours(timestamp: str, hours: int) -> bool:
    """Check if a timestamp is within the specified number of hours from now.

    Args:
        timestamp: ISO 8601 formatted timestamp string.
        hours: Number of hours to check.

    Returns:
        True if the timestamp is within the specified hours.

    Examples:
        >>> is_within_hours("2025-02-04T14:00:00Z", 24)
        True  # if current time is 2025-02-04T15:00:00Z
    """
    dt = parse_iso(timestamp)
    now = datetime.now(UTC)
    delta = now - dt
    return delta.total_seconds() <= hours * 3600
