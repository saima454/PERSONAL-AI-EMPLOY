"""Watcher health monitor with crash recovery and restart logic.

Wraps each BaseWatcher in a supervised async task that detects crashes,
applies exponential backoff, and tracks restart counts.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso
from backend.utils.uuid_utils import correlation_id

if TYPE_CHECKING:
    from pathlib import Path

    from backend.watchers.base_watcher import BaseWatcher

logger = logging.getLogger(__name__)


class WatcherStatus(Enum):
    """Lifecycle states for a managed watcher task."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    FAILED = "failed"


@dataclass
class WatcherInfo:
    """Lightweight view of a WatcherTask for dashboard rendering."""

    name: str
    status: str
    restart_count: int
    last_error: str | None
    started_at: str | None


@dataclass
class WatcherTask:
    """Supervised wrapper around a BaseWatcher with health tracking.

    Runs the watcher in a loop, catching unhandled exceptions and restarting
    with exponential backoff up to ``max_restarts``.
    """

    name: str
    watcher: BaseWatcher
    max_restarts: int = 3
    log_dir: Path | None = None

    # Mutable state — set via field(default_factory) or post-init
    status: WatcherStatus = field(default=WatcherStatus.PENDING, init=False)
    restart_count: int = field(default=0, init=False)
    last_error: str | None = field(default=None, init=False)
    started_at: str | None = field(default=None, init=False)
    stopped_at: str | None = field(default=None, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

    # ── Public API ───────────────────────────────────────────────

    async def run_supervised(self) -> None:
        """Run the watcher in a supervised loop with crash recovery.

        On each crash:
        1. Log the error
        2. Increment restart_count
        3. Wait ``2^restart_count`` seconds (exponential backoff, max 60s)
        4. If restart_count >= max_restarts → mark as FAILED and stop
        """
        while True:
            self.status = WatcherStatus.RUNNING
            self.started_at = now_iso()
            logger.info("Watcher %s started", self.name)

            try:
                await self.watcher.run()
            except asyncio.CancelledError:
                self.status = WatcherStatus.STOPPED
                self.stopped_at = now_iso()
                logger.info("Watcher %s stopped (cancelled)", self.name)
                self._log_event("watcher_stop", "success", "Graceful shutdown")
                return
            except Exception as exc:
                self.last_error = str(exc)[:200]
                self.stopped_at = now_iso()
                self.restart_count += 1
                logger.exception(
                    "Watcher %s crashed (attempt %d/%d)",
                    self.name,
                    self.restart_count,
                    self.max_restarts,
                )
                self._log_event("watcher_crash", "failure", self.last_error)

                if self.restart_count >= self.max_restarts:
                    self.status = WatcherStatus.FAILED
                    logger.error(
                        "Watcher %s permanently failed after %d restarts",
                        self.name,
                        self.restart_count,
                    )
                    self._log_event(
                        "watcher_failed", "failure", f"Max restarts ({self.max_restarts}) exceeded"
                    )
                    return

                self.status = WatcherStatus.ERROR
                backoff = min(2**self.restart_count, 60)
                logger.info("Restarting %s in %ds...", self.name, backoff)
                self._log_event(
                    "watcher_restart",
                    "success",
                    f"Restart {self.restart_count}/{self.max_restarts}, backoff {backoff}s",
                )

                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    self.status = WatcherStatus.STOPPED
                    self.stopped_at = now_iso()
                    logger.info("Watcher %s restart cancelled", self.name)
                    return

    async def cancel(self) -> None:
        """Gracefully cancel the running watcher task."""
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._task, timeout=5.0)
        self.status = WatcherStatus.STOPPED
        self.stopped_at = now_iso()

    def start(self) -> asyncio.Task[None]:
        """Create and store the asyncio task for this watcher."""
        self._task = asyncio.create_task(self.run_supervised(), name=f"watcher-{self.name}")
        return self._task

    @property
    def info(self) -> WatcherInfo:
        """Return a lightweight snapshot for dashboard rendering."""
        return WatcherInfo(
            name=self.name,
            status=self.status.value,
            restart_count=self.restart_count,
            last_error=self.last_error,
            started_at=self.started_at,
        )

    # ── Private ──────────────────────────────────────────────────

    def _log_event(self, action_type: str, result: str, details: str) -> None:
        """Log a watchdog event to the audit trail."""
        if self.log_dir is None:
            return
        try:
            log_action(
                self.log_dir,
                {
                    "timestamp": now_iso(),
                    "correlation_id": correlation_id(),
                    "actor": "watchdog",
                    "action_type": action_type,
                    "target": self.name,
                    "result": result,
                    "parameters": {
                        "restart_count": self.restart_count,
                        "max_restarts": self.max_restarts,
                        "details": details,
                    },
                },
            )
        except Exception:
            logger.exception("Failed to log watchdog event for %s", self.name)
