"""Tests for the Ralph Wiggum Loop feature (001-ralph-loop).

Test classes:
  TestRalphConfig         — T007: env var loading, validation, defaults
  TestStateManager        — T008: vault file CRUD, dry_run, emergency_stop
  TestPromptInjector      — T009: continuation prompt building
  TestFileMovement        — T014: file-movement completion strategy
  TestSafetyLimits        — T017: max iterations, timeouts, emergency stop
  TestStatus              — T021: status command output
  TestStopHook            — T024: onStop hook JSON contract
  TestOrchestratorInteg   — T025: orchestrator _check_ralph_loops integration
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ralph_wiggum import (
    CompletionStrategy,
    HaltReason,
    IterationRecord,
    LoopStatus,
    RalphConfig,
    RalphRunResult,
    RalphTask,
    RalphTaskSummary,
)
from backend.ralph_wiggum.prompt_injector import PromptInjector
from backend.ralph_wiggum.state_manager import StateManager
from backend.utils.timestamps import now_iso


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_task(
    task_id: str = "RW_20260224_080000",
    status: LoopStatus = LoopStatus.in_progress,
    current_iteration: int = 0,
    max_iterations: int = 5,
    strategy: CompletionStrategy = CompletionStrategy.promise,
    promise: str | None = "TASK_COMPLETE",
    file_pattern: str | None = None,
) -> RalphTask:
    return RalphTask(
        task_id=task_id,
        prompt="Test task prompt",
        completion_strategy=strategy,
        max_iterations=max_iterations,
        iteration_timeout=60.0,
        total_timeout=300.0,
        completion_promise=promise,
        completion_file_pattern=file_pattern,
        status=status,
        current_iteration=current_iteration,
        started_at=now_iso(),
        dev_mode=True,
    )


def _make_iteration(
    n: int = 1,
    task_id: str = "RW_20260224_080000",
    output: str = "output summary",
    completion_detected: bool = False,
) -> IterationRecord:
    return IterationRecord(
        iteration_number=n,
        task_id=task_id,
        started_at=now_iso(),
        completed_at=now_iso(),
        duration_seconds=1.5,
        output_summary=output,
        completion_detected=completion_detected,
    )


# ── T007: TestRalphConfig ──────────────────────────────────────────────────────


class TestRalphConfig:
    """Tests for RalphConfig env var loading and validation."""

    def test_env_vars_loaded_correctly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env vars override defaults."""
        monkeypatch.setenv("RALPH_MAX_ITERATIONS", "5")
        monkeypatch.setenv("RALPH_ITERATION_TIMEOUT", "120")
        monkeypatch.setenv("RALPH_TOTAL_TIMEOUT", "600")
        monkeypatch.setenv("DEV_MODE", "false")
        monkeypatch.setenv("DRY_RUN", "true")

        cfg = RalphConfig.from_env()

        assert cfg.max_iterations == 5
        assert cfg.iteration_timeout == 120.0
        assert cfg.total_timeout == 600.0
        assert cfg.dev_mode is False
        assert cfg.dry_run is True

    def test_invalid_max_iterations_defaults_to_10(self) -> None:
        """max_iterations=0 logs WARNING and defaults to 10 — no exception raised."""
        cfg = RalphConfig(max_iterations=0)
        assert cfg.max_iterations == 10

    def test_invalid_iteration_timeout_defaults_to_300(self) -> None:
        """iteration_timeout=-1 logs WARNING and defaults to 300 — no exception raised."""
        cfg = RalphConfig(iteration_timeout=-1.0)
        assert cfg.iteration_timeout == 300.0

    def test_defaults_when_env_vars_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RalphConfig.from_env() uses defaults when env vars not set."""
        for var in ("RALPH_MAX_ITERATIONS", "RALPH_ITERATION_TIMEOUT", "RALPH_TOTAL_TIMEOUT"):
            monkeypatch.delenv(var, raising=False)

        cfg = RalphConfig.from_env()

        assert cfg.max_iterations == 10
        assert cfg.iteration_timeout == 300.0
        assert cfg.total_timeout == 3600.0


# ── T008: TestStateManager ────────────────────────────────────────────────────


class TestStateManager:
    """Tests for StateManager CRUD operations."""

    def test_create_task_writes_yaml_frontmatter(self, tmp_path: Path) -> None:
        """create_task writes a file with correct task_id in YAML frontmatter."""
        mgr = StateManager(tmp_path)
        task = _make_task()
        file_path = mgr.create_task(task)

        assert file_path.exists()
        content = file_path.read_text(encoding="utf-8")
        assert "task_id: RW_20260224_080000" in content
        assert "status: in_progress" in content

    def test_update_task_overwrites_frontmatter_preserves_notes(self, tmp_path: Path) -> None:
        """update_task rewrites frontmatter while preserving Notes section."""
        mgr = StateManager(tmp_path)
        task = _make_task()
        file_path = mgr.create_task(task)

        # Append a Notes section after the sentinel
        existing = file_path.read_text(encoding="utf-8")
        file_path.write_text(existing + "\n## Notes\n\nManual note preserved.", encoding="utf-8")

        # Update status
        task.status = LoopStatus.completed
        task.current_iteration = 3
        mgr.update_task(task)

        content = file_path.read_text(encoding="utf-8")
        assert "status: completed" in content
        assert "current_iteration: 3" in content
        assert "Manual note preserved." in content

    def test_load_task_returns_matching_task(self, tmp_path: Path) -> None:
        """load_task returns a RalphTask matching the saved task_id."""
        mgr = StateManager(tmp_path)
        task = _make_task(task_id="RW_20260224_090000")
        mgr.create_task(task)

        loaded = mgr.load_task("RW_20260224_090000")

        assert loaded is not None
        assert loaded.task_id == "RW_20260224_090000"
        assert loaded.status == LoopStatus.in_progress

    def test_load_task_returns_none_for_unknown_id(self, tmp_path: Path) -> None:
        """load_task returns None for a task ID that doesn't exist."""
        mgr = StateManager(tmp_path)
        result = mgr.load_task("RW_NONEXISTENT_000")
        assert result is None

    def test_load_all_tasks_sorted_newest_first(self, tmp_path: Path) -> None:
        """load_all_tasks returns tasks sorted by filename (newest first)."""
        mgr = StateManager(tmp_path)
        task_a = _make_task(task_id="RW_20260224_080000")
        task_b = _make_task(task_id="RW_20260224_090000")
        mgr.create_task(task_a)
        mgr.create_task(task_b)

        tasks = mgr.load_all_tasks()

        assert len(tasks) == 2
        # Sorted newest first by filename (090000 > 080000)
        assert tasks[0].task_id == "RW_20260224_090000"

    def test_emergency_stop_active_true_when_file_exists(self, tmp_path: Path) -> None:
        """emergency_stop_active returns True when vault/STOP_RALPH exists."""
        mgr = StateManager(tmp_path)
        (tmp_path / "STOP_RALPH").touch()
        assert mgr.emergency_stop_active() is True

    def test_emergency_stop_active_false_when_absent(self, tmp_path: Path) -> None:
        """emergency_stop_active returns False when vault/STOP_RALPH doesn't exist."""
        mgr = StateManager(tmp_path)
        assert mgr.emergency_stop_active() is False

    def test_dry_run_create_task_no_file_created(self, tmp_path: Path) -> None:
        """dry_run=True means create_task is a no-op — no file written."""
        mgr = StateManager(tmp_path, dry_run=True)
        task = _make_task()
        file_path = mgr.create_task(task)

        assert not file_path.exists()


# ── T009: TestPromptInjector ──────────────────────────────────────────────────


class TestPromptInjector:
    """Tests for PromptInjector.build_continuation_prompt()."""

    def test_empty_records_returns_original_prompt(self) -> None:
        """No iteration records → original prompt returned unchanged."""
        result = PromptInjector.build_continuation_prompt("do the task", [])
        assert result == "do the task"

    def test_one_record_includes_original_and_summary(self) -> None:
        """One record → prompt includes original + iteration summary."""
        rec = _make_iteration(n=1, output="Processed 3 files")
        result = PromptInjector.build_continuation_prompt("do the task", [rec])

        assert "do the task" in result
        assert "Iteration 1: Processed 3 files" in result
        assert "Continue from where you left off." in result

    def test_max_summary_chars_truncates_long_output(self) -> None:
        """Long output_summary is truncated to max_summary_chars."""
        long_output = "x" * 1000
        rec = _make_iteration(n=1, output=long_output)
        result = PromptInjector.build_continuation_prompt("task", [rec], max_summary_chars=10)

        # Only first 10 chars of output appear
        assert "x" * 10 in result
        assert "x" * 11 not in result

    def test_multiple_records_all_included_in_order(self) -> None:
        """Multiple records → all summaries included in iteration order."""
        recs = [
            _make_iteration(n=1, output="First output"),
            _make_iteration(n=2, output="Second output"),
            _make_iteration(n=3, output="Third output"),
        ]
        result = PromptInjector.build_continuation_prompt("task", recs)

        assert "Iteration 1: First output" in result
        assert "Iteration 2: Second output" in result
        assert "Iteration 3: Third output" in result
        # Order preserved
        idx1 = result.index("Iteration 1")
        idx2 = result.index("Iteration 2")
        idx3 = result.index("Iteration 3")
        assert idx1 < idx2 < idx3


# ── T014: TestFileMovement ────────────────────────────────────────────────────


class TestFileMovement:
    """Tests for file-movement completion strategy in _LoopController."""

    def test_check_completion_false_when_no_matching_file(self, tmp_path: Path) -> None:
        """_check_completion returns False when no file matches the glob."""
        from backend.ralph_wiggum.ralph_loop import _check_completion

        task = _make_task(
            strategy=CompletionStrategy.file_movement,
            promise=None,
            file_pattern=str(tmp_path / "Done" / "*.md"),
        )
        result = _check_completion(task, "")
        assert result is False

    def test_check_completion_true_when_file_exists(self, tmp_path: Path) -> None:
        """_check_completion returns True and sets completed_artifact when file exists."""
        from backend.ralph_wiggum.ralph_loop import _check_completion

        done_dir = tmp_path / "Done"
        done_dir.mkdir()
        target = done_dir / "INVOICE_123.md"
        target.write_text("done", encoding="utf-8")

        task = _make_task(
            strategy=CompletionStrategy.file_movement,
            promise=None,
            file_pattern=str(done_dir / "*.md"),
        )
        result = _check_completion(task, "")
        assert result is True
        assert task.completed_artifact == str(target)

    def test_first_sorted_match_used(self, tmp_path: Path) -> None:
        """When multiple files match, the first sorted one is used."""
        from backend.ralph_wiggum.ralph_loop import _check_completion

        done_dir = tmp_path / "Done"
        done_dir.mkdir()
        (done_dir / "b_file.md").write_text("b", encoding="utf-8")
        (done_dir / "a_file.md").write_text("a", encoding="utf-8")

        task = _make_task(
            strategy=CompletionStrategy.file_movement,
            promise=None,
            file_pattern=str(done_dir / "*.md"),
        )
        _check_completion(task, "")
        assert task.completed_artifact is not None
        assert "a_file.md" in task.completed_artifact

    def test_wrong_file_pattern_loops_to_max_iterations(self, tmp_path: Path) -> None:
        """Wrong pattern → _check_completion returns False, no crash."""
        from backend.ralph_wiggum.ralph_loop import _check_completion

        task = _make_task(
            strategy=CompletionStrategy.file_movement,
            promise=None,
            file_pattern=str(tmp_path / "nonexistent" / "*.md"),
        )
        # Should not raise, just return False
        result = _check_completion(task, "")
        assert result is False


# ── T017: TestSafetyLimits ────────────────────────────────────────────────────


class TestSafetyLimits:
    """Tests for safety limits: max iterations, timeouts, emergency stop."""

    def test_loop_halts_at_max_iterations(self, tmp_path: Path) -> None:
        """Loop halts after max_iterations with halt_reason=max_iterations_reached."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        loop = RalphLoop(vault_path=tmp_path, dev_mode=True, dry_run=False)
        result = loop.start(
            prompt="impossible task",
            completion_strategy=CompletionStrategy.promise,
            completion_promise="__NEVER_OUTPUT_THIS__",
            max_iterations=3,
        )

        assert result.status == LoopStatus.halted
        assert result.halt_reason == HaltReason.max_iterations_reached
        assert result.iterations_run == 3

    def test_per_iteration_timeout_halts_loop(self, tmp_path: Path) -> None:
        """Per-iteration timeout raises asyncio.TimeoutError → HaltReason.per_iteration_timeout."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        # Use very short timeout and mock _call_claude to hang
        async def slow_claude(*args, **kwargs):
            await asyncio.sleep(10)  # Much longer than timeout
            return ("output", "session123")

        loop = RalphLoop(vault_path=tmp_path, dev_mode=False, dry_run=False)
        loop.config.iteration_timeout = 0.1  # 100ms timeout

        with patch("backend.ralph_wiggum.ralph_loop._LoopController._call_claude", side_effect=slow_claude):
            result = loop.start(
                prompt="slow task",
                completion_strategy=CompletionStrategy.promise,
                completion_promise="DONE",
                max_iterations=5,
            )

        assert result.halt_reason == HaltReason.per_iteration_timeout

    def test_total_timeout_halts_loop(self, tmp_path: Path) -> None:
        """Total timeout exceeded → halt_reason=total_timeout_exceeded."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop
        from backend.utils.timestamps import parse_iso
        from datetime import datetime, UTC, timedelta

        loop = RalphLoop(vault_path=tmp_path, dev_mode=True, dry_run=False)
        loop.config.total_timeout = 0.01  # 10ms — will be exceeded immediately

        result = loop.start(
            prompt="task",
            completion_strategy=CompletionStrategy.promise,
            completion_promise="__NEVER__",
            max_iterations=10,
        )

        assert result.halt_reason == HaltReason.total_timeout_exceeded

    def test_emergency_stop_halts_loop(self, tmp_path: Path) -> None:
        """vault/STOP_RALPH sentinel halts loop with halt_reason=emergency_stop."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        # Create sentinel before loop starts
        (tmp_path / "STOP_RALPH").touch()

        loop = RalphLoop(vault_path=tmp_path, dev_mode=True, dry_run=False)
        result = loop.start(
            prompt="task",
            completion_strategy=CompletionStrategy.promise,
            completion_promise="__NEVER__",
            max_iterations=10,
        )

        assert result.halt_reason == HaltReason.emergency_stop

    def test_dev_mode_completes_in_3_iterations(self, tmp_path: Path) -> None:
        """DEV_MODE simulation auto-completes at iteration 3."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        loop = RalphLoop(vault_path=tmp_path, dev_mode=True, dry_run=False)
        result = loop.start(
            prompt="task",
            completion_strategy=CompletionStrategy.promise,
            completion_promise="TASK_COMPLETE",
            max_iterations=10,
        )

        assert result.status == LoopStatus.completed
        assert result.iterations_run == 3

    def test_dry_run_no_state_files_created(self, tmp_path: Path) -> None:
        """dry_run=True → loop runs but no files created in vault/ralph_wiggum/."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        loop = RalphLoop(vault_path=tmp_path, dev_mode=True, dry_run=True)
        loop.start(
            prompt="task",
            completion_strategy=CompletionStrategy.promise,
            completion_promise="TASK_COMPLETE",
            max_iterations=5,
        )

        ralph_dir = tmp_path / "ralph_wiggum"
        files = list(ralph_dir.glob("*.md")) if ralph_dir.exists() else []
        assert files == []

    def test_halt_reason_recorded_in_state_file(self, tmp_path: Path) -> None:
        """halt_reason is persisted to state file on halt."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        loop = RalphLoop(vault_path=tmp_path, dev_mode=True, dry_run=False)
        result = loop.start(
            prompt="task",
            completion_strategy=CompletionStrategy.promise,
            completion_promise="__NEVER__",
            max_iterations=2,
        )

        state_file = tmp_path / "ralph_wiggum" / f"{result.task_id}.md"
        assert state_file.exists()
        content = state_file.read_text(encoding="utf-8")
        assert "halt_reason: max_iterations_reached" in content

    def test_cli_exit_code_1_on_halt(self, tmp_path: Path) -> None:
        """RalphRunResult.halted is True when loop is halted."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        loop = RalphLoop(vault_path=tmp_path, dev_mode=True, dry_run=False)
        result = loop.start(
            prompt="task",
            completion_strategy=CompletionStrategy.promise,
            completion_promise="__NEVER__",
            max_iterations=2,
        )

        assert result.halted is True
        assert result.completed is False


# ── T021: TestStatus ──────────────────────────────────────────────────────────


class TestStatus:
    """Tests for RalphLoop.status() command."""

    def test_status_no_state_files_returns_empty(self, tmp_path: Path) -> None:
        """status() with no state files returns RalphStatusResult with empty loops."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        loop = RalphLoop(vault_path=tmp_path)
        result = loop.status()

        assert result.loops == []
        assert result.active_count == 0

    def test_status_with_completed_task_returns_summary(self, tmp_path: Path) -> None:
        """status() with one completed task returns correct summary."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        mgr = StateManager(tmp_path)
        task = _make_task(task_id="RW_20260224_080000", status=LoopStatus.completed)
        task.current_iteration = 3
        mgr.create_task(task)

        loop = RalphLoop(vault_path=tmp_path)
        result = loop.status()

        assert len(result.loops) == 1
        assert result.loops[0].task_id == "RW_20260224_080000"
        assert result.loops[0].status == LoopStatus.completed
        assert result.completed_count == 1

    def test_status_specific_task_id(self, tmp_path: Path) -> None:
        """status(task_id=X) returns only the specified task."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        mgr = StateManager(tmp_path)
        mgr.create_task(_make_task(task_id="RW_20260224_080000"))
        mgr.create_task(_make_task(task_id="RW_20260224_090000"))

        loop = RalphLoop(vault_path=tmp_path)
        result = loop.status(task_id="RW_20260224_080000")

        assert len(result.loops) == 1
        assert result.loops[0].task_id == "RW_20260224_080000"

    def test_status_multiple_tasks_ordered_newest_first(self, tmp_path: Path) -> None:
        """status() with multiple tasks returns them ordered newest first."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        mgr = StateManager(tmp_path)
        mgr.create_task(_make_task(task_id="RW_20260224_080000"))
        mgr.create_task(_make_task(task_id="RW_20260224_090000"))

        loop = RalphLoop(vault_path=tmp_path)
        result = loop.status()

        assert len(result.loops) == 2
        assert result.loops[0].task_id == "RW_20260224_090000"

    def test_status_emergency_stop_reflected(self, tmp_path: Path) -> None:
        """emergency_stop_active=True shown in RalphStatusResult."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        (tmp_path / "STOP_RALPH").touch()

        loop = RalphLoop(vault_path=tmp_path)
        result = loop.status()

        assert result.emergency_stop_active is True

    def test_status_includes_correct_iteration_count(self, tmp_path: Path) -> None:
        """status() shows correct current_iteration and max_iterations."""
        from backend.ralph_wiggum.ralph_loop import RalphLoop

        mgr = StateManager(tmp_path)
        task = _make_task(task_id="RW_20260224_080000", current_iteration=4, max_iterations=10)
        mgr.create_task(task)

        loop = RalphLoop(vault_path=tmp_path)
        result = loop.status()

        summary = result.loops[0]
        assert summary.current_iteration == 4
        assert summary.max_iterations == 10


# ── T024: TestStopHook ────────────────────────────────────────────────────────


class TestStopHook:
    """Tests for backend/ralph_wiggum/stop_hook.py — onStop hook contract."""

    def _run_hook(self, vault_path: Path, stdin_payload: dict) -> dict:
        """Run stop_hook.main() with mocked stdin and return parsed stdout JSON."""
        import io
        from backend.ralph_wiggum import stop_hook

        stdin_json = json.dumps(stdin_payload)

        captured_output = []

        def mock_print(s, *args, **kwargs):
            captured_output.append(s)

        with (
            patch("sys.stdin", io.StringIO(stdin_json)),
            patch("builtins.print", side_effect=mock_print),
        ):
            stop_hook.main()

        # Return the last print output as parsed JSON
        assert captured_output, "stop_hook.main() produced no output"
        return json.loads(captured_output[-1])

    def test_no_active_task_approves(self, tmp_path: Path) -> None:
        """No in_progress tasks → approve."""
        # stop_hook resolves vault_path = claude_project_dir/vault
        # so we don't create any task files → empty vault
        result = self._run_hook(
            tmp_path,
            {"claude_project_dir": str(tmp_path)},
        )
        assert result["decision"] == "approve"

    def test_active_task_blocks_with_reason(self, tmp_path: Path) -> None:
        """in_progress task present → block with reason containing task_id."""
        # stop_hook resolves vault_path = claude_project_dir/vault
        vault_path = tmp_path / "vault"
        mgr = StateManager(vault_path)
        mgr.create_task(_make_task(task_id="RW_20260224_080000", current_iteration=1))

        result = self._run_hook(
            tmp_path,
            {"claude_project_dir": str(tmp_path)},
        )

        assert result["decision"] == "block"
        assert "RW_20260224_080000" in result["reason"]

    def test_emergency_stop_blocks_even_if_complete(self, tmp_path: Path) -> None:
        """Emergency stop → block regardless of task state."""
        vault_path = tmp_path / "vault"
        vault_path.mkdir(parents=True, exist_ok=True)
        (vault_path / "STOP_RALPH").touch()
        mgr = StateManager(vault_path)
        mgr.create_task(_make_task(status=LoopStatus.completed))

        result = self._run_hook(
            tmp_path,
            {"claude_project_dir": str(tmp_path)},
        )

        assert result["decision"] == "block"
        assert "Emergency stop" in result["reason"]

    def test_at_max_iterations_approves_and_marks_halted(self, tmp_path: Path) -> None:
        """Task at max_iterations → approve and mark task as halted."""
        vault_path = tmp_path / "vault"
        mgr = StateManager(vault_path)
        task = _make_task(task_id="RW_20260224_080000", current_iteration=5, max_iterations=5)
        mgr.create_task(task)

        result = self._run_hook(
            tmp_path,
            {"claude_project_dir": str(tmp_path)},
        )

        assert result["decision"] == "approve"

        # Verify task was marked halted
        loaded = mgr.load_task("RW_20260224_080000")
        assert loaded is not None
        assert loaded.status == LoopStatus.halted
        assert loaded.halt_reason == HaltReason.max_iterations_reached

    def test_block_increments_current_iteration(self, tmp_path: Path) -> None:
        """On block, current_iteration is incremented in state file."""
        vault_path = tmp_path / "vault"
        mgr = StateManager(vault_path)
        task = _make_task(task_id="RW_20260224_080000", current_iteration=1, max_iterations=10)
        mgr.create_task(task)

        self._run_hook(
            tmp_path,
            {"claude_project_dir": str(tmp_path)},
        )

        loaded = mgr.load_task("RW_20260224_080000")
        assert loaded is not None
        assert loaded.current_iteration == 2

    def test_always_outputs_valid_json_exit_0(self, tmp_path: Path) -> None:
        """stop_hook always outputs valid JSON (no exception raised)."""
        import io
        from backend.ralph_wiggum import stop_hook

        stdin_json = json.dumps({"claude_project_dir": str(tmp_path)})
        captured = []

        with (
            patch("sys.stdin", io.StringIO(stdin_json)),
            patch("builtins.print", side_effect=lambda s, *a, **kw: captured.append(s)),
        ):
            # Should not raise
            stop_hook.main()

        assert captured
        parsed = json.loads(captured[-1])
        assert "decision" in parsed
        assert parsed["decision"] in ("approve", "block")


# ── T025: TestOrchestratorIntegration ────────────────────────────────────────


class TestOrchestratorInteg:
    """Tests for Orchestrator._check_ralph_loops() integration."""

    def test_check_ralph_loops_returns_without_raising(self, tmp_path: Path) -> None:
        """_check_ralph_loops() doesn't raise when vault is empty."""
        from backend.orchestrator.orchestrator import Orchestrator, OrchestratorConfig

        cfg = OrchestratorConfig(vault_path=str(tmp_path), dev_mode=True, dry_run=True)
        orch = Orchestrator(cfg)

        # Ensure vault subdirs exist
        (tmp_path / "Needs_Action").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Done").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Logs" / "actions").mkdir(parents=True, exist_ok=True)

        asyncio.run(orch._check_ralph_loops())  # Should not raise

    def test_ralph_loop_task_file_triggers_loop_spawn(self, tmp_path: Path) -> None:
        """File with type: ralph_loop_task triggers RalphLoop.start()."""
        from backend.orchestrator.orchestrator import Orchestrator, OrchestratorConfig
        from backend.utils.frontmatter import format_with_frontmatter

        needs_action = tmp_path / "Needs_Action"
        needs_action.mkdir(parents=True, exist_ok=True)
        (tmp_path / "Done").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Logs" / "actions").mkdir(parents=True, exist_ok=True)

        # Create a ralph_loop_task file
        task_file = needs_action / "RALPH_test.md"
        content = format_with_frontmatter(
            {
                "type": "ralph_loop_task",
                "subject": "Test task",
                "prompt": "Do something simple",
                "completion_strategy": "promise",
                "completion_promise": "TASK_COMPLETE",
                "max_iterations": 3,
            },
            "",
        )
        task_file.write_text(content, encoding="utf-8")

        mock_result = RalphRunResult(
            status=LoopStatus.completed,
            task_id="RW_20260224_080000",
            iterations_run=3,
            final_status="completed",
        )

        cfg = OrchestratorConfig(vault_path=str(tmp_path), dev_mode=True, dry_run=True)
        orch = Orchestrator(cfg)

        with patch("backend.ralph_wiggum.ralph_loop.RalphLoop.start", return_value=mock_result) as mock_start:
            asyncio.run(orch._check_ralph_loops())
            mock_start.assert_called_once()

    def test_non_ralph_task_file_is_ignored(self, tmp_path: Path) -> None:
        """Files without type: ralph_loop_task are not processed."""
        from backend.orchestrator.orchestrator import Orchestrator, OrchestratorConfig
        from backend.utils.frontmatter import format_with_frontmatter

        needs_action = tmp_path / "Needs_Action"
        needs_action.mkdir(parents=True, exist_ok=True)
        (tmp_path / "Done").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Logs" / "actions").mkdir(parents=True, exist_ok=True)

        # Create a non-ralph task file
        task_file = needs_action / "EMAIL_task.md"
        task_file.write_text(
            format_with_frontmatter({"type": "email_task", "subject": "Email"}, ""), encoding="utf-8"
        )

        cfg = OrchestratorConfig(vault_path=str(tmp_path), dev_mode=True, dry_run=True)
        orch = Orchestrator(cfg)

        with patch("backend.ralph_wiggum.ralph_loop.RalphLoop.start") as mock_start:
            asyncio.run(orch._check_ralph_loops())
            mock_start.assert_not_called()

    def test_completed_loop_moves_task_to_done(self, tmp_path: Path) -> None:
        """Completed loop moves the task file to vault/Done/."""
        from backend.orchestrator.orchestrator import Orchestrator, OrchestratorConfig
        from backend.utils.frontmatter import format_with_frontmatter

        needs_action = tmp_path / "Needs_Action"
        needs_action.mkdir(parents=True, exist_ok=True)
        done_dir = tmp_path / "Done"
        done_dir.mkdir(parents=True, exist_ok=True)
        (tmp_path / "Logs" / "actions").mkdir(parents=True, exist_ok=True)

        task_file = needs_action / "RALPH_move_test.md"
        task_file.write_text(
            format_with_frontmatter(
                {
                    "type": "ralph_loop_task",
                    "subject": "Move test",
                    "prompt": "Do it",
                    "completion_promise": "TASK_COMPLETE",
                },
                "",
            ),
            encoding="utf-8",
        )

        mock_result = RalphRunResult(
            status=LoopStatus.completed,
            task_id="RW_20260224_080000",
            iterations_run=3,
            final_status="completed",
        )

        cfg = OrchestratorConfig(vault_path=str(tmp_path), dev_mode=True, dry_run=False)
        orch = Orchestrator(cfg)

        with patch("backend.ralph_wiggum.ralph_loop.RalphLoop.start", return_value=mock_result):
            asyncio.run(orch._check_ralph_loops())

        assert not task_file.exists()
        assert (done_dir / "RALPH_move_test.md").exists()

    def test_halted_loop_leaves_file_in_needs_action(self, tmp_path: Path) -> None:
        """Halted loop leaves the task file in Needs_Action with halt_reason in frontmatter."""
        from backend.orchestrator.orchestrator import Orchestrator, OrchestratorConfig
        from backend.utils.frontmatter import format_with_frontmatter, parse_frontmatter

        needs_action = tmp_path / "Needs_Action"
        needs_action.mkdir(parents=True, exist_ok=True)
        (tmp_path / "Done").mkdir(parents=True, exist_ok=True)
        (tmp_path / "Logs" / "actions").mkdir(parents=True, exist_ok=True)

        task_file = needs_action / "RALPH_halt_test.md"
        task_file.write_text(
            format_with_frontmatter(
                {
                    "type": "ralph_loop_task",
                    "subject": "Halt test",
                    "prompt": "Do it",
                    "completion_promise": "__NEVER__",
                    "max_iterations": 2,
                },
                "",
            ),
            encoding="utf-8",
        )

        mock_result = RalphRunResult(
            status=LoopStatus.halted,
            task_id="RW_20260224_080000",
            iterations_run=2,
            final_status="halted",
            halt_reason=HaltReason.max_iterations_reached,
        )

        cfg = OrchestratorConfig(vault_path=str(tmp_path), dev_mode=True, dry_run=False)
        orch = Orchestrator(cfg)

        with patch("backend.ralph_wiggum.ralph_loop.RalphLoop.start", return_value=mock_result):
            asyncio.run(orch._check_ralph_loops())

        assert task_file.exists()
        fm = parse_frontmatter(task_file)
        assert fm.get("ralph_halt_reason") == HaltReason.max_iterations_reached.value
