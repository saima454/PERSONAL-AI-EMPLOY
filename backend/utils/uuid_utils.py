"""UUID utilities for the AI Employee system.

This module provides UUID generation for correlation IDs used in
audit logging and action tracking.
"""

import uuid


def correlation_id() -> str:
    """Generate a new UUID v4 correlation ID.

    Correlation IDs are used to trace related events across the system,
    such as linking a file move action to its log entry.

    Returns:
        A UUID v4 string.

    Examples:
        >>> cid = correlation_id()
        >>> len(cid)
        36
        >>> cid  # e.g., "550e8400-e29b-41d4-a716-446655440000"
    """
    return str(uuid.uuid4())


def short_id() -> str:
    """Generate a short 8-character ID.

    Useful for human-readable identifiers where full UUID is too long.

    Returns:
        First 8 characters of a UUID v4.

    Examples:
        >>> sid = short_id()
        >>> len(sid)
        8
    """
    return str(uuid.uuid4())[:8]
