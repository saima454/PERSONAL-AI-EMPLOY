"""Tests for backend.orchestrator.watchdog — WatcherTask supervised execution."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from backend.orchestrator.watchdog import WatcherInfo, WatcherStatus, WatcherTask

# ── Helpers ──────────────────────────────────────────────────────


class FakeWatcher:
    """Minimal BaseWatcher-like stub for testing."""

    def __init__(self, fail_count: int = 0) -> None:
        self.fail_count = fail_count
        self._calls = 0

    async def run(self) -> None:
        self._calls += 1
        if self._calls <= self.fail_count:
            raise RuntimeError(f"Fake crash #{self._calls}")
        # Run "forever" until cancelled
        await asyncio.sleep(3600)


class InstantCrashWatcher:
    """Always raises on run()."""

    async def run(self) -> None:
        raise RuntimeError("instant crash")


# ── Status Transition Tests ──────────────────────────────────────


class TestWatcherTaskStatus:
    def test_initial_status_is_pending(self) -> None:
        wt = WatcherTask(name="test", watcher=FakeWatcher())
        assert wt.status == WatcherStatus.PENDING

    @pytest.mark.asyncio
    async def test_running_status_after_start(self) -> None:
        wt = WatcherTask(name="test", watcher=FakeWatcher())
        task = wt.start()
        await asyncio.sleep(0.05)
        assert wt.status == WatcherStatus.RUNNING
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_stopped_after_cancel(self) -> None:
        wt = WatcherTask(name="test", watcher=FakeWatcher())
        wt.start()
        await asyncio.sleep(0.05)
        await wt.cancel()
        assert wt.status == WatcherStatus.STOPPED

    @pytest.mark.asyncio
    async def test_error_status_on_crash(self) -> None:
        watcher = FakeWatcher(fail_count=1)
        wt = WatcherTask(name="test", watcher=watcher, max_restarts=3)
        task = wt.start()
        # Wait for crash + backoff start
        await asyncio.sleep(0.1)
        assert wt.restart_count == 1
        # After restart it should be running again
        await asyncio.sleep(3)  # wait for backoff (2^1 = 2s)
        assert wt.status == WatcherStatus.RUNNING
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_failed_after_max_restarts(self) -> None:
        wt = WatcherTask(name="test", watcher=InstantCrashWatcher(), max_restarts=2)
        task = wt.start()
        # Wait for all restarts to exhaust (backoff: 2s + 4s = 6s, but crashes are instant)
        await asyncio.wait_for(task, timeout=15)
        assert wt.status == WatcherStatus.FAILED
        assert wt.restart_count >= 2


# ── Restart Logic Tests ──────────────────────────────────────────


class TestRestartLogic:
    @pytest.mark.asyncio
    async def test_restart_count_increments(self) -> None:
        watcher = FakeWatcher(fail_count=2)
        wt = WatcherTask(name="test", watcher=watcher, max_restarts=5)
        task = wt.start()
        # Wait enough for 2 crashes + backoffs + recovery
        await asyncio.sleep(8)
        assert wt.restart_count == 2
        assert wt.status == WatcherStatus.RUNNING
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_last_error_recorded(self) -> None:
        wt = WatcherTask(name="test", watcher=InstantCrashWatcher(), max_restarts=1)
        task = wt.start()
        await asyncio.wait_for(task, timeout=10)
        assert wt.last_error is not None
        assert "instant crash" in wt.last_error


# ── Info Property Tests ──────────────────────────────────────────


class TestWatcherInfo:
    def test_info_returns_watcher_info(self) -> None:
        wt = WatcherTask(name="Gmail", watcher=FakeWatcher())
        info = wt.info
        assert isinstance(info, WatcherInfo)
        assert info.name == "Gmail"
        assert info.status == "pending"
        assert info.restart_count == 0

    @pytest.mark.asyncio
    async def test_info_reflects_running_state(self) -> None:
        wt = WatcherTask(name="Gmail", watcher=FakeWatcher())
        task = wt.start()
        await asyncio.sleep(0.05)
        info = wt.info
        assert info.status == "running"
        assert info.started_at is not None
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ── Audit Logging Tests ─────────────────────────────────────────


class TestWatchdogLogging:
    @pytest.mark.asyncio
    async def test_log_event_called_on_crash(self, tmp_path) -> None:
        wt = WatcherTask(
            name="test",
            watcher=InstantCrashWatcher(),
            max_restarts=1,
            log_dir=tmp_path,
        )
        task = wt.start()
        await asyncio.wait_for(task, timeout=10)

        # Check that log files were created
        log_files = list(tmp_path.glob("*.json"))
        assert len(log_files) > 0
