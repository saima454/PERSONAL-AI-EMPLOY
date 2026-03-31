"""Ralph Wiggum Loop — dataclasses, enums, and type definitions.

All shared types for the ralph_wiggum feature. Imported by ralph_loop.py,
state_manager.py, prompt_injector.py, and stop_hook.py.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────


class CompletionStrategy(str, Enum):
    """How the loop detects task completion."""

    promise = "promise"
    file_movement = "file_movement"


class LoopStatus(str, Enum):
    """Current lifecycle state of a Ralph loop."""

    in_progress = "in_progress"
    completed = "completed"
    halted = "halted"
    error = "error"


class HaltReason(str, Enum):
    """Why a loop was halted before completion."""

    max_iterations_reached = "max_iterations_reached"
    per_iteration_timeout = "per_iteration_timeout"
    total_timeout_exceeded = "total_timeout_exceeded"
    emergency_stop = "emergency_stop"
    subprocess_error = "subprocess_error"


# ── Config ────────────────────────────────────────────────────────────────────


@dataclass
class RalphConfig:
    """Configuration loaded from environment variables.

    Validates max_iterations > 0 and iteration_timeout > 0 in __post_init__.
    Invalid values log a WARNING and fall back to defaults.
    """

    max_iterations: int = 10
    iteration_timeout: float = 300.0
    total_timeout: float = 3600.0
    vault_path: Path = field(default_factory=lambda: Path("./vault"))
    dev_mode: bool = True
    dry_run: bool = False

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            logger.warning(
                "RALPH_MAX_ITERATIONS=%d is invalid (must be > 0), defaulting to 10",
                self.max_iterations,
            )
            self.max_iterations = 10
        if self.iteration_timeout <= 0:
            logger.warning(
                "RALPH_ITERATION_TIMEOUT=%.1f is invalid (must be > 0), defaulting to 300",
                self.iteration_timeout,
            )
            self.iteration_timeout = 300.0

    @classmethod
    def from_env(cls) -> RalphConfig:
        """Load configuration from environment variables."""
        try:
            max_iter = int(os.getenv("RALPH_MAX_ITERATIONS", "10"))
        except ValueError:
            max_iter = 10

        try:
            iter_timeout = float(os.getenv("RALPH_ITERATION_TIMEOUT", "300"))
        except ValueError:
            iter_timeout = 300.0

        try:
            total_timeout = float(os.getenv("RALPH_TOTAL_TIMEOUT", "3600"))
        except ValueError:
            total_timeout = 3600.0

        vault_path_str = os.getenv("VAULT_PATH", "./vault")

        return cls(
            max_iterations=max_iter,
            iteration_timeout=iter_timeout,
            total_timeout=total_timeout,
            vault_path=Path(vault_path_str),
            dev_mode=os.getenv("DEV_MODE", "true").lower() == "true",
            dry_run=os.getenv("DRY_RUN", "false").lower() == "true",
        )


# ── Core Task Entity ───────────────────────────────────────────────────────────


@dataclass
class IterationRecord:
    """Log entry for a single loop iteration."""

    iteration_number: int
    task_id: str
    started_at: str
    completed_at: str = ""
    duration_seconds: float = 0.0
    output_summary: str = ""
    completion_detected: bool = False
    halt_reason: HaltReason | None = None
    exit_code: int | None = None
    error_message: str = ""


@dataclass
class RalphTask:
    """Core state entity persisted to vault/ralph_wiggum/{task_id}.md."""

    task_id: str
    prompt: str
    completion_strategy: CompletionStrategy
    max_iterations: int
    iteration_timeout: float
    total_timeout: float

    # Optional completion parameters
    completion_promise: str | None = None
    completion_file_pattern: str | None = None

    # Runtime state
    status: LoopStatus = LoopStatus.in_progress
    current_iteration: int = 0
    started_at: str = ""
    last_iteration_at: str = ""
    completed_at: str = ""
    halt_reason: HaltReason | None = None
    completed_artifact: str | None = None
    session_id: str | None = None
    dev_mode: bool = True
    iterations: list[IterationRecord] = field(default_factory=list)


# ── Result Types ───────────────────────────────────────────────────────────────


@dataclass
class RalphRunResult:
    """Result returned by RalphLoop.start() and run_if_spawned()."""

    status: LoopStatus
    task_id: str
    iterations_run: int
    final_status: str
    state_file_path: str = ""
    halt_reason: HaltReason | None = None
    completed_artifact: str | None = None
    reason: str = ""

    @property
    def completed(self) -> bool:
        return self.status == LoopStatus.completed

    @property
    def halted(self) -> bool:
        return self.status == LoopStatus.halted


@dataclass
class RalphTaskSummary:
    """Summary of a single loop for the status display."""

    task_id: str
    status: LoopStatus
    completion_strategy: CompletionStrategy
    current_iteration: int
    max_iterations: int
    started_at: str
    completed_at: str = ""
    halt_reason: HaltReason | None = None
    elapsed_seconds: float = 0.0
    completed_artifact: str | None = None


@dataclass
class RalphStatusResult:
    """Result returned by RalphLoop.status()."""

    loops: list[RalphTaskSummary]
    active_count: int = 0
    completed_count: int = 0
    halted_count: int = 0
    emergency_stop_active: bool = False
