# backend\orchestrator\orchestrator.py
"""Main orchestrator — starts watchers, action executor, and dashboard loop.

Single entry point for the AI Employee system. Coordinates all subsystems
as concurrent async tasks in a single Python process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from backend.orchestrator.watchdog import WatcherStatus, WatcherTask
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso
from backend.utils.uuid_utils import correlation_id

logger = logging.getLogger(__name__)

# Vault subdirectories required by the system
VAULT_SUBDIRS = [
    "Inbox",
    "Needs_Action",
    "Plans",
    "Pending_Approval",
    "Approved",
    "Rejected",
    "Done",
    "Logs",
    "Logs/actions",
    "Logs/errors",
    "Logs/decisions",
    "Logs/audit",
    "Briefings",
    "Accounting",
]


@dataclass
class OrchestratorConfig:
    """Configuration loaded from environment variables."""

    vault_path: str = "./vault"
    check_interval: int = 30
    dashboard_interval: int = 300
    max_restart_attempts: int = 3
    dev_mode: bool = True
    dry_run: bool = False
    lock_file_path: str = "config/.orchestrator.lock"
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> OrchestratorConfig:
        """Load configuration from environment variables."""
        return cls(
            vault_path=os.getenv("VAULT_PATH", "./vault"),
            check_interval=int(os.getenv("ORCHESTRATOR_CHECK_INTERVAL", "30")),
            dashboard_interval=int(os.getenv("ORCHESTRATOR_DASHBOARD_UPDATE_INTERVAL", "300")),
            max_restart_attempts=int(os.getenv("ORCHESTRATOR_MAX_RESTART_ATTEMPTS", "3")),
            dev_mode=os.getenv("DEV_MODE", "true").lower() == "true",
            dry_run=os.getenv("DRY_RUN", "false").lower() == "true",
            lock_file_path="config/.orchestrator.lock",
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )


# ── Lock File Management ────────────────────────────────────────────


def is_process_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def acquire_lock(lock_path: str | Path) -> bool:
    """Write PID to lock file. Returns False if another instance is running.

    If a stale lock file exists (PID not alive), it is overwritten.
    """
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        try:
            content = path.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("PID:"):
                    existing_pid = int(line.split(":")[1].strip())
                    if is_process_alive(existing_pid):
                        logger.error(
                            "Another orchestrator is running (PID %d). Lock: %s",
                            existing_pid,
                            path,
                        )
                        return False
                    logger.warning(
                        "Stale lock file found (PID %d not alive), overwriting", existing_pid
                    )
                    break
        except (ValueError, OSError):
            logger.warning("Corrupted lock file, overwriting: %s", path)

    path.write_text(
        f"PID: {os.getpid()}\nSTARTED: {now_iso()}\n",
        encoding="utf-8",
    )
    logger.info("Lock acquired: %s (PID %d)", path, os.getpid())
    return True


def release_lock(lock_path: str | Path) -> None:
    """Delete the lock file."""
    path = Path(lock_path)
    if path.exists():
        path.unlink()
        logger.info("Lock released: %s", path)


# ── Orchestrator ─────────────────────────────────────────────────────


class Orchestrator:
    """Main orchestrator — coordinates watchers, action executor, and dashboard."""

    def __init__(self, config: OrchestratorConfig) -> None:
        self.config = config
        self.vault_path = Path(config.vault_path)
        self.log_dir = self.vault_path / "Logs" / "actions"
        self.watcher_tasks: list[WatcherTask] = []
        self._action_executor_task: asyncio.Task[None] | None = None
        self._dashboard_task: asyncio.Task[None] | None = None
        self._started_at: str | None = None

    async def run(self) -> None:
        """Main entry point. Acquires lock, starts all subsystems, blocks until shutdown."""
        if not acquire_lock(self.config.lock_file_path):
            logger.error("Cannot start: another orchestrator instance is running")
            return

        try:
            self._started_at = now_iso()
            self._ensure_vault_dirs()
            self._log_event("orchestrator_start", "success", f"DEV_MODE={self.config.dev_mode}")

            mode = "DEV_MODE" if self.config.dev_mode else "PRODUCTION"
            logger.info("Starting orchestrator (%s)", mode)

            # Check content schedule on startup
            await self._check_content_schedule()

            # Check CEO briefing schedule on startup (Feature 007)
            await self._check_briefing_schedule()

            # Check for pending Ralph loop tasks (Feature 001)
            await self._check_ralph_loops()

            # Start watchers
            self._start_watchers()

            # Start action executor
            self._start_action_executor()

            # Start dashboard loop
            self._start_dashboard_loop()

            logger.info("Orchestrator running. Press Ctrl+C to stop.")

            # Block until cancelled — let tasks run
            await self._wait_forever()

        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Cancel all tasks and release lock."""
        logger.info("Shutting down orchestrator...")

        # Cancel watcher tasks
        for wt in self.watcher_tasks:
            await wt.cancel()

        # Cancel action executor
        if self._action_executor_task and not self._action_executor_task.done():
            self._action_executor_task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._action_executor_task, timeout=5.0)

        # Cancel dashboard task
        if self._dashboard_task and not self._dashboard_task.done():
            self._dashboard_task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._dashboard_task, timeout=5.0)

        self._log_event("orchestrator_stop", "success", "Graceful shutdown")
        release_lock(self.config.lock_file_path)
        logger.info("Orchestrator stopped.")

    # ── Watcher Management ───────────────────────────────────────

    def _start_watchers(self) -> None:
        """Create and start watcher tasks. Skip unavailable watchers."""
        watchers_config = self._build_watcher_configs()

        for name, factory in watchers_config:
            try:
                watcher = factory()
                wt = WatcherTask(
                    name=name,
                    watcher=watcher,
                    max_restarts=self.config.max_restart_attempts,
                    log_dir=self.log_dir,
                )
                wt.start()
                self.watcher_tasks.append(wt)
                logger.info("Started watcher: %s", name)
            except ImportError as exc:
                logger.warning("Skipping watcher %s: %s", name, exc)
            except Exception:
                logger.exception("Failed to start watcher %s", name)

        if not self.watcher_tasks:
            logger.warning(
                "No watchers started — orchestrator will only run action executor and dashboard"
            )

    def _build_watcher_configs(self) -> list[tuple[str, object]]:
        """Build list of (name, factory) for each watcher.

        Each factory is a zero-arg callable that returns a BaseWatcher instance.
        Uses lazy imports to allow skipping unavailable watchers.
        """
        configs: list[tuple[str, object]] = []

        # Gmail Watcher
        def _gmail_factory():  # noqa: ANN202
            from backend.watchers.gmail_watcher import GmailWatcher

            return GmailWatcher(
                vault_path=str(self.vault_path),
                credentials_path=os.getenv("GMAIL_CREDENTIALS_PATH", "config/credentials.json"),
                token_path=os.getenv("GMAIL_TOKEN_PATH", "config/token.json"),
                check_interval=int(os.getenv("GMAIL_CHECK_INTERVAL", "120")),
                dry_run=self.config.dry_run,
                dev_mode=self.config.dev_mode,
            )

        configs.append(("Gmail", _gmail_factory))

        # Vault Action Watcher (reply checkbox → Pending_Approval template)
        def _vault_action_factory():  # noqa: ANN202
            from backend.watchers.vault_action_watcher import VaultActionWatcher

            return VaultActionWatcher(
                vault_path=str(self.vault_path),
                check_interval=5,
            )

        configs.append(("VaultAction", _vault_action_factory))

        # WhatsApp Watcher
        def _whatsapp_factory():  # noqa: ANN202
            from backend.watchers.whatsapp_watcher import WhatsAppWatcher

            keywords_env = os.getenv("WHATSAPP_KEYWORDS", "")
            keywords = [k.strip() for k in keywords_env.split(",") if k.strip()] or None
            return WhatsAppWatcher(
                vault_path=str(self.vault_path),
                session_path=os.getenv("WHATSAPP_SESSION_PATH", "config/whatsapp_session"),
                check_interval=int(os.getenv("WHATSAPP_CHECK_INTERVAL", "30")),
                keywords=keywords,
                headless=os.getenv("WHATSAPP_HEADLESS", "true").lower() == "true",
                dry_run=self.config.dry_run,
                dev_mode=self.config.dev_mode,
            )

        configs.append(("WhatsApp", _whatsapp_factory))

        # LinkedIn Watcher
        def _linkedin_factory():  # noqa: ANN202
            from backend.watchers.linkedin_watcher import LinkedInWatcher

            return LinkedInWatcher(
                vault_path=str(self.vault_path),
                session_path=os.getenv("LINKEDIN_SESSION_PATH", "config/linkedin_session"),
                check_interval=300,
                headless=os.getenv("LINKEDIN_HEADLESS", "true").lower() == "true",
                dry_run=self.config.dry_run,
                dev_mode=self.config.dev_mode,
            )

        configs.append(("LinkedIn", _linkedin_factory))

        # Facebook Watcher
        def _facebook_factory():  # noqa: ANN202
            from backend.watchers.facebook_watcher import FacebookWatcher

            keywords_env = os.getenv("FACEBOOK_KEYWORDS", "")
            keywords = [k.strip() for k in keywords_env.split(",") if k.strip()] or None
            return FacebookWatcher(
                vault_path=str(self.vault_path),
                session_path=os.getenv("FACEBOOK_SESSION_PATH", "config/meta_session"),
                check_interval=int(os.getenv("FACEBOOK_CHECK_INTERVAL", "120")),
                keywords=keywords,
                headless=os.getenv("FACEBOOK_HEADLESS", "true").lower() == "true",
                dry_run=self.config.dry_run,
                dev_mode=self.config.dev_mode,
            )

        configs.append(("Facebook", _facebook_factory))

        # Instagram Watcher
        def _instagram_factory():  # noqa: ANN202
            from backend.watchers.instagram_watcher import InstagramWatcher

            keywords_env = os.getenv("INSTAGRAM_KEYWORDS", "")
            keywords = [k.strip() for k in keywords_env.split(",") if k.strip()] or None
            return InstagramWatcher(
                vault_path=str(self.vault_path),
                session_path=os.getenv("INSTAGRAM_SESSION_PATH", "config/meta_session"),
                check_interval=int(os.getenv("INSTAGRAM_CHECK_INTERVAL", "60")),
                keywords=keywords,
                headless=os.getenv("INSTAGRAM_HEADLESS", "true").lower() == "true",
                dry_run=self.config.dry_run,
                dev_mode=self.config.dev_mode,
            )

        configs.append(("Instagram", _instagram_factory))

        # Twitter Watcher
        def _twitter_factory():  # noqa: ANN202
            from backend.watchers.twitter_watcher import TwitterWatcher

            keywords_env = os.getenv("TWITTER_KEYWORDS", "")
            keywords = [k.strip() for k in keywords_env.split(",") if k.strip()] or None
            return TwitterWatcher(
                vault_path=str(self.vault_path),
                session_path=os.getenv("TWITTER_SESSION_PATH", "config/twitter_session"),
                check_interval=int(os.getenv("TWITTER_CHECK_INTERVAL", "300")),
                keywords=keywords,
                headless=os.getenv("TWITTER_HEADLESS", "false").lower() == "true",
                dry_run=self.config.dry_run,
                dev_mode=self.config.dev_mode,
            )

        configs.append(("Twitter", _twitter_factory))

        return configs

    # ── Action Executor ──────────────────────────────────────────

    def _start_action_executor(self) -> None:
        """Start the action executor as an async task."""
        from backend.orchestrator.action_executor import ActionExecutor

        executor = ActionExecutor(self.config)
        self._action_executor_task = asyncio.create_task(
            executor.run(),
            name="action-executor",
        )
        logger.info("Started action executor (interval: %ds)", self.config.check_interval)

    # ── Dashboard Loop ───────────────────────────────────────────

    def _start_dashboard_loop(self) -> None:
        """Start the periodic dashboard update as an async task."""
        self._dashboard_task = asyncio.create_task(
            self._dashboard_loop(),
            name="dashboard-updater",
        )
        logger.info("Started dashboard updater (interval: %ds)", self.config.dashboard_interval)

    async def _dashboard_loop(self) -> None:
        """Periodically update vault/Dashboard.md."""
        from backend.orchestrator.dashboard import (
            DashboardState,
            count_vault_files,
            render_dashboard,
            write_dashboard,
        )

        # Write initial dashboard immediately
        await self._update_dashboard_once(
            DashboardState, count_vault_files, render_dashboard, write_dashboard
        )

        while True:
            await asyncio.sleep(self.config.dashboard_interval)
            await self._update_dashboard_once(
                DashboardState, count_vault_files, render_dashboard, write_dashboard
            )

    async def _update_dashboard_once(
        self, DashboardState, count_vault_files, render_dashboard, write_dashboard
    ) -> None:  # noqa: N803
        """Single dashboard update cycle."""
        try:
            import time

            uptime = int(time.time() - _iso_to_epoch(self._started_at)) if self._started_at else 0

            errors: list[str] = []
            for wt in self.watcher_tasks:
                if wt.status == WatcherStatus.ERROR or wt.status == WatcherStatus.FAILED:
                    errors.append(f"{wt.name}: {wt.last_error or 'unknown error'}")

            state = DashboardState(
                watchers=[wt.info for wt in self.watcher_tasks],
                vault_counts=count_vault_files(self.vault_path),
                dev_mode=self.config.dev_mode,
                last_update=now_iso(),
                uptime_seconds=uptime,
                errors=errors[-5:],
            )

            content = render_dashboard(state)
            await write_dashboard(self.vault_path, content)
        except Exception:
            logger.exception("Failed to update dashboard")

    # ── Content Schedule ─────────────────────────────────────────────────────

    async def _check_content_schedule(self) -> None:
        """Check if a LinkedIn post draft is due today and generate if so.

        Called on startup after _log_event("orchestrator_start", ...).
        Uses asyncio.to_thread() to wrap the synchronous ContentScheduler.
        Catches ContentStrategyError (missing strategy file) and logs WARNING.
        Catches all other exceptions and logs WARNING — never raises.
        """
        try:
            from backend.scheduler.content_scheduler import (  # noqa: I001
                ContentScheduler,
                ContentStrategyError as CSE,
            )

            scheduler = ContentScheduler(
                vault_path=self.vault_path,
                dev_mode=self.config.dev_mode,
                dry_run=self.config.dry_run,
            )
            result = await asyncio.to_thread(scheduler.run_if_due)

            if result.status == "generated":
                logger.info(
                    "Content scheduler: draft generated for topic=%r path=%s",
                    result.topic,
                    result.draft_path,
                )
            else:
                logger.debug(
                    "Content scheduler: %s (%s)", result.status, result.reason
                )

        except Exception as exc:
            from backend.scheduler.content_scheduler import ContentStrategyError as CSE
            if isinstance(exc, CSE):
                logger.warning(
                    "Content scheduler: strategy file missing or invalid — %s", exc
                )
            else:
                logger.warning("Content scheduler: unexpected error — %s", exc)

    # ── Briefing Schedule ────────────────────────────────────────────────────

    async def _check_briefing_schedule(self) -> None:
        """Check if a CEO briefing is due today and generate if so.

        Called on startup after _check_content_schedule().
        Uses asyncio.to_thread() to wrap the synchronous BriefingGenerator.
        Catches all exceptions and logs WARNING — never raises.
        """
        try:
            from backend.briefing.briefing_generator import BriefingGenerator  # noqa: I001

            generator = BriefingGenerator(
                vault_path=self.vault_path,
                dev_mode=self.config.dev_mode,
                dry_run=self.config.dry_run,
            )
            result = await asyncio.to_thread(generator.run_if_due)

            if result.status == "generated":
                logger.info(
                    "CEO briefing generated: %s (period=%s to %s)",
                    result.briefing_path,
                    result.period_start,
                    result.period_end,
                )
            else:
                logger.debug(
                    "CEO briefing: %s (%s)", result.status, result.reason
                )

        except Exception as exc:
            logger.warning("CEO briefing scheduler: unexpected error — %s", exc)

    # ── Ralph Wiggum Loops ────────────────────────────────────────────────────

    async def _check_ralph_loops(self) -> None:
        """Scan vault/Needs_Action/ for ralph_loop_task files and spawn loops.

        Files with frontmatter `type: ralph_loop_task` are processed by RalphLoop.
        On completion: task file moved to vault/Done/.
        On halt: task file stays in Needs_Action with `ralph_halt_reason` added.
        Never raises — all exceptions caught and logged as WARNING.
        """
        try:
            from backend.ralph_wiggum.ralph_loop import RalphLoop  # noqa: I001
            from backend.ralph_wiggum import CompletionStrategy, LoopStatus
            from backend.utils.frontmatter import parse_frontmatter, update_frontmatter

            needs_action = self.vault_path / "Needs_Action"
            if not needs_action.exists():
                return

            for task_file in sorted(needs_action.glob("*.md")):
                try:
                    fm = parse_frontmatter(task_file)
                except Exception:
                    continue

                if fm.get("type") != "ralph_loop_task":
                    continue

                prompt = fm.get("prompt", "")
                if not prompt:
                    logger.warning("ralph_loop_task file has no prompt: %s", task_file)
                    continue

                strategy_str = fm.get("completion_strategy", "promise")
                try:
                    strategy = CompletionStrategy(strategy_str)
                except ValueError:
                    strategy = CompletionStrategy.promise

                promise = fm.get("completion_promise", "TASK_COMPLETE")
                file_pattern = fm.get("completion_file_pattern")
                max_iterations = fm.get("max_iterations")
                if max_iterations is not None:
                    try:
                        max_iterations = int(max_iterations)
                    except (ValueError, TypeError):
                        max_iterations = None

                loop = RalphLoop(
                    vault_path=self.vault_path,
                    dev_mode=self.config.dev_mode,
                    dry_run=self.config.dry_run,
                )

                logger.info("Spawning Ralph loop for: %s", task_file.name)
                result = await asyncio.to_thread(
                    loop.start,
                    prompt,
                    strategy,
                    promise if strategy == CompletionStrategy.promise else None,
                    file_pattern if strategy == CompletionStrategy.file_movement else None,
                    max_iterations,
                )

                if result.status == LoopStatus.completed:
                    # Move task file to Done/
                    done_dir = self.vault_path / "Done"
                    done_dir.mkdir(parents=True, exist_ok=True)
                    dest = done_dir / task_file.name
                    import os as _os
                    _os.replace(str(task_file), str(dest))
                    logger.info(
                        "Ralph loop completed: task_id=%s, moved %s to Done/",
                        result.task_id,
                        task_file.name,
                    )
                    self._log_event(
                        "ralph_loop_completed",
                        "success",
                        f"task_id={result.task_id} iterations={result.iterations_run}",
                    )
                elif result.status == LoopStatus.halted:
                    # Update frontmatter with halt reason
                    halt_val = result.halt_reason.value if result.halt_reason else "unknown"
                    try:
                        update_frontmatter(task_file, {"ralph_halt_reason": halt_val})
                    except Exception:
                        pass
                    logger.warning(
                        "Ralph loop halted: task_id=%s, reason=%s, file=%s",
                        result.task_id,
                        halt_val,
                        task_file.name,
                    )
                    self._log_event(
                        "ralph_loop_halted",
                        "warning",
                        f"task_id={result.task_id} halt_reason={halt_val}",
                    )

        except Exception as exc:
            logger.warning("Ralph loop check failed: %s", exc)

    # ── Helpers ───────────────────────────────────────────────────

    def _ensure_vault_dirs(self) -> None:
        """Create any missing vault subdirectories."""
        for subdir in VAULT_SUBDIRS:
            (self.vault_path / subdir).mkdir(parents=True, exist_ok=True)
        logger.debug("Vault directories verified")

    def _log_event(self, action_type: str, result: str, details: str) -> None:
        """Log an orchestrator event to the audit trail."""
        try:
            log_action(
                self.log_dir,
                {
                    "timestamp": now_iso(),
                    "correlation_id": correlation_id(),
                    "actor": "orchestrator",
                    "action_type": action_type,
                    "target": "orchestrator",
                    "result": result,
                    "parameters": {"details": details, "dev_mode": self.config.dev_mode},
                },
            )
        except Exception:
            logger.exception("Failed to log orchestrator event")

    async def _wait_forever(self) -> None:
        """Block until the task is cancelled."""
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass


def _iso_to_epoch(iso_str: str | None) -> float:
    """Convert ISO 8601 timestamp to Unix epoch seconds."""
    if not iso_str:
        import time

        return time.time()
    from backend.utils.timestamps import parse_iso

    return parse_iso(iso_str).timestamp()
