# Tasks: Ralph Wiggum Loop

**Feature**: 001-ralph-loop
**Input**: Design documents from `/specs/001-ralph-loop/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅, contracts/cli.md ✅

**Implementation Order** (from plan.md — MUST follow):
1. `skills/ralph-wiggum/SKILL.md` — skill documentation FIRST (Constitution Principle III)
2. `backend/ralph_wiggum/__init__.py` — all dataclasses/enums (foundation)
3. `backend/ralph_wiggum/state_manager.py` + `prompt_injector.py` — shared infrastructure
4. `backend/ralph_wiggum/ralph_loop.py` — loop controller + CLI
5. `backend/ralph_wiggum/stop_hook.py` — interactive hook mode
6. Tests, then orchestrator integration

**Tests**: Explicitly requested in spec ("Tests for loop logic, completion detection, timeout handling"). Write tests BEFORE each story's implementation.

**Organization**: Tasks grouped by user story to enable independent delivery and testing.

---

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no intra-task file conflicts)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths included in all task descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: SKILL.md first (mandatory per Constitution III), package skeleton, and env configuration.

- [x] T001 Create `skills/ralph-wiggum/SKILL.md` — include: trigger phrases ("ralph loop", "keep iterating", "don't stop", "loop until done"), layer=REASONING, sensitivity=LOW, inputs (prompt, completion strategy, max iterations), outputs (state file at vault/ralph_wiggum/TASK_ID.md, log entries), two execution modes (hook-based and subprocess), both completion strategies (promise marker and file-movement), CLI commands (--completion-promise, --completion-file, --max-iterations, --status, --vault-path, --dry-run), DEV_MODE behavior (3-iteration simulation, auto-outputs completion marker), safety limits (max iterations, timeouts, vault/STOP_RALPH), and example usage blocks for both strategies
- [x] T002 Create `backend/ralph_wiggum/__init__.py` — define all 8 enums/dataclasses: `CompletionStrategy(Enum)` (promise, file_movement), `LoopStatus(Enum)` (in_progress, completed, halted, error), `HaltReason(Enum)` (max_iterations_reached, per_iteration_timeout, total_timeout_exceeded, emergency_stop, subprocess_error), `RalphConfig` (@dataclass with fields: max_iterations=10, iteration_timeout=300.0, total_timeout=3600.0, vault_path, dev_mode, dry_run loaded from env vars RALPH_MAX_ITERATIONS/RALPH_ITERATION_TIMEOUT/RALPH_TOTAL_TIMEOUT/VAULT_PATH/DEV_MODE/DRY_RUN; __post_init__ validates max_iterations > 0, iteration_timeout > 0), `RalphTask` (@dataclass: task_id, prompt, completion_strategy, completion_promise, completion_file_pattern, max_iterations, iteration_timeout, total_timeout, status=LoopStatus.in_progress, current_iteration=0, started_at, last_iteration_at, completed_at, halt_reason, completed_artifact, session_id, dev_mode, iterations=field(default_factory=list)), `IterationRecord` (@dataclass: iteration_number, task_id, started_at, completed_at, duration_seconds, output_summary, completion_detected=False, halt_reason, exit_code, error_message), `RalphRunResult` (@dataclass: status, task_id, iterations_run, final_status, halt_reason, completed_artifact, state_file_path, reason), `RalphStatusResult` + `RalphTaskSummary`
- [x] T003 [P] Add to `config/.env`: `RALPH_MAX_ITERATIONS=10`, `RALPH_ITERATION_TIMEOUT=300`, `RALPH_TOTAL_TIMEOUT=3600` (under a `# Ralph Wiggum Loop` comment section)
- [x] T004 [P] Add documented entries to `config/.env.example`: `RALPH_MAX_ITERATIONS=10  # Maximum iterations per loop (default: 10)`, `RALPH_ITERATION_TIMEOUT=300  # Per-iteration timeout in seconds (default: 5 min)`, `RALPH_TOTAL_TIMEOUT=3600  # Total session timeout in seconds (default: 60 min)`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: `StateManager` and `PromptInjector` — shared by both hook-mode and subprocess-mode; MUST be complete before any loop logic is implemented.

**⚠️ CRITICAL**: US1 through US5 all depend on `state_manager.py`. US1-US5 loop execution depends on `prompt_injector.py`. Neither can be developed until T005-T006 are complete.

- [x] T005 Implement `StateManager` class in `backend/ralph_wiggum/state_manager.py` — `__init__(self, vault_path: Path, dry_run: bool = False)`; methods: `create_task(task: RalphTask) -> Path` (mkdir vault/ralph_wiggum if needed, write YAML frontmatter + sentinel-protected iteration table markdown, return file path; no-op if dry_run), `update_task(task: RalphTask) -> None` (overwrite existing state file frontmatter + iteration table body; sentinel: `<!-- ITERATIONS_SECTION_START -->` / `<!-- ITERATIONS_SECTION_END -->`; preserve Notes section; no-op if dry_run), `load_task(task_id: str) -> RalphTask | None` (glob vault/ralph_wiggum/*.md, parse frontmatter, return RalphTask or None), `load_all_tasks() -> list[RalphTask]` (load all .md files in vault/ralph_wiggum/, sort by started_at descending), `emergency_stop_active() -> bool` (check vault/STOP_RALPH exists), `log_iteration(record: IterationRecord) -> None` (call log_action from backend.utils.logging_utils with action_type="ralph_iteration_complete" or "ralph_iteration_halted"; no-op if dry_run); use `extract_frontmatter` from `backend.utils.frontmatter` and `log_action` from `backend.utils.logging_utils`; state file path: `vault/ralph_wiggum/{task.task_id}.md`
- [x] T006 [P] Implement `PromptInjector` class in `backend/ralph_wiggum/prompt_injector.py` — static method `build_continuation_prompt(original_prompt: str, iteration_records: list[IterationRecord], max_summary_chars: int = 500) -> str`: if no iteration_records return original_prompt unchanged; otherwise return `f"{original_prompt}\n\n## Previous Iterations (context)\n" + "\n".join(f"Iteration {r.iteration_number}: {r.output_summary[:max_summary_chars]}" for r in iteration_records) + "\n\nContinue from where you left off."` — always include the original prompt verbatim at the top; truncate each iteration summary to max_summary_chars

**Checkpoint**: State manager and prompt injector complete — all user story phases can now begin.

---

## Phase 3: User Story 1 — Promise-Based Task Loop (Priority: P1) 🎯 MVP

**Goal**: `python -m backend.ralph_wiggum "task prompt" --completion-promise "TASK_COMPLETE"` starts a loop, iterates until completion marker detected in output, persists state file at `vault/ralph_wiggum/RW_*.md`, exits with status=completed.

**Independent Test**: `DEV_MODE=true uv run python -m backend.ralph_wiggum "Process vault/Needs_Action files" --completion-promise "TASK_COMPLETE" --max-iterations 5` → state file created with `status: completed`, `current_iteration: 3`, log entry in vault/Logs/.

### Tests for User Story 1

- [x] T007 [P] [US1] Write `TestRalphConfig` (4 tests) in `tests/test_ralph_loop.py` — (1) env vars loaded correctly (RALPH_MAX_ITERATIONS=5); (2) invalid max_iterations=0 defaults to 10 with no exception; (3) invalid iteration_timeout=-1 defaults to 300; (4) RalphConfig constructed from defaults when env vars absent
- [x] T008 [P] [US1] Write `TestStateManager` (8 tests) in `tests/test_ralph_loop.py` — use tmp_path fixture; (1) create_task writes YAML frontmatter with correct task_id; (2) update_task overwrites frontmatter, preserves Notes section; (3) load_task returns RalphTask matching saved task; (4) load_task returns None for unknown ID; (5) load_all_tasks returns list sorted newest first; (6) emergency_stop_active True when STOP_RALPH exists; (7) emergency_stop_active False when absent; (8) dry_run=True means create_task is no-op (no file created)
- [x] T009 [P] [US1] Write `TestPromptInjector` (4 tests) in `tests/test_ralph_loop.py` — (1) empty iteration_records returns original_prompt unchanged; (2) one record — output includes original_prompt + iteration summary; (3) max_summary_chars=10 truncates long summaries; (4) multiple records — all included in order

### Implementation for User Story 1

- [x] T010 [US1] Implement `RalphLoop.__init__()` and `RalphLoop.start()` in `backend/ralph_wiggum/ralph_loop.py` — `__init__(self, vault_path=None, dev_mode=None, dry_run=None, config=None)`: load RalphConfig from env, override with any provided kwargs; `start(self, prompt, completion_strategy, completion_promise=None, completion_file_pattern=None, max_iterations=None) -> RalphRunResult`: validate args (CompletionStrategy.promise requires completion_promise, file_movement requires completion_file_pattern); generate `task_id = f"RW_{now_local:%Y%m%d_%H%M%S}"`; create RalphTask; call StateManager(vault_path, dry_run).create_task(task); call `asyncio.run(_LoopController(task, mgr, injector, config).run())`; return RalphRunResult with final status, task_id, iterations_run, halt_reason
- [x] T011 [US1] Implement `_LoopController` inner class with `run()` and `_call_claude()` in `backend/ralph_wiggum/ralph_loop.py` — `run(self) -> RalphTask`: set task.started_at = now_iso(); loop `while task.current_iteration < task.max_iterations`: increment current_iteration, create IterationRecord, call `await _run_iteration(record)`, update state via StateManager, check completion via `_check_completion(task, record.output_summary)` → if True set status=completed and break; after loop if no completion set status=halted, halt_reason=max_iterations_reached; set task.completed_at; final StateManager.update_task(task); return task; `_call_claude(prompt, session_id) -> tuple[str, str]`: `subprocess.run(["claude", "-p", prompt, "--output-format", "json"] + (["--resume", session_id] if session_id else []), capture_output=True, text=True, timeout=self.config.iteration_timeout)`; parse JSON response; return (response["result"], response.get("session_id", "")); on non-zero exit raise RuntimeError(f"claude exit {result.returncode}: {result.stderr[:200]}")
- [x] T012 [US1] Implement `_LoopController._simulate_iteration()` and `_check_completion()` in `backend/ralph_wiggum/ralph_loop.py` — `_simulate_iteration(record: IterationRecord, task: RalphTask) -> str`: `await asyncio.sleep(1)`; generate output `f"[DEV_MODE] Iteration {record.iteration_number}: processed 1 file in vault/Needs_Action/"`;  if `record.iteration_number >= 3 or record.iteration_number == task.max_iterations`: append `f" {task.completion_promise}"` to output (auto-completes); return output; `_check_completion(task: RalphTask, output: str) -> bool`: if strategy=promise return `task.completion_promise in output`; if strategy=file_movement return `len(glob.glob(task.completion_file_pattern)) > 0`; return False otherwise
- [x] T013 [US1] Implement `main()` CLI entry point in `backend/ralph_wiggum/ralph_loop.py` — `python_dotenv.load_dotenv("config/.env")`; `argparse.ArgumentParser`; positional `prompt` (nargs="?"); mutually exclusive group: `--status [TASK_ID]` vs `prompt + --completion-promise STR + --completion-file GLOB` (exactly one of promise/file required when prompt given); optional `--max-iterations N`, `--vault-path PATH`, `--dry-run`; when prompt: call `RalphLoop(...).start(...)`, print result summary (✅ or ⚠️); when --status: call `RalphLoop(...).status(task_id)`, print formatted status; `if __name__ == "__main__": main()`; module docstring enables `python -m backend.ralph_wiggum`

**Checkpoint**: US1 MVP complete — `DEV_MODE=true uv run python -m backend.ralph_wiggum "task" --completion-promise "TASK_COMPLETE" --max-iterations 5` creates `vault/ralph_wiggum/RW_*.md` with status=completed.

---

## Phase 4: User Story 2 — File-Movement Completion Detection (Priority: P2)

**Goal**: `--completion-file "vault/Done/task_*.md"` exits loop when matching file found in Done. State file records `completed_artifact` path. Both completion strategies fully functional via same CLI.

**Independent Test**: `DEV_MODE=true uv run python -m backend.ralph_wiggum "task" --completion-file "vault/Done/INVOICE_*.md"` → loops 3 iterations (DEV_MODE), state file shows `status: completed`, `completed_artifact` field set to matched file path.

### Tests for User Story 2

- [x] T014 [P] [US2] Write `TestFileMovement` (4 tests) in `tests/test_ralph_loop.py` — use tmp_path; (1) `_check_completion` returns False when no matching file; (2) returns True and sets `task.completed_artifact` when file matching glob exists; (3) multiple matching files — first match (sorted) used; (4) completion_file_pattern with wrong path → loop runs to max_iterations (no crash)

### Implementation for User Story 2

- [x] T015 [US2] Extend `_check_completion()` for file-movement strategy in `backend/ralph_wiggum/ralph_loop.py` — for `CompletionStrategy.file_movement`: call `matches = sorted(glob.glob(task.completion_file_pattern))`; if matches: set `task.completed_artifact = matches[0]`; return True; return False; log WARNING at loop start if `not glob.glob(task.completion_file_pattern) and task.completion_strategy == CompletionStrategy.file_movement` (pattern matches nothing — possible misconfiguration)
- [x] T016 [US2] Wire `--completion-file GLOB` flag in `main()` in `backend/ralph_wiggum/ralph_loop.py` — add `--completion-file GLOB` to argparse; validate mutual exclusion with `--completion-promise`; pass `completion_strategy=CompletionStrategy.file_movement, completion_file_pattern=args.completion_file` to `RalphLoop.start()`; print completion artifact path in success output: `Artifact: {result.completed_artifact}`

**Checkpoint**: US2 complete — both `--completion-promise` and `--completion-file` strategies functional.

---

## Phase 5: User Story 3 — Safety Limits and Emergency Stop (Priority: P3)

**Goal**: Loop halts after max_iterations with `halt_reason: max_iterations_reached`. Per-iteration timeout enforced via `asyncio.wait_for`. Total timeout checked at loop entry. `vault/STOP_RALPH` sentinel halts all loops within 1 iteration cycle.

**Independent Test**: `DEV_MODE=true uv run python -m backend.ralph_wiggum "task" --completion-promise "__NEVER__" --max-iterations 3` → exits with ⚠️ halted, reason=max_iterations_reached, exit code 1; `touch vault/STOP_RALPH` during run → exits with reason=emergency_stop.

### Tests for User Story 3

- [x] T017 [P] [US3] Write `TestSafetyLimits` (8 tests) in `tests/test_ralph_loop.py` — use tmp_path; (1) loop halts at max_iterations=3, state shows halt_reason=max_iterations_reached; (2) per-iteration timeout: mock `_call_claude` to sleep > timeout → HaltReason.per_iteration_timeout; (3) total timeout exceeded: mock started_at to 3600s ago → halts at next iteration entry; (4) emergency_stop: create vault/STOP_RALPH → loop halts within 1 cycle with halt_reason=emergency_stop; (5) DEV_MODE max_iterations test — loop completes in 3 iterations regardless; (6) DRY_RUN: loop runs but no state files created; (7) halt reason recorded in state file; (8) CLI exits with code 1 on halt, code 0 on completion

### Implementation for User Story 3

- [x] T018 [US3] Add `asyncio.wait_for` per-iteration timeout in `_LoopController._run_iteration()` in `backend/ralph_wiggum/ralph_loop.py` — wrap `_call_claude()` or `_simulate_iteration()` coroutine with `asyncio.wait_for(coro, timeout=self.config.iteration_timeout)`; catch `asyncio.TimeoutError` → set `record.halt_reason = HaltReason.per_iteration_timeout`, `record.error_message = f"Timeout after {self.config.iteration_timeout}s"`, `task.status = LoopStatus.halted`, `task.halt_reason = HaltReason.per_iteration_timeout`; StateManager.update_task(task); return False; all exceptions caught with graceful halt (never raises from _run_iteration)
- [x] T019 [US3] Add total timeout and elapsed-time check in `_LoopController.run()` in `backend/ralph_wiggum/ralph_loop.py` — at start of each loop iteration check: `elapsed = (datetime.now(UTC) - parse_iso(task.started_at)).total_seconds()`; if `elapsed >= task.total_timeout`: set halt with HaltReason.total_timeout_exceeded, StateManager.update_task, break; compute `remaining = task.total_timeout - elapsed` and pass to `asyncio.wait_for(coro, timeout=min(task.iteration_timeout, remaining))` in _run_iteration
- [x] T020 [US3] Add background sentinel monitor in `_LoopController.run()` in `backend/ralph_wiggum/ralph_loop.py` — before loop: `halt_event = asyncio.Event()`; create `monitor_task = asyncio.create_task(_sentinel_monitor(self.config.vault_path, halt_event), name="ralph-sentinel")`; in loop body: check `if halt_event.is_set()`: set halt with HaltReason.emergency_stop, break; in finally block: `monitor_task.cancel(); with contextlib.suppress(asyncio.CancelledError): await asyncio.wait_for(monitor_task, timeout=1.0)`; implement `async def _sentinel_monitor(vault_path, halt_event)`: while True: if (vault_path/"STOP_RALPH").exists(): halt_event.set(); return; await asyncio.sleep(1)

**Checkpoint**: US3 complete — all safety limits enforced. `--max-iterations 3 --completion-promise "__NEVER__"` halts correctly with exit code 1.

---

## Phase 6: User Story 4 — Status Monitoring (Priority: P4)

**Goal**: `python -m backend.ralph_wiggum --status` shows all loops (active, completed, halted) with task ID, iteration count, elapsed time, strategy. `--status TASK_ID` shows single loop detail.

**Independent Test**: After running Scenario 1 from quickstart.md, `uv run python -m backend.ralph_wiggum --status` shows at least one completed loop entry; empty vault shows "No Ralph loops found.".

### Tests for User Story 4

- [x] T021 [P] [US4] Write `TestStatus` (6 tests) in `tests/test_ralph_loop.py` — use tmp_path; (1) `status()` with no state files returns RalphStatusResult with loops=[]; (2) status() with 1 completed task returns correct summary; (3) status(task_id="RW_XXX") returns single task summary; (4) status() with multiple tasks — ordered newest first; (5) emergency_stop_active=True reflected in RalphStatusResult; (6) status output includes correct iteration count, strategy, elapsed_seconds

### Implementation for User Story 4

- [x] T022 [US4] Implement `RalphLoop.status(task_id=None) -> RalphStatusResult` in `backend/ralph_wiggum/ralph_loop.py` — `StateManager(vault_path).load_all_tasks()` → build `RalphTaskSummary` list (most recent first); filter to single task if task_id provided; count active_count, completed_count, halted_count; check `StateManager.emergency_stop_active()`; return `RalphStatusResult(loops=summaries, active_count=..., completed_count=..., halted_count=..., emergency_stop_active=...)`; compute `elapsed_seconds = (now_utc - parse_iso(task.started_at)).total_seconds()` for in_progress tasks; use `task.total_elapsed_seconds` for terminal tasks
- [x] T023 [US4] Wire `--status [TASK_ID]` flag to `RalphLoop.status()` in `main()` in `backend/ralph_wiggum/ralph_loop.py` — when `--status` provided: call `status(task_id=args.status if args.status != True else None)`; format output block: header "Ralph Loop Status", "Emergency Stop: ACTIVE/INACTIVE", sections for Active/Completed/Halted loops; per loop: `{task_id} — {status} (iter {current}/{max}, {elapsed:.0f}s, strategy: {strategy})`; if loops empty: print "No Ralph loops found."; exit code 0 always for --status

**Checkpoint**: US4 complete — all 4 CLI flags (--completion-promise, --completion-file, --max-iterations, --status) functional.

---

## Phase 7: User Story 5 — Stop Hook and Orchestrator Integration (Priority: P5)

**Goal**: (a) `onStop` hook in `.claude/settings.json` intercepts interactive Claude Code exit when `vault/ralph_wiggum/` has an in_progress task — blocks exit with continuation reason. (b) Orchestrator auto-spawns Ralph loop for `vault/Needs_Action/` files with `type: ralph_loop_task` frontmatter.

**Independent Test**: Create `vault/ralph_wiggum/RW_test.md` with `status: in_progress`; run `python backend/ralph_wiggum/stop_hook.py` with mocked stdin → output contains `{"decision": "block", ...}`; create a `ralph_loop_task` file in Needs_Action and start orchestrator → loop spawned and log entry created.

### Tests for User Story 5

- [x] T024 [P] [US5] Write `TestStopHook` (6 tests) in `tests/test_ralph_loop.py` — use tmp_path; mock stdin; (1) no active task → stdout `{"decision": "approve"}`; (2) in_progress task present → stdout `{"decision": "block", "reason": "..."}` containing task_id and iteration count; (3) emergency stop active → stdout `{"decision": "block", "reason": "Emergency stop..."}` even if task complete; (4) task at max_iterations → stdout approve + task status set to halted; (5) stop_hook increments current_iteration in state file on block; (6) stop_hook outputs valid JSON with exit 0 in all cases
- [x] T025 [P] [US5] Write `TestOrchestratorIntegration` (5 tests) in `tests/test_ralph_loop.py` — (1) `_check_ralph_loops()` returns None and does not raise; (2) file with `type: ralph_loop_task` triggers loop spawn (mock RalphLoop.start); (3) file without `type: ralph_loop_task` is ignored; (4) completed loop moves task file to Done; (5) halted loop leaves task file in Needs_Action with updated frontmatter

### Implementation for User Story 5

- [x] T026 [US5] Implement `backend/ralph_wiggum/stop_hook.py` — `main()`: read stdin via `json.loads(sys.stdin.read())`; extract `claude_project_dir = Path(payload.get("claude_project_dir", "."))` and `vault_path = claude_project_dir / "vault"`; instantiate `StateManager(vault_path)`; check `mgr.emergency_stop_active()` → if True: print `json.dumps({"decision": "block", "reason": "Emergency stop active (vault/STOP_RALPH exists). Remove file to resume."})` + exit 0; `tasks = [t for t in mgr.load_all_tasks() if t.status == LoopStatus.in_progress]`; if no tasks: print `json.dumps({"decision": "approve"})` + exit 0; `task = tasks[-1]` (most recent); if `task.current_iteration >= task.max_iterations`: set task.status=halted, task.halt_reason=max_iterations_reached, mgr.update_task(task); print approve + exit 0; else: `task.current_iteration += 1; task.last_iteration_at = now_iso(); mgr.update_task(task)`; build continuation_prompt via PromptInjector; print `json.dumps({"decision": "block", "reason": f"Task {task.task_id} incomplete. Iteration {task.current_iteration}/{task.max_iterations}. {continuation_prompt[:500]}"})` + exit 0; if __name__ == "__main__": main()
- [x] T027 [US5] Add `onStop` hook entry to `.claude/settings.json` — if file does not exist, create it with `{"hooks": {"onStop": [{"handler": {"type": "command", "script": "uv run python backend/ralph_wiggum/stop_hook.py"}}]}}`; if file already exists, read and merge the `onStop` entry under `hooks` key, preserving all existing keys
- [x] T028 [US5] Add `_check_ralph_loops()` async method to `Orchestrator` class in `backend/orchestrator/orchestrator.py` — lazy import `from backend.ralph_wiggum.ralph_loop import RalphLoop` inside method; scan `vault/Needs_Action/*.md` for files with frontmatter `type: ralph_loop_task`; for each file: read `prompt`, `completion_strategy` (default "promise"), `completion_promise` (default "TASK_COMPLETE"), `max_iterations` (default from env); instantiate `RalphLoop(vault_path=self.vault_path, dev_mode=self.config.dev_mode, dry_run=self.config.dry_run)`; call `result = await asyncio.to_thread(loop.start, prompt, strategy, ...)`; if `result.status == "completed"`: move task file to `vault/Done/`, log INFO with task_id + iterations; elif `result.status == "halted"`: log WARNING with halt_reason, leave file in Needs_Action with added frontmatter `ralph_halt_reason: {result.halt_reason}`; wrap entire method in `try/except Exception as exc: logger.warning("Ralph loop check failed: %s", exc)` — never raises
- [x] T029 [US5] Add `await self._check_ralph_loops()` call in `Orchestrator.run()` in `backend/orchestrator/orchestrator.py` — place after `await self._check_briefing_schedule()` (the last existing _check_* call); no other changes to run()

**Checkpoint**: US5 complete — all 5 user stories fully implemented. Full feature delivered.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Test suite validation, quickstart scenario verification, and final quality checks.

- [x] T030 [P] Run full test suite `uv run pytest tests/test_ralph_loop.py -v` — confirm all tests pass (target: 0 failures); fix any test/implementation mismatches discovered
- [x] T031 [P] Validate quickstart.md Scenario 1 (promise loop): `DEV_MODE=true uv run python -m backend.ralph_wiggum "Process files" --completion-promise "TASK_COMPLETE" --max-iterations 5` → state file exists with `status: completed`, log entry present
- [x] T032 [P] Validate quickstart.md Scenario 3 (max iterations halt): `DEV_MODE=true ... --completion-promise "__NEVER__" --max-iterations 3` → exit code 1, state file shows `halt_reason: max_iterations_reached`
- [x] T033 [P] Validate quickstart.md Scenario 4 (status command): run `uv run python -m backend.ralph_wiggum --status` after Scenarios 1 and 3 — output shows ≥2 loops with correct statuses and iteration counts

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on T002 (__init__.py dataclasses must exist before state_manager imports them)
- **US1 (Phase 3)**: Depends on Phase 2 complete; T007-T009 [P] (test classes, different files conceptually — same test file but independent test classes); T010 depends on T006 (needs PromptInjector); T011-T013 sequential (same file)
- **US2 (Phase 4)**: Depends on US1 complete (file_movement extends _check_completion in ralph_loop.py)
- **US3 (Phase 5)**: Depends on US1 complete (safety features wrap existing loop in ralph_loop.py); T018-T020 sequential (same file, same method)
- **US4 (Phase 6)**: Depends on T005 (state_manager.load_all_tasks); T022-T023 sequential (same file)
- **US5 (Phase 7)**: Depends on US1 complete (stop_hook reads state created by loop); T026-T029 sequential within phase; T024-T025 [P] (different test classes)
- **Polish (Phase 8)**: Depends on US1-US5 complete (specifically T030 requires all test classes written)

### Within Phase 3 (US1) — Sequential Within ralph_loop.py

```
tests/: T007 || T008 || T009   [parallel — all independent test classes]
                ↓
ralph_loop.py: T010 → T011 → T012 → T013   [sequential — same file, each builds on previous]
```

### Parallel Opportunities

| Tasks | Parallel? | Reason |
|-------|-----------|--------|
| T003, T004 | ✅ Yes | Different config files |
| T005, T006 | ✅ Yes | Different files (state_manager.py vs prompt_injector.py) |
| T007, T008, T009 | ✅ Yes | Independent test classes (can be written simultaneously, merged) |
| T014, T021, T024, T025 | ✅ Yes | Different test classes in test file |
| T030, T031, T032, T033 | ✅ Yes | Independent validation scenarios |

---

## Parallel Execution Examples

### Phase 3 (US1) Parallel Test Writing

```bash
# Agent A — TestRalphConfig (4 tests)
T007: TestRalphConfig in tests/test_ralph_loop.py

# Agent B — TestStateManager (8 tests)
T008: TestStateManager in tests/test_ralph_loop.py

# Agent C — TestPromptInjector (4 tests)
T009: TestPromptInjector in tests/test_ralph_loop.py

# After all three: sequential implementation
T010 → T011 → T012 → T013
```

### Phase 2 Parallel Foundation

```bash
# Agent A
T005: state_manager.py

# Agent B
T006: prompt_injector.py
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Phase 1: Setup (T001–T004)
2. Phase 2: Foundational — state_manager + prompt_injector (T005–T006)
3. Phase 3: US1 tests (T007–T009) then implementation (T010–T013)
4. **STOP and VALIDATE**: `DEV_MODE=true uv run python -m backend.ralph_wiggum "task" --completion-promise "TASK_COMPLETE" --max-iterations 5`
5. Confirm `vault/ralph_wiggum/RW_*.md` created with `status: completed`, iteration count = 3

### Full Delivery Order

| Phase | Delivers | Validate With |
|-------|----------|---------------|
| 1 + 2 | SKILL.md, dataclasses, state manager, prompt injector | `python -c "from backend.ralph_wiggum import RalphConfig"` |
| 3 (US1) | Promise loop + CLI | `DEV_MODE=true --generate-now` style → vault/ralph_wiggum/ state file |
| 4 (US2) | File-movement completion | `--completion-file "vault/Done/*.md"` → exits on first match |
| 5 (US3) | Safety limits | `--max-iterations 3 --completion-promise "__NEVER__"` → halted in 3 |
| 6 (US4) | Status command | `--status` → shows all loops |
| 7 (US5) | Stop hook + orchestrator | Stop hook blocks interactive exit; orchestrator auto-spawns |
| 8 | Tests + quickstart | `pytest tests/test_ralph_loop.py -v` all pass |

---

## Task Summary

| Phase | Task IDs | Count | US |
|-------|----------|-------|----|
| Setup | T001–T004 | 4 | — |
| Foundational | T005–T006 | 2 | — |
| US1 — Promise Loop | T007–T013 | 7 | P1 |
| US2 — File-Movement | T014–T016 | 3 | P2 |
| US3 — Safety Limits | T017–T020 | 4 | P3 |
| US4 — Status | T021–T023 | 3 | P4 |
| US5 — Stop Hook + Orchestrator | T024–T029 | 6 | P5 |
| Polish | T030–T033 | 4 | — |
| **TOTAL** | **T001–T033** | **33** | |

**~37 test cases** distributed across 6 test classes (T007–T009, T014, T017, T021, T024–T025).

---

## Notes

- **SKILL.md must be T001** — Constitution Principle III: all AI capability documented as skill first
- **Test file path**: all tests in single `tests/test_ralph_loop.py` (same pattern as test_ceo_briefing.py)
- **asyncio.to_thread()** wraps sync subprocess calls in async orchestrator context (matches orchestrator.py pattern)
- **DEV_MODE simulation**: iteration 3 (or final iteration if max < 3) auto-outputs completion marker — ensures DEV_MODE always terminates cleanly
- **settings.json merge**: T027 MUST preserve existing keys — read first, then merge, never overwrite
- **stop_hook.py is sync** (not async) — Claude Code hooks are plain subprocess scripts, not async
- **No new dependencies**: all packages already in pyproject.toml (subprocess stdlib, asyncio stdlib, glob stdlib, yaml already present)
- **Commit points**: T001 (SKILL.md), T006 (foundational), T013 (US1 CLI complete), T016 (US2), T020 (US3), T023 (US4), T029 (US5), T033 (all validated)
