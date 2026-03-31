# Research: Ralph Wiggum Loop

**Feature**: 001-ralph-loop
**Date**: 2026-02-24
**Status**: Complete — all decisions resolved

---

## Decision 1: Claude Code Stop Hook Mechanism

**Decision**: Use `onStop` hook in `.claude/settings.json`, returning JSON `{"decision": "block", "reason": "..."}` with exit 0 to intercept Claude Code's exit.

**Rationale**: The `onStop` event fires every time Claude Code tries to end a session. The hook receives a JSON payload on stdin (session_id, cwd, claude_project_dir) and can either allow exit (exit 0, no JSON or `{"decision": "approve"}`) or block it (exit 0 + `{"decision": "block", "reason": "Task not complete. ...progress..."}`). The `reason` text becomes Claude's feedback and guides its next action. Using exit 2 also works but does not allow structured reason text — exit 0 + JSON is preferred.

**Hook config format** (`.claude/settings.json`):
```json
{
  "hooks": {
    "onStop": [
      {
        "handler": {
          "type": "command",
          "script": "python backend/ralph_wiggum/stop_hook.py"
        }
      }
    ]
  }
}
```

**Hook stdin payload**:
```json
{"session_id": "...", "hook_event_name": "onStop", "cwd": "...", "claude_project_dir": "..."}
```

**Alternatives considered**:
- Exit code 2 only (simpler but no structured reason text)
- `UserPromptSubmit` hook (runs before prompt, not at exit — different use case)

---

## Decision 2: Programmatic Loop Controller (Subprocess Mode)

**Decision**: `ralph_loop.py` invokes `claude -p "prompt" --output-format json` as a subprocess and manages iteration state in Python. Uses `--resume SESSION_ID` for context continuity.

**Rationale**: The `-p` / `--print` flag enables non-interactive Claude Code invocation. `--output-format json` provides structured output including `session_id` and `result` fields. `--resume SESSION_ID` allows subsequent iterations to inherit conversation context, so Claude sees its own previous work without explicit re-injection. This mode is required for orchestrator-spawned loops where no interactive session exists.

**Command format**:
```bash
# First iteration
claude -p "PROMPT" --output-format json
# → {"result": "...", "session_id": "abc123", ...}

# Subsequent iterations (with context continuity)
claude -p "PROMPT\n\nPrevious iterations:\n..." --resume abc123 --output-format json
```

**Security note**: Trust verification is disabled in `-p` mode. Only run on trusted repositories.

**Additional useful flags**:
- `--max-turns N` — limit agentic turns per iteration
- `--allowedTools "Bash,Read,Edit"` — auto-approve tool types
- `--max-budget-usd X.XX` — cost safety per iteration

**Alternatives considered**:
- Hook-only approach (no programmatic spawning from orchestrator — insufficient)
- MCP server wrapper (adds unnecessary complexity for process management)

---

## Decision 3: Two-Mode Architecture

**Decision**: Implement both hook-based (interactive) and subprocess-based (programmatic) execution modes in the same codebase. Both modes share `state_manager.py` and `prompt_injector.py`.

**Rationale**: The spec requires the orchestrator to spawn loops programmatically AND the stop hook intercepts interactive Claude sessions. These are complementary, not competing:
- **Hook mode**: User/orchestrator opens Claude Code interactively, stop hook manages continuation
- **Subprocess mode**: `ralph_loop.py` calls `claude -p` in a controlled loop, orchestrator calls `RalphLoop.start()`

**Shared components**: `state_manager.py` (reads/writes vault state files) and `prompt_injector.py` (builds injected prompts) are used by both modes.

**Alternatives considered**:
- Hook-only (no programmatic spawning — insufficient for orchestrator use case)
- Subprocess-only (stop hook not implemented — incomplete per spec)

---

## Decision 4: State Machine Design

**Decision**: Enum-based state machine with 4 states: `in_progress`, `completed`, `halted`, `error`. State tracked in `RalphTask` dataclass, persisted to YAML frontmatter markdown in `vault/ralph_wiggum/`.

**Rationale**: Mirrors `WatcherStatus` pattern from `backend/orchestrator/watchdog.py`. Enum values are strings for YAML serialization. State transitions are explicit in code:
- `in_progress → completed`: completion signal detected (promise or file)
- `in_progress → halted`: safety limit reached (max_iterations, timeout, STOP_RALPH)
- `in_progress → error`: unexpected exception

**Halt reasons** (enum):
- `max_iterations_reached`
- `per_iteration_timeout`
- `total_timeout_exceeded`
- `emergency_stop` (STOP_RALPH sentinel)
- `subprocess_error`

**Alternatives considered**:
- Boolean `is_complete` field (insufficient — does not distinguish halted from completed)
- Full state machine library (over-engineered for 4 states)

---

## Decision 5: Timeout Enforcement Strategy

**Decision**: Use `asyncio.wait_for` for per-iteration timeout. Background `asyncio.Task` monitors `vault/STOP_RALPH` sentinel every 1 second. Total timeout checked at loop entry via elapsed time.

**Rationale**: Matches `orchestrator.py` pattern (lines 190-197). `asyncio.wait_for` cancels the subprocess coroutine cleanly without leaving zombie processes. The sentinel background task uses `asyncio.CancelledError` for clean shutdown. Total timeout is checked at start of each iteration (not continuously) to avoid added complexity.

**Patterns from codebase**:
- `contextlib.suppress(asyncio.CancelledError)` for background task cleanup
- `asyncio.to_thread(generator.run_if_due)` for sync subprocess calls

**Alternatives considered**:
- `threading.Timer` (incompatible with async codebase)
- `signal.alarm` (Windows-incompatible)
- Polling total timeout inside subprocess (too fine-grained)

---

## Decision 6: State File Location and Format

**Decision**: State files stored in `vault/ralph_wiggum/<TASK_ID>.md` with YAML frontmatter. Task ID format: `RW_YYYYMMDD_HHMMSS` (timestamp-based, unique per second).

**Rationale**: Matches vault file conventions. YAML frontmatter allows human inspection in Obsidian. File body uses markdown table for iteration history (matches briefing generator pattern). `vault/ralph_wiggum/` added to vault folder structure as a new subdirectory.

**State file frontmatter fields**:
```yaml
type: ralph_wiggum_task
task_id: RW_20260224_080000
status: in_progress          # in_progress | completed | halted | error
completion_strategy: promise  # promise | file_movement
completion_promise: TASK_COMPLETE
completion_file_pattern: ""
max_iterations: 10
current_iteration: 3
started_at: "2026-02-24T08:00:00Z"
last_iteration_at: "2026-02-24T08:05:00Z"
halt_reason: null
dev_mode: true
```

**Alternatives considered**:
- JSON files (not human-readable in Obsidian)
- SQLite database (violates local-first vault design)
- In-memory only (no persistence across restarts)

---

## Decision 7: Completion Signal Detection

**Decision (Promise)**: Scan the full `result` text from each iteration for the configured marker string. Detection is case-sensitive. Marker may appear anywhere in output.

**Decision (File-movement)**: Use `glob.glob(pattern)` after each iteration to check `vault/Done/`. First match triggers exit. Pattern is provided at loop start and not re-evaluated.

**Edge case handling**:
- Promise in quoted text: Spec assumption is that the AI is reliable; if false positives are a concern, the operator should choose a distinctive marker (e.g., `__RALPH_TASK_COMPLETE__`)
- Zero files matching glob: Log warning at loop start; loop continues until safety limit
- Multiple files matching glob: First match (sorted) triggers exit

**Alternatives considered**:
- Exact-end-of-output matching for promise (too rigid, AI sometimes appends newlines)
- Watch `vault/Done/` with filesystem events (inotify/watchdog — adds OS dependency)

---

## Decision 8: Prompt Injection for Continuation

**Decision**: `prompt_injector.py` builds the continuation prompt as: `{original_prompt}\n\n## Previous Iterations\n{summary}`. Summary includes iteration number + first 500 chars of previous output per iteration. Uses `--resume SESSION_ID` in subprocess mode for native Claude context continuity.

**Rationale**: `--resume SESSION_ID` is the most reliable way to preserve context in subprocess mode — Claude natively sees its own previous conversation. The prompt injection adds a structured summary as explicit context in case session resume is not available (e.g., first iteration or DEV_MODE simulation).

**Alternatives considered**:
- Full previous output (too large for long runs — token limit risk)
- Summary only without --resume (loses tool call history)

---

## Decision 9: DEV_MODE Simulation

**Decision**: In `DEV_MODE=true`, `ralph_loop.py` simulates iteration execution by sleeping 1 second and generating a fake output string. Iteration 3 (or the final iteration) automatically outputs the completion marker to demonstrate successful loop termination.

**Rationale**: Matches existing DEV_MODE pattern from `briefing_generator.py` and `data_collectors.py` — real execution paths avoided, but state machine still runs correctly.

**Alternatives considered**:
- Skip loop entirely in DEV_MODE (insufficient — loop state machine behavior not testable)
- Mock subprocess calls only (more complex, same outcome)

---

## Decision 10: Orchestrator Integration Pattern

**Decision**: `Orchestrator._check_ralph_loops()` scans `vault/Needs_Action/` for files with frontmatter `type: ralph_loop_task`. For matching files: lazy-import `RalphLoop`, call `await asyncio.to_thread(loop.start)`, move file to `vault/Done/` on completion or log halt reason and leave in `vault/Needs_Action/`.

**Rationale**: Mirrors `_check_briefing_schedule()` and `_check_content_schedule()` patterns exactly. Lazy import prevents circular dependencies. `asyncio.to_thread` wraps the synchronous subprocess loop.

**Tag for auto-spawn**: Frontmatter field `type: ralph_loop_task` + `prompt:` field + optional `completion_strategy:`, `max_iterations:`.

**Alternatives considered**:
- Orchestrator configuration file listing loop tasks (static; vault-driven is more flexible)
- CLI-only (no orchestrator integration — incomplete per spec US5)
