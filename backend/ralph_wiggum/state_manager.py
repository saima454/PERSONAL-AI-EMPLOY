"""State manager for Ralph Wiggum Loop — CRUD for vault/ralph_wiggum/*.md files.

Shared by both hook-mode (stop_hook.py) and subprocess-mode (ralph_loop.py).
All write operations are no-ops when dry_run=True.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from backend.ralph_wiggum import (
    HaltReason,
    IterationRecord,
    LoopStatus,
    RalphTask,
    CompletionStrategy,
)
from backend.utils.frontmatter import extract_frontmatter, format_with_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso, today_iso
from backend.utils.uuid_utils import correlation_id

logger = logging.getLogger(__name__)

ITERATIONS_START = "<!-- ITERATIONS_SECTION_START -->"
ITERATIONS_END = "<!-- ITERATIONS_SECTION_END -->"


class StateManager:
    """Manages Ralph task state files in vault/ralph_wiggum/."""

    def __init__(self, vault_path: Path, dry_run: bool = False) -> None:
        self.vault_path = Path(vault_path)
        self.ralph_dir = self.vault_path / "ralph_wiggum"
        self.log_dir = self.vault_path / "Logs" / "actions"
        self.dry_run = dry_run

    # ── Write Operations ───────────────────────────────────────────────────────

    def create_task(self, task: RalphTask) -> Path:
        """Write initial state file for a new task.

        Returns the path to the created file. No-op if dry_run.
        """
        file_path = self.ralph_dir / f"{task.task_id}.md"

        if self.dry_run:
            logger.debug("[DRY_RUN] Would create task file: %s", file_path)
            return file_path

        self.ralph_dir.mkdir(parents=True, exist_ok=True)

        frontmatter = _task_to_frontmatter(task)
        body = _build_iterations_body(task.iterations)
        content = format_with_frontmatter(frontmatter, body)
        file_path.write_text(content, encoding="utf-8")

        logger.debug("Created task state file: %s", file_path)
        return file_path

    def update_task(self, task: RalphTask) -> None:
        """Overwrite existing state file with updated task state.

        Preserves any content outside the sentinel-protected iterations section.
        No-op if dry_run.
        """
        if self.dry_run:
            logger.debug("[DRY_RUN] Would update task: %s", task.task_id)
            return

        file_path = self.ralph_dir / f"{task.task_id}.md"

        if not file_path.exists():
            # Create if missing (e.g., first update after task creation failed)
            self.create_task(task)
            return

        # Read existing content to preserve any Notes section outside sentinels
        existing = file_path.read_text(encoding="utf-8")
        _, existing_body = extract_frontmatter(existing)

        # Extract content after ITERATIONS_END sentinel (Notes section etc.)
        notes_section = ""
        if ITERATIONS_END in existing_body:
            after_end = existing_body.split(ITERATIONS_END, 1)[-1]
            # Only keep if there's meaningful content
            stripped = after_end.strip()
            if stripped:
                notes_section = "\n\n" + stripped

        frontmatter = _task_to_frontmatter(task)
        iterations_body = _build_iterations_body(task.iterations)
        body = iterations_body + notes_section

        content = format_with_frontmatter(frontmatter, body)
        file_path.write_text(content, encoding="utf-8")

    def log_iteration(self, record: IterationRecord) -> None:
        """Log an iteration outcome to vault/Logs/actions/YYYY-MM-DD.json.

        No-op if dry_run.
        """
        if self.dry_run:
            return

        action_type = (
            "ralph_iteration_complete"
            if not record.halt_reason
            else "ralph_iteration_halted"
        )

        log_action(
            self.log_dir,
            {
                "timestamp": record.completed_at or now_iso(),
                "correlation_id": correlation_id(),
                "actor": "ralph_wiggum",
                "action_type": action_type,
                "target": record.task_id,
                "result": "completed" if record.completion_detected else "in_progress",
                "parameters": {
                    "iteration": record.iteration_number,
                    "duration_seconds": record.duration_seconds,
                    "completion_detected": record.completion_detected,
                    "halt_reason": record.halt_reason.value if record.halt_reason else None,
                },
            },
        )

    def log_loop_result(
        self,
        task: RalphTask,
        duration_seconds: float,
    ) -> None:
        """Log the final loop outcome (completed or halted).

        No-op if dry_run.
        """
        if self.dry_run:
            return

        action_type = (
            "ralph_loop_completed"
            if task.status == LoopStatus.completed
            else "ralph_loop_halted"
        )

        log_action(
            self.log_dir,
            {
                "timestamp": now_iso(),
                "correlation_id": correlation_id(),
                "actor": "ralph_wiggum",
                "action_type": action_type,
                "target": task.task_id,
                "result": task.status.value,
                "parameters": {
                    "task_id": task.task_id,
                    "iterations_run": task.current_iteration,
                    "status": task.status.value,
                    "halt_reason": task.halt_reason.value if task.halt_reason else None,
                    "duration_seconds": round(duration_seconds, 2),
                    "completion_strategy": task.completion_strategy.value,
                },
            },
        )

    # ── Read Operations ────────────────────────────────────────────────────────

    def load_task(self, task_id: str) -> RalphTask | None:
        """Load a single task by ID. Returns None if not found."""
        file_path = self.ralph_dir / f"{task_id}.md"
        if not file_path.exists():
            return None

        try:
            content = file_path.read_text(encoding="utf-8")
            fm, _ = extract_frontmatter(content)
            return _frontmatter_to_task(fm)
        except Exception as exc:
            logger.warning("Failed to load task %s: %s", task_id, exc)
            return None

    def load_all_tasks(self) -> list[RalphTask]:
        """Load all task files from vault/ralph_wiggum/, sorted newest first."""
        if not self.ralph_dir.exists():
            return []

        tasks: list[RalphTask] = []
        for file_path in sorted(self.ralph_dir.glob("*.md"), reverse=True):
            try:
                content = file_path.read_text(encoding="utf-8")
                fm, _ = extract_frontmatter(content)
                task = _frontmatter_to_task(fm)
                if task:
                    tasks.append(task)
            except Exception as exc:
                logger.warning("Failed to load task from %s: %s", file_path, exc)

        return tasks

    def emergency_stop_active(self) -> bool:
        """Return True if vault/STOP_RALPH sentinel file exists."""
        return (self.vault_path / "STOP_RALPH").exists()


# ── Private Helpers ────────────────────────────────────────────────────────────


def _task_to_frontmatter(task: RalphTask) -> dict:
    """Convert a RalphTask to a YAML-serializable dict for frontmatter."""
    return {
        "task_id": task.task_id,
        "prompt": task.prompt,
        "completion_strategy": task.completion_strategy.value,
        "completion_promise": task.completion_promise,
        "completion_file_pattern": task.completion_file_pattern,
        "max_iterations": task.max_iterations,
        "iteration_timeout": task.iteration_timeout,
        "total_timeout": task.total_timeout,
        "status": task.status.value,
        "current_iteration": task.current_iteration,
        "started_at": task.started_at,
        "last_iteration_at": task.last_iteration_at,
        "completed_at": task.completed_at,
        "halt_reason": task.halt_reason.value if task.halt_reason else None,
        "completed_artifact": task.completed_artifact,
        "session_id": task.session_id,
        "dev_mode": task.dev_mode,
    }


def _frontmatter_to_task(fm: dict) -> RalphTask | None:
    """Reconstruct a RalphTask from parsed frontmatter. Returns None on error."""
    if not fm or "task_id" not in fm:
        return None

    try:
        strategy_str = fm.get("completion_strategy", "promise")
        strategy = CompletionStrategy(strategy_str)

        status_str = fm.get("status", "in_progress")
        status = LoopStatus(status_str)

        halt_reason_str = fm.get("halt_reason")
        halt_reason = HaltReason(halt_reason_str) if halt_reason_str else None

        return RalphTask(
            task_id=fm["task_id"],
            prompt=fm.get("prompt", ""),
            completion_strategy=strategy,
            max_iterations=int(fm.get("max_iterations", 10)),
            iteration_timeout=float(fm.get("iteration_timeout", 300.0)),
            total_timeout=float(fm.get("total_timeout", 3600.0)),
            completion_promise=fm.get("completion_promise"),
            completion_file_pattern=fm.get("completion_file_pattern"),
            status=status,
            current_iteration=int(fm.get("current_iteration", 0)),
            started_at=fm.get("started_at", ""),
            last_iteration_at=fm.get("last_iteration_at", ""),
            completed_at=fm.get("completed_at", ""),
            halt_reason=halt_reason,
            completed_artifact=fm.get("completed_artifact"),
            session_id=fm.get("session_id"),
            dev_mode=bool(fm.get("dev_mode", True)),
            iterations=[],  # iteration records not stored in-memory after load
        )
    except (KeyError, ValueError) as exc:
        logger.warning("Failed to parse task frontmatter: %s", exc)
        return None


def _build_iterations_body(iterations: list[IterationRecord]) -> str:
    """Build the markdown body with sentinel-protected iteration table."""
    header = "\n## Iterations\n\n"
    table_header = "| # | Started | Duration | Status | Notes |\n"
    table_sep = "|---|---------|----------|--------|-------|\n"

    rows = ""
    for rec in iterations:
        status = "completed" if rec.completion_detected else (
            rec.halt_reason.value if rec.halt_reason else "ok"
        )
        notes = rec.error_message or rec.output_summary[:60] or "-"
        rows += f"| {rec.iteration_number} | {rec.started_at[-8:] if rec.started_at else '-'} | {rec.duration_seconds:.1f}s | {status} | {notes} |\n"

    return (
        f"{header}"
        f"{ITERATIONS_START}\n"
        f"{table_header}"
        f"{table_sep}"
        f"{rows}"
        f"{ITERATIONS_END}\n"
    )
