"""Tests for RateLimiter (backend.mcp_servers.rate_limiter)."""

from __future__ import annotations

import time

import pytest

from backend.mcp_servers.rate_limiter import RateLimiter


@pytest.fixture()
def limiter() -> RateLimiter:
    """Create a RateLimiter with default config (won't find file, uses defaults)."""
    return RateLimiter(config_path="nonexistent.json")


class TestRateLimiter:
    """Tests for the sliding window rate limiter."""

    def test_allows_under_limit(self, limiter: RateLimiter) -> None:
        """Requests under the limit are allowed."""
        allowed, wait = limiter.check()

        assert allowed is True
        assert wait == 0

    def test_rejects_at_limit(self, limiter: RateLimiter) -> None:
        """Requests at the limit are rejected with wait time."""
        # Fill up the limit (default 10)
        for _ in range(limiter.max_sends):
            limiter.record_send()

        allowed, wait = limiter.check()

        assert allowed is False
        assert wait > 0

    def test_window_expiry_allows_again(self, limiter: RateLimiter) -> None:
        """After window expires, sends are allowed again."""
        # Fill up the limit with timestamps in the past
        past_time = time.time() - 3601  # 1 hour + 1 second ago
        for _ in range(limiter.max_sends):
            limiter._send_timestamps.append(past_time)

        allowed, wait = limiter.check()

        assert allowed is True
        assert wait == 0

    def test_record_send_increments_count(self, limiter: RateLimiter) -> None:
        """Recording a send increases the current count."""
        assert limiter.current_count == 0

        limiter.record_send()

        assert limiter.current_count == 1

    def test_partial_window_expiry(self, limiter: RateLimiter) -> None:
        """Only expired timestamps are pruned, recent ones stay."""
        # Add 5 expired and 3 recent
        past_time = time.time() - 3601
        for _ in range(5):
            limiter._send_timestamps.append(past_time)
        for _ in range(3):
            limiter.record_send()

        assert limiter.current_count == 3

    def test_check_returns_positive_wait(self, limiter: RateLimiter) -> None:
        """Wait time is always at least 1 second when rate limited."""
        for _ in range(limiter.max_sends):
            limiter.record_send()

        _, wait = limiter.check()

        assert wait >= 1

    def test_loads_config_from_file(self, tmp_path: pytest.TempPathFactory) -> None:
        """Loads rate limits from JSON config file."""
        config = tmp_path / "rate_limits.json"
        config.write_text('{"email": {"sends_per_hour": 5}}', encoding="utf-8")

        limiter = RateLimiter(config_path=str(config))

        assert limiter.max_sends == 5
