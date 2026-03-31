"""Ralph Wiggum Loop — main loop controller and CLI entry point.

Two modes:
  Subprocess mode: RalphLoop.start() invokes claude -p in a loop (orchestrator use)
  Hook mode: stop_hook.py intercepts onStop events (interactive Claude Code use)

Both modes share StateManager (vault state) and PromptInjector (context continuity).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import glob as glob_module
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from backend.ralph_wiggum import (
    CompletionStrategy,
    HaltReason,
    IterationRecord,
    LoopStatus,
    RalphConfig,
    RalphRunResult,
    RalphStatusResult,
    RalphTask,
    RalphTaskSummary,
)
from backend.ralph_wiggum.prompt_injector import PromptInjector
from backend.ralph_wiggum.state_manager import StateManager
from backend.utils.timestamps import now_iso, parse_iso

logger = logging.getLogger(__name__)


# ── Public helpers (used by tests) ────────────────────────────────────────────


def _check_completion(task: RalphTask, output: str) -> bool:
    """Check whether the task completion condition has been met.

    For promise strategy: checks if completion_promise string is in output.
    For file_movement strategy: checks if glob pattern matches any file.

    Mutates task.completed_artifact for file_movement when a match is found.
    """
    if task.completion_strategy == CompletionStrategy.promise:
        if task.completion_promise and task.completion_promise in output:
            return True
        return False

    if task.completion_strategy == CompletionStrategy.file_movement:
        if not task.completion_file_pattern:
            return False
        matches = sorted(glob_module.glob(task.completion_file_pattern))
        if matches:
            task.completed_artifact = matches[0]
            return True
        return False

    return False


# ── Loop Controller ────────────────────────────────────────────────────────────


class _LoopController:
    """Internal: runs the iteration loop with asyncio (timeout, sentinel, subprocess)."""

    def __init__(
        self,
        task: RalphTask,
        mgr: StateManager,
        injector: PromptInjector,
        config: RalphConfig,
    ) -> None:
        self.task = task
        self.mgr = mgr
        self.injector = injector
        self.config = config
        self._halt_event: asyncio.Event | None = None
        self._monitor_task: asyncio.Task | None = None

    async def run(self) -> RalphTask:
        """Main iteration loop. Returns the final task state."""
        task = self.task
        task.started_at = now_iso()
        self._halt_event = asyncio.Event()

        # Start background sentinel monitor
        self._monitor_task = asyncio.create_task(
            _sentinel_monitor(self.config.vault_path, self._halt_event),
            name="ralph-sentinel",
        )

        try:
            while task.current_iteration < task.max_iterations:
                # Check emergency stop
                if self._halt_event.is_set() or self.mgr.emergency_stop_active():
                    task.status = LoopStatus.halted
                    task.halt_reason = HaltReason.emergency_stop
                    break

                # Check total timeout
                elapsed = _elapsed_seconds(task.started_at)
                if elapsed >= task.total_timeout:
                    task.status = LoopStatus.halted
                    task.halt_reason = HaltReason.total_timeout_exceeded
                    break

                task.current_iteration += 1
                record = IterationRecord(
                    iteration_number=task.current_iteration,
                    task_id=task.task_id,
                    started_at=now_iso(),
                )

                # Run the iteration
                completed = await self._run_iteration(record)

                task.last_iteration_at = now_iso()
                task.iterations.append(record)
                self.mgr.update_task(task)
                self.mgr.log_iteration(record)

                if completed:
                    task.status = LoopStatus.completed
                    task.completed_at = now_iso()
                    break

                # Check if halt was triggered during iteration
                if task.status == LoopStatus.halted:
                    break

            else:
                # Exhausted all iterations without completion
                if task.status == LoopStatus.in_progress:
                    task.status = LoopStatus.halted
                    task.halt_reason = HaltReason.max_iterations_reached

        finally:
            # Cancel sentinel monitor
            if self._monitor_task and not self._monitor_task.done():
                self._monitor_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait_for(self._monitor_task, timeout=1.0)

        if not task.completed_at and task.status != LoopStatus.in_progress:
            task.completed_at = now_iso()

        self.mgr.update_task(task)
        return task

    async def _run_iteration(self, record: IterationRecord) -> bool:
        """Run a single iteration. Returns True if completion detected.

        Wraps the subprocess (or simulation) in asyncio.wait_for for timeout.
        Sets record fields from iteration output. Never raises.
        """
        task = self.task
        iter_start = datetime.now(UTC)

        # Calculate remaining time for total timeout
        elapsed_total = _elapsed_seconds(task.started_at)
        remaining = task.total_timeout - elapsed_total
        timeout = min(self.config.iteration_timeout, remaining)

        if timeout <= 0:
            task.status = LoopStatus.halted
            task.halt_reason = HaltReason.total_timeout_exceeded
            record.halt_reason = HaltReason.total_timeout_exceeded
            record.error_message = "Total timeout exceeded before iteration started"
            return False

        try:
            # Build the prompt for this iteration
            prompt = self.injector.build_continuation_prompt(
                task.prompt,
                task.iterations,  # previous iterations only
            )

            if self.config.dev_mode:
                coro = self._simulate_iteration(record, task)
            else:
                coro = self._call_claude(prompt, task.session_id)

            if self.config.dev_mode:
                output = await asyncio.wait_for(coro, timeout=timeout)
                session_id = task.session_id
            else:
                output, session_id = await asyncio.wait_for(coro, timeout=timeout)
                if session_id:
                    task.session_id = session_id

        except asyncio.TimeoutError:
            record.halt_reason = HaltReason.per_iteration_timeout
            record.error_message = f"Timeout after {self.config.iteration_timeout:.0f}s"
            record.completed_at = now_iso()
            record.duration_seconds = (datetime.now(UTC) - iter_start).total_seconds()
            task.status = LoopStatus.halted
            task.halt_reason = HaltReason.per_iteration_timeout
            logger.warning(
                "Iteration %d timed out after %.0fs",
                record.iteration_number,
                self.config.iteration_timeout,
            )
            return False

        except Exception as exc:
            record.halt_reason = HaltReason.subprocess_error
            record.error_message = str(exc)[:200]
            record.completed_at = now_iso()
            record.duration_seconds = (datetime.now(UTC) - iter_start).total_seconds()
            task.status = LoopStatus.halted
            task.halt_reason = HaltReason.subprocess_error
            logger.error("Iteration %d error: %s", record.iteration_number, exc)
            return False

        # Success path
        record.output_summary = output[:500] if output else ""
        record.completed_at = now_iso()
        record.duration_seconds = (datetime.now(UTC) - iter_start).total_seconds()
        record.exit_code = 0

        # Check completion
        completed = _check_completion(task, output)
        record.completion_detected = completed

        mode_prefix = "[DEV_MODE] " if self.config.dev_mode else ""
        logger.info(
            "%sIteration %d/%d: %.1fs%s",
            mode_prefix,
            record.iteration_number,
            task.max_iterations,
            record.duration_seconds,
            " — completion detected" if completed else "",
        )
        if completed and task.completion_strategy == CompletionStrategy.file_movement:
            task.completed_at = now_iso()

        return completed

    async def _call_claude(self, prompt: str, session_id: str | None) -> tuple[str, str]:
        """Invoke claude -p subprocess and return (output, session_id).

        Uses asyncio.to_thread to avoid blocking the event loop.
        """
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if session_id:
            cmd += ["--resume", session_id]

        def _run() -> tuple[str, str]:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"claude exit {result.returncode}: {result.stderr[:200]}"
                )
            data = json.loads(result.stdout)
            return data.get("result", ""), data.get("session_id", "") or ""

        return await asyncio.to_thread(_run)

    async def _simulate_iteration(
        self, record: IterationRecord, task: RalphTask
    ) -> str:
        """DEV_MODE simulation: sleep + generate fake output.

        Auto-outputs completion marker at iteration 3 (or max_iterations if < 3).
        """
        await asyncio.sleep(1.0)

        output = (
            f"[DEV_MODE] Iteration {record.iteration_number}: "
            f"processed 1 file in vault/Needs_Action/"
        )

        # Auto-complete at iteration 3 (only when max_iterations allows it and
        # promise is "TASK_COMPLETE" — non-standard promises like __NEVER__ are not
        # auto-output so tests can exercise the halt path)
        complete_at = 3
        is_standard_promise = (
            task.completion_strategy == CompletionStrategy.promise
            and task.completion_promise == "TASK_COMPLETE"
        )
        if record.iteration_number >= complete_at and (
            is_standard_promise or task.completion_strategy == CompletionStrategy.file_movement
        ):
            if is_standard_promise:
                output += f" {task.completion_promise}"
            elif task.completion_strategy == CompletionStrategy.file_movement:
                # Simulate file appearance for file-movement in DEV_MODE
                if task.completion_file_pattern:
                    pattern_path = Path(task.completion_file_pattern)
                    target = pattern_path.parent / f"DEV_MODE_complete_{task.task_id}.md"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"DEV_MODE completed task {task.task_id}", encoding="utf-8")

        return output


# ── Sentinel Monitor ──────────────────────────────────────────────────────────


async def _sentinel_monitor(vault_path: Path, halt_event: asyncio.Event) -> None:
    """Background task: checks vault/STOP_RALPH every 1 second.

    Sets halt_event when sentinel is found.
    """
    sentinel = vault_path / "STOP_RALPH"
    while True:
        if sentinel.exists():
            halt_event.set()
            return
        await asyncio.sleep(1.0)


# ── Elapsed time helper ───────────────────────────────────────────────────────


def _elapsed_seconds(started_at: str) -> float:
    """Return seconds elapsed since started_at ISO timestamp."""
    if not started_at:
        return 0.0
    try:
        dt = parse_iso(started_at)
        return (datetime.now(UTC) - dt).total_seconds()
    except (ValueError, OSError):
        return 0.0


# ── Public API ────────────────────────────────────────────────────────────────


class RalphLoop:
    """Public API for the Ralph Wiggum Loop.

    Usage:
        loop = RalphLoop()
        result = loop.start("Process vault files", CompletionStrategy.promise,
                            completion_promise="TASK_COMPLETE")
    """

    def __init__(
        self,
        vault_path: Path | str | None = None,
        dev_mode: bool | None = None,
        dry_run: bool | None = None,
        config: RalphConfig | None = None,
    ) -> None:
        if config is not None:
            self.config = config
        else:
            self.config = RalphConfig.from_env()

        # Override with explicit kwargs
        if vault_path is not None:
            self.config.vault_path = Path(vault_path)
        if dev_mode is not None:
            self.config.dev_mode = dev_mode
        if dry_run is not None:
            self.config.dry_run = dry_run

    def start(
        self,
        prompt: str,
        completion_strategy: CompletionStrategy = CompletionStrategy.promise,
        completion_promise: str | None = None,
        completion_file_pattern: str | None = None,
        max_iterations: int | None = None,
    ) -> RalphRunResult:
        """Start a Ralph loop. Blocks until completion or halt.

        Args:
            prompt: The task prompt text.
            completion_strategy: How to detect completion (promise or file_movement).
            completion_promise: Marker string in output (required for promise strategy).
            completion_file_pattern: Glob pattern in vault/Done/ (required for file_movement).
            max_iterations: Override max iterations for this loop.

        Returns:
            RalphRunResult with final status, task_id, iterations_run.
        """
        # Validate
        if completion_strategy == CompletionStrategy.promise and not completion_promise:
            raise ValueError("completion_promise is required for promise strategy")
        if completion_strategy == CompletionStrategy.file_movement and not completion_file_pattern:
            raise ValueError("completion_file_pattern is required for file_movement strategy")

        # Generate task ID
        task_id = f"RW_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

        effective_max = max_iterations if max_iterations is not None else self.config.max_iterations

        task = RalphTask(
            task_id=task_id,
            prompt=prompt,
            completion_strategy=completion_strategy,
            max_iterations=effective_max,
            iteration_timeout=self.config.iteration_timeout,
            total_timeout=self.config.total_timeout,
            completion_promise=completion_promise,
            completion_file_pattern=completion_file_pattern,
            dev_mode=self.config.dev_mode,
        )

        mgr = StateManager(self.config.vault_path, dry_run=self.config.dry_run)
        state_file = mgr.create_task(task)

        injector = PromptInjector()
        controller = _LoopController(task, mgr, injector, self.config)

        # Run the async loop
        try:
            asyncio.run(controller.run())
        except RuntimeError as exc:
            # asyncio.run() called from within existing event loop (e.g., tests)
            if "cannot run nested" in str(exc).lower():
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(controller.run())
                finally:
                    loop.close()
            else:
                task.status = LoopStatus.error
                task.halt_reason = HaltReason.subprocess_error
                mgr.update_task(task)

        start_ts = task.started_at or now_iso()
        duration = _elapsed_seconds(start_ts)
        mgr.log_loop_result(task, duration)

        return RalphRunResult(
            status=task.status,
            task_id=task.task_id,
            iterations_run=task.current_iteration,
            final_status=task.status.value,
            state_file_path=str(state_file),
            halt_reason=task.halt_reason,
            completed_artifact=task.completed_artifact,
        )

    def status(self, task_id: str | None = None) -> RalphStatusResult:
        """Return status of all loops (or a specific loop if task_id provided)."""
        mgr = StateManager(self.config.vault_path)
        all_tasks = mgr.load_all_tasks()

        if task_id:
            all_tasks = [t for t in all_tasks if t.task_id == task_id]

        now = datetime.now(UTC)
        summaries: list[RalphTaskSummary] = []

        for task in all_tasks:
            elapsed = _elapsed_seconds(task.started_at)
            summaries.append(
                RalphTaskSummary(
                    task_id=task.task_id,
                    status=task.status,
                    completion_strategy=task.completion_strategy,
                    current_iteration=task.current_iteration,
                    max_iterations=task.max_iterations,
                    started_at=task.started_at,
                    completed_at=task.completed_at,
                    halt_reason=task.halt_reason,
                    elapsed_seconds=elapsed,
                    completed_artifact=task.completed_artifact,
                )
            )

        active = [s for s in summaries if s.status == LoopStatus.in_progress]
        completed = [s for s in summaries if s.status == LoopStatus.completed]
        halted = [s for s in summaries if s.status == LoopStatus.halted]

        return RalphStatusResult(
            loops=summaries,
            active_count=len(active),
            completed_count=len(completed),
            halted_count=len(halted),
            emergency_stop_active=mgr.emergency_stop_active(),
        )


# ── CLI Entry Point ────────────────────────────────────────────────────────────


def _print_result(result: RalphRunResult) -> None:
    """Print loop result in human-readable format."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    if result.status == LoopStatus.completed:
        print(f"\u2705 Loop completed: {result.task_id}")
        print(f"   Iterations: {result.iterations_run}")
        if result.completed_artifact:
            print(f"   Artifact: {result.completed_artifact}")
        if result.state_file_path:
            print(f"   State file: {result.state_file_path}")
    else:
        reason = result.halt_reason.value if result.halt_reason else "unknown"
        print(f"\u26a0\ufe0f  Loop halted: {result.task_id}")
        print(f"   Reason: {reason}")
        print(f"   Iterations: {result.iterations_run}")
        if result.state_file_path:
            print(f"   State file: {result.state_file_path}")


def _print_status(result: RalphStatusResult) -> None:
    """Print status in human-readable format."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    if not result.loops:
        print("No Ralph loops found.")
        return

    print("Ralph Loop Status")
    print("=================")
    stop_status = "ACTIVE" if result.emergency_stop_active else "INACTIVE"
    print(f"Emergency Stop: {stop_status}")
    print()

    if result.active_count:
        print(f"Active Loops ({result.active_count}):")
        for s in result.loops:
            if s.status == LoopStatus.in_progress:
                print(
                    f"  {s.task_id} \u2014 in_progress "
                    f"(iter {s.current_iteration}/{s.max_iterations}, "
                    f"{s.elapsed_seconds:.0f}s, "
                    f"strategy: {s.completion_strategy.value})"
                )

    if result.completed_count:
        print(f"\nCompleted Loops ({result.completed_count}):")
        for s in result.loops:
            if s.status == LoopStatus.completed:
                print(
                    f"  {s.task_id} \u2014 completed "
                    f"(iter {s.current_iteration}/{s.max_iterations}, "
                    f"{s.elapsed_seconds:.0f}s)"
                )

    if result.halted_count:
        print(f"\nHalted Loops ({result.halted_count}):")
        for s in result.loops:
            if s.status == LoopStatus.halted:
                reason = s.halt_reason.value if s.halt_reason else "unknown"
                print(
                    f"  {s.task_id} \u2014 halted: {reason} "
                    f"({s.current_iteration}/{s.max_iterations}, "
                    f"{s.elapsed_seconds:.0f}s)"
                )


def main() -> None:
    """CLI entry point for python -m backend.ralph_wiggum."""
    load_dotenv("config/.env")

    parser = argparse.ArgumentParser(
        prog="ralph_wiggum",
        description="Ralph Wiggum Loop — keeps Claude Code iterating until task complete",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("prompt", nargs="?", help="The task prompt text")
    group.add_argument(
        "--status",
        nargs="?",
        const=True,
        metavar="TASK_ID",
        help="Show loop status (optionally for a specific TASK_ID)",
    )

    parser.add_argument(
        "--completion-promise",
        metavar="STR",
        help="Completion marker string in Claude output (promise strategy)",
    )
    parser.add_argument(
        "--completion-file",
        metavar="GLOB",
        help="Glob pattern for completion file in vault/Done/ (file_movement strategy)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        metavar="N",
        help="Override max iterations for this loop",
    )
    parser.add_argument(
        "--vault-path",
        metavar="PATH",
        help="Override vault directory path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without writing files or logs",
    )

    args = parser.parse_args()

    # Build RalphLoop instance
    loop_kwargs: dict = {}
    if args.vault_path:
        loop_kwargs["vault_path"] = args.vault_path
    if args.dry_run:
        loop_kwargs["dry_run"] = True

    loop = RalphLoop(**loop_kwargs)

    # Status command
    if args.status is not None:
        task_id = args.status if args.status is not True else None
        result = loop.status(task_id=task_id)
        _print_status(result)
        sys.exit(0)

    # Start loop command
    prompt = args.prompt
    if not prompt:
        parser.error("prompt is required when not using --status")

    if args.completion_promise and args.completion_file:
        parser.error("--completion-promise and --completion-file are mutually exclusive")
    if not args.completion_promise and not args.completion_file:
        parser.error("one of --completion-promise or --completion-file is required")

    if args.completion_promise:
        strategy = CompletionStrategy.promise
        promise = args.completion_promise
        file_pattern = None
    else:
        strategy = CompletionStrategy.file_movement
        promise = None
        file_pattern = args.completion_file

    result = loop.start(
        prompt=prompt,
        completion_strategy=strategy,
        completion_promise=promise,
        completion_file_pattern=file_pattern,
        max_iterations=args.max_iterations,
    )

    _print_result(result)
    sys.exit(0 if result.completed else 1)


if __name__ == "__main__":
    main()
