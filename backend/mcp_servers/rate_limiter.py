"""In-memory sliding window rate limiter for email sends.

Loads limits from ``config/rate_limits.json``. Counter resets on server
restart (no persistence needed for Silver tier).
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MAX_SENDS_PER_HOUR = 10
DEFAULT_WINDOW_SECONDS = 3600


class RateLimiter:
    """Sliding-window rate limiter for email send operations."""

    def __init__(self, config_path: str = "config/rate_limits.json") -> None:
        self._send_timestamps: deque[float] = deque()
        self._load_config(config_path)

    def _load_config(self, config_path: str) -> None:
        """Load rate limit settings from JSON configuration."""
        path = Path(config_path)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                email_config = data.get("email", {})
                self.max_sends = email_config.get("sends_per_hour", DEFAULT_MAX_SENDS_PER_HOUR)
            except (json.JSONDecodeError, KeyError):
                logger.warning("Failed to parse rate limits config, using defaults")
                self.max_sends = DEFAULT_MAX_SENDS_PER_HOUR
        else:
            logger.warning("Rate limits config not found at %s, using defaults", config_path)
            self.max_sends = DEFAULT_MAX_SENDS_PER_HOUR

        self.window_seconds = DEFAULT_WINDOW_SECONDS
        logger.info(
            "Rate limiter initialized: %d sends per %d seconds",
            self.max_sends,
            self.window_seconds,
        )

    def _prune_expired(self) -> None:
        """Remove timestamps outside the current sliding window."""
        cutoff = time.time() - self.window_seconds
        while self._send_timestamps and self._send_timestamps[0] < cutoff:
            self._send_timestamps.popleft()

    def check(self) -> tuple[bool, int]:
        """Check if a send is allowed under the current rate limit.

        Returns:
            Tuple of (allowed, seconds_until_next_slot).
            If allowed is True, seconds_until_next_slot is 0.
            If allowed is False, seconds_until_next_slot is the number
            of seconds until the oldest entry expires from the window.
        """
        self._prune_expired()

        if len(self._send_timestamps) < self.max_sends:
            return True, 0

        # Calculate how long until the oldest timestamp expires
        oldest = self._send_timestamps[0]
        seconds_remaining = int(oldest + self.window_seconds - time.time()) + 1
        return False, max(seconds_remaining, 1)

    def record_send(self) -> None:
        """Record a successful send timestamp."""
        self._send_timestamps.append(time.time())

    @property
    def current_count(self) -> int:
        """Number of sends in the current window."""
        self._prune_expired()
        return len(self._send_timestamps)
