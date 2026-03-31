# Data Model: Ralph Wiggum Loop

**Feature**: 001-ralph-loop
**Date**: 2026-02-24
**Source**: specs/001-ralph-loop/spec.md + research.md

---

## Entities

### 1. `RalphConfig` (Configuration)

Loaded at startup from environment variables and defaults. Immutable during a loop session.

| Field | Type | Default | Source | Description |
|-------|------|---------|--------|-------------|
| `max_iterations` | `int` | `10` | `RALPH_MAX_ITERATIONS` env | Maximum iterations before forced halt |
| `iteration_timeout` | `float` | `300.0` | `RALPH_ITERATION_TIMEOUT` env | Per-iteration timeout in seconds (5 min) |
| `total_timeout` | `float` | `3600.0` | `RALPH_TOTAL_TIMEOUT` env | Total session timeout in seconds (60 min) |
| `vault_path` | `Path` | `./vault` | `VAULT_PATH` env | Path to vault root |
| `dev_mode` | `bool` | `True` | `DEV_MODE` env | Simulate execution, no real subprocess calls |
| `dry_run` | `bool` | `False` | `--dry-run` flag | No file writes; console output only |

**Validation**:
- `max_iterations > 0` (default 10 if ≤ 0, log WARNING)
- `iteration_timeout > 0` (default 300 if ≤ 0)
- `total_timeout > iteration_timeout` (log WARNING if not)

---

### 2. `CompletionStrategy` (Enum)

```
promise        — detect marker string in AI output
file_movement  — detect file matching glob pattern in vault/Done/
```

---

### 3. `LoopStatus` (Enum)

Lifecycle state of a `RalphTask`.

```
in_progress   — loop is actively running or between iterations
completed     — completion signal detected; loop exited cleanly
halted        — safety limit triggered; loop forced to stop
error         — unexpected exception; loop could not continue
```

**Valid transitions**:
```
in_progress → completed   (completion signal detected)
in_progress → halted      (safety limit: max_iterations, timeout, emergency_stop)
in_progress → error       (unhandled exception)
```

---

### 4. `HaltReason` (Enum)

Reason recorded in `RalphTask` when `status = halted`.

```
max_iterations_reached  — current_iteration == max_iterations, no completion
per_iteration_timeout   — single iteration exceeded iteration_timeout
total_timeout_exceeded  — total elapsed time exceeded total_timeout
emergency_stop          — vault/STOP_RALPH sentinel file detected
subprocess_error        — claude -p subprocess returned non-zero exit code
```

---

### 5. `RalphTask` (Core Entity)

Represents one complete loop session. Persisted to `vault/ralph_wiggum/<TASK_ID>.md` after every iteration.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task_id` | `str` | Yes | Unique ID: `RW_YYYYMMDD_HHMMSS` |
| `prompt` | `str` | Yes | Original task prompt (full text) |
| `completion_strategy` | `CompletionStrategy` | Yes | `promise` or `file_movement` |
| `completion_promise` | `str \| None` | Conditional | Marker string; required if strategy=promise |
| `completion_file_pattern` | `str \| None` | Conditional | Glob pattern; required if strategy=file_movement |
| `max_iterations` | `int` | Yes | From `RalphConfig.max_iterations` |
| `iteration_timeout` | `float` | Yes | From `RalphConfig.iteration_timeout` |
| `total_timeout` | `float` | Yes | From `RalphConfig.total_timeout` |
| `status` | `LoopStatus` | Yes | Current lifecycle state |
| `current_iteration` | `int` | Yes | Count of iterations started (0 = not started) |
| `started_at` | `str \| None` | Yes | ISO 8601 UTC; set on loop start |
| `last_iteration_at` | `str \| None` | Yes | ISO 8601 UTC; updated after each iteration |
| `completed_at` | `str \| None` | No | ISO 8601 UTC; set on terminal state |
| `halt_reason` | `HaltReason \| None` | No | Set when status=halted |
| `completed_artifact` | `str \| None` | No | File path that triggered file-movement completion |
| `session_id` | `str \| None` | No | Claude Code session ID for `--resume` continuity |
| `dev_mode` | `bool` | Yes | From `RalphConfig.dev_mode` |
| `iterations` | `list[IterationRecord]` | Yes | Per-iteration records (append-only) |

**Derived properties**:
- `total_elapsed_seconds`: `(completed_at - started_at).total_seconds()`
- `is_terminal`: `status in (completed, halted, error)`

---

### 6. `IterationRecord` (Per-Iteration Log)

One record created per iteration. Append-only (never modified after creation).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `iteration_number` | `int` | Yes | 1-based iteration index |
| `task_id` | `str` | Yes | Parent task ID for correlation |
| `started_at` | `str` | Yes | ISO 8601 UTC |
| `completed_at` | `str \| None` | No | ISO 8601 UTC; set on iteration end |
| `duration_seconds` | `float \| None` | No | Wall clock time for this iteration |
| `output_summary` | `str` | Yes | First 500 chars of Claude output (empty in DEV_MODE sim) |
| `completion_detected` | `bool` | Yes | True if completion signal was found in this iteration |
| `halt_reason` | `HaltReason \| None` | No | Set if this iteration triggered a halt |
| `exit_code` | `int \| None` | No | Claude subprocess exit code (None in hook mode / DEV_MODE) |
| `error_message` | `str \| None` | No | Exception message if iteration failed |

---

### 7. `RalphRunResult` (Operation Result)

Returned by `RalphLoop.start()` and `RalphLoop.run_if_spawned()`.

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | `"completed"`, `"halted"`, `"error"`, `"skipped"` |
| `task_id` | `str \| None` | Task ID if loop was created |
| `iterations_run` | `int` | Total iterations executed |
| `final_status` | `LoopStatus \| None` | Terminal loop state |
| `halt_reason` | `HaltReason \| None` | Why loop halted (if applicable) |
| `completed_artifact` | `str \| None` | File that triggered file-movement completion |
| `state_file_path` | `Path \| None` | Path to persisted state file |
| `reason` | `str` | Human-readable description of outcome |

---

### 8. `RalphStatusResult` (Status Report)

Returned by `RalphLoop.status()`.

| Field | Type | Description |
|-------|------|-------------|
| `loops` | `list[RalphTaskSummary]` | All loops found (most recent first) |
| `active_count` | `int` | Loops with status=in_progress |
| `completed_count` | `int` | Loops with status=completed |
| `halted_count` | `int` | Loops with status=halted |
| `emergency_stop_active` | `bool` | True if vault/STOP_RALPH exists |

---

### 9. `RalphTaskSummary` (For Status Display)

Lightweight view of a `RalphTask` for status reporting.

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Task identifier |
| `status` | `LoopStatus` | Current state |
| `current_iteration` | `int` | Iterations run so far |
| `max_iterations` | `int` | Configured limit |
| `elapsed_seconds` | `float` | Seconds since loop started |
| `completion_strategy` | `CompletionStrategy` | How it detects completion |
| `started_at` | `str` | ISO 8601 start time |
| `halt_reason` | `HaltReason \| None` | Why it halted (if applicable) |
| `state_file_path` | `str` | Path to the state markdown file |

---

## State File Format

**Location**: `vault/ralph_wiggum/<TASK_ID>.md`

**YAML frontmatter** (machine-managed):
```yaml
---
type: ralph_wiggum_task
task_id: RW_20260224_080000
status: in_progress
completion_strategy: promise
completion_promise: TASK_COMPLETE
completion_file_pattern: ""
max_iterations: 10
current_iteration: 3
started_at: "2026-02-24T08:00:00Z"
last_iteration_at: "2026-02-24T08:05:00Z"
completed_at: null
halt_reason: null
completed_artifact: null
session_id: "abc123"
dev_mode: true
---
```

**Markdown body** (human-readable, sentinel-protected iteration table):
```markdown
# Ralph Task: RW_20260224_080000

**Prompt**: Process all files in /Needs_Action and move to Done when complete

## Status: in_progress — Iteration 3/10

<!-- ITERATIONS_SECTION_START -->
## Iteration History

| # | State | Started | Duration | Completion | Error |
|---|-------|---------|----------|-----------|-------|
| 1 | completed | 08:00:05 | 45.2s | no | — |
| 2 | completed | 08:01:02 | 52.1s | no | — |
| 3 | completed | 08:02:06 | 48.8s | no | — |
<!-- ITERATIONS_SECTION_END -->

## Notes

(Edit this section manually — not overwritten by system)
```

---

## Vault Folder: `vault/ralph_wiggum/`

New subdirectory added to canonical vault structure.

```
vault/ralph_wiggum/
├── RW_20260224_080000.md    # Active loop state
├── RW_20260223_143000.md    # Completed loop (retained for audit)
└── RW_20260222_091500.md    # Halted loop
```

**Retention**: Files retained indefinitely (never deleted by system). Human can archive manually. Matches Constitution Principle VII (90-day minimum log retention).

---

## Orchestrator Task File Format

Files in `vault/Needs_Action/` that trigger auto-spawn (US5):

```yaml
---
type: ralph_loop_task
subject: "Process and respond to all pending emails"
prompt: "Review all files in vault/Needs_Action/ with type=email_detected. For each: summarize, draft a reply, save to vault/Plans/. Output TASK_COMPLETE when all processed."
completion_strategy: promise
completion_promise: TASK_COMPLETE
max_iterations: 15
priority: medium
received: "2026-02-24T08:00:00Z"
---
```

**Required fields for auto-spawn**: `type: ralph_loop_task`, `prompt:`
**Optional fields**: `completion_strategy` (default: promise), `completion_promise` (default: TASK_COMPLETE), `max_iterations` (default: from RALPH_MAX_ITERATIONS env)

---

## Relationships

```
RalphConfig ──────────────── RalphTask (1:many)
                              │
RalphTask ─────────────────── IterationRecord (1:many, append-only)
          │
          └── CompletionStrategy (enum reference)
          └── LoopStatus (enum, current state)
          └── HaltReason (enum, set on halt)

RalphLoop.status() ────────── RalphStatusResult
                              └── RalphTaskSummary (1:many)

RalphLoop.start() ─────────── RalphRunResult
```
