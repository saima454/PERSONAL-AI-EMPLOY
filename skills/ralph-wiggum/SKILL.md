# Skill: Ralph Wiggum Loop

## Metadata

```yaml
name: ralph-wiggum
version: 1.0.0
layer: REASONING
sensitivity: LOW
```

## Triggers

Invoke this skill when the user says:
- "ralph loop" / "start ralph loop" / "run ralph loop"
- "keep iterating" / "keep going until done" / "loop until done"
- "don't stop" / "keep working" / "don't exit until complete"
- "loop until TASK_COMPLETE" / "repeat until complete"
- "run in a loop" / "iterate until finished"
- "auto-iterate" / "continuous iteration"
- "ralph status" / "loop status" / "check ralph"
- "stop ralph" / "emergency stop loop"

## What This Skill Does

The Ralph Wiggum Loop is a REASONING layer skill. It keeps Claude Code iterating on
multi-step tasks until completion is confirmed — either by a promise marker in output
or by a file appearing in `vault/Done/`. When Claude tries to exit, the stop hook
checks if the task is actually complete. If not, it re-injects the prompt with context
from previous iterations.

**Two execution modes:**
1. **Hook-based** (interactive): `.claude/settings.json` `onStop` hook intercepts
   Claude Code's natural exit. Stop hook reads state → blocks if incomplete.
2. **Subprocess-based** (programmatic): `ralph_loop.py` invokes `claude -p` in a loop.
   Orchestrator uses this mode to auto-spawn loops for `ralph_loop_task` vault files.

**Two completion strategies:**
- **Promise-based**: Claude outputs a specific marker string (default: `TASK_COMPLETE`)
  in its response to signal completion.
- **File-movement**: A target file matching a glob pattern appears in `vault/Done/`
  to signal the task is done.

## End-to-End Flow

```
Task prompt + completion strategy
        ↓
RalphLoop.start() — creates state file in vault/ralph_wiggum/
        ↓
_LoopController.run() — asyncio iteration loop
        ├── Check emergency stop (vault/STOP_RALPH sentinel)
        ├── Check total timeout elapsed
        ├── Run claude -p "{prompt}" --output-format json [--resume SESSION_ID]
        │     └── asyncio.wait_for(coro, timeout=per_iteration_timeout)
        ├── _check_completion(task, output):
        │     promise: completion_promise in output?
        │     file_movement: glob(completion_file_pattern) has matches?
        └── StateManager.update_task() — persist state after every iteration
                ↓
Loop exits when:
  completed → vault/ralph_wiggum/RW_*.md status=completed, exit code 0
  halted    → vault/ralph_wiggum/RW_*.md status=halted, exit code 1
  error     → vault/ralph_wiggum/RW_*.md status=error, exit code 2
        ↓
vault/Logs/actions/YYYY-MM-DD.json ← ralph_loop_completed / ralph_loop_halted entry
```

## Stop Hook Flow (Interactive Mode)

```
Claude Code tries to exit (onStop event)
        ↓
backend/ralph_wiggum/stop_hook.py reads stdin JSON
        ↓
StateManager loads vault/ralph_wiggum/*.md files
        ↓
Emergency stop active (vault/STOP_RALPH exists)?
  YES → {"decision": "block", "reason": "Emergency stop active..."}
  NO  ↓
Any in_progress tasks?
  NO  → {"decision": "approve"}
  YES ↓
At max_iterations?
  YES → task.status = halted; {"decision": "approve"}
  NO  → increment current_iteration; build continuation prompt
        {"decision": "block", "reason": "Task {id} incomplete. Iteration N/M. {context}"}
```

## No HITL Required

**No human approval needed.** Ralph loop operates entirely within the REASONING layer:
- All operations are local (vault reads/writes only)
- Claude still follows HITL workflow within each iteration (approvals still required
  for any sensitive actions Claude takes during iteration)
- Loop controller itself never sends emails, makes payments, or posts social content
- `vault/STOP_RALPH` provides human override at any time

Per constitution Principle IV: HITL applies to the actions Claude takes within
iterations, not to the loop controller itself.

## Permissions

```yaml
permissions:
  vault_read:
    - vault/ralph_wiggum/*.md
    - vault/Needs_Action/*.md  # for orchestrator ralph_loop_task detection
    - vault/STOP_RALPH         # emergency stop sentinel
  vault_write:
    - vault/ralph_wiggum/RW_*.md    # state files (created + updated each iteration)
    - vault/Logs/actions/YYYY-MM-DD.json  # iteration log entries
    - vault/Done/               # completed task files (orchestrator mode only)
  external_apis: none
  browser: none
  subprocess:
    - claude -p "..." --output-format json  # subprocess mode only
```

## Dependencies

- `backend/ralph_wiggum/__init__.py` — RalphConfig, RalphTask, IterationRecord, enums
- `backend/ralph_wiggum/state_manager.py` — StateManager (vault state CRUD)
- `backend/ralph_wiggum/prompt_injector.py` — PromptInjector (context continuity)
- `backend/utils/frontmatter.py` — extract_frontmatter(), format_with_frontmatter()
- `backend/utils/logging_utils.py` — log_action()
- `backend/utils/timestamps.py` — now_iso(), parse_iso()
- `vault/ralph_wiggum/` — state files directory (created at runtime)

## CLI Commands

```bash
# Promise-based loop (DEV_MODE simulation — auto-completes at iteration 3)
DEV_MODE=true uv run python -m backend.ralph_wiggum \
  "Process all files in vault/Needs_Action and move each to Done" \
  --completion-promise "TASK_COMPLETE" \
  --max-iterations 5

# File-movement loop (waits for matching file in vault/Done/)
DEV_MODE=true uv run python -m backend.ralph_wiggum \
  "Draft a response to INVOICE_123.md and save to vault/Done/" \
  --completion-file "vault/Done/INVOICE_123.md" \
  --max-iterations 10

# Dry-run mode (no files written, no real subprocess calls)
DEV_MODE=true uv run python -m backend.ralph_wiggum \
  "Test task" \
  --completion-promise "TASK_COMPLETE" \
  --dry-run

# Status — all loops
uv run python -m backend.ralph_wiggum --status

# Status — specific loop
uv run python -m backend.ralph_wiggum --status RW_20260224_080000

# Emergency stop (external — create sentinel file)
touch vault/STOP_RALPH
# Clear after loop halts:
rm vault/STOP_RALPH
```

## Decision Tree

```
ralph loop command issued
        ↓
Validate args: completion_promise XOR completion_file (one required)
        ↓
Generate task_id = RW_{YYYYMMDD_HHMMSS}
Create vault/ralph_wiggum/{task_id}.md (unless --dry-run)
        ↓
DEV_MODE=true?
  YES → simulate iterations (sleep 1s + fake output)
        auto-output completion marker at iteration 3 or max_iterations
  NO  ↓
Loop:
  1. Check vault/STOP_RALPH → halt if exists
  2. Check total elapsed >= total_timeout → halt
  3. asyncio.wait_for(claude -p prompt --resume session_id, timeout=iteration_timeout)
  4. Check completion → exit loop if detected
  5. StateManager.update_task() → persist state
  6. current_iteration >= max_iterations → halt
        ↓
Exit: completed (0) | halted (1) | error (2)
```

## State File Format

State files live at `vault/ralph_wiggum/RW_YYYYMMDD_HHMMSS.md`:

```yaml
---
task_id: RW_20260224_080000
prompt: "Process all files in vault/Needs_Action"
completion_strategy: promise
completion_promise: TASK_COMPLETE
completion_file_pattern: null
max_iterations: 10
iteration_timeout: 300
total_timeout: 3600
status: completed            # in_progress | completed | halted | error
current_iteration: 3
started_at: "2026-02-24T08:00:00Z"
last_iteration_at: "2026-02-24T08:00:06Z"
completed_at: "2026-02-24T08:00:06Z"
halt_reason: null            # max_iterations_reached | per_iteration_timeout | ...
completed_artifact: null
session_id: "abc123"
dev_mode: true
---

## Iterations

<!-- ITERATIONS_SECTION_START -->
| # | Started | Duration | Status | Notes |
|---|---------|----------|--------|-------|
| 1 | 08:00:00 | 2.1s | ok | simulated |
| 2 | 08:00:02 | 1.8s | ok | simulated |
| 3 | 08:00:04 | 2.0s | completed | completion marker detected |
<!-- ITERATIONS_SECTION_END -->
```

## Orchestrator Task File Format

To auto-spawn a Ralph loop, create a file in `vault/Needs_Action/`:

```yaml
---
type: ralph_loop_task
subject: "Process Q1 invoices"
prompt: "Review all invoices in vault/Needs_Action/ and draft responses. Save to vault/Done/ when all processed."
completion_strategy: promise          # optional, default: promise
completion_promise: TASK_COMPLETE     # optional, default: TASK_COMPLETE
max_iterations: 5                     # optional, default: RALPH_MAX_ITERATIONS
priority: low
received: "2026-02-24T08:00:00Z"
---
```

The orchestrator's `_check_ralph_loops()` method picks this up, spawns `RalphLoop.start()`,
and moves the file to `vault/Done/` on completion.

## DEV_MODE Behavior

When `DEV_MODE=true`:
- No real `claude -p` subprocess calls
- Each iteration: `await asyncio.sleep(1)` + generates fake output string
- Iteration 3 (or `max_iterations` if < 3) auto-outputs the completion marker
- All state files still written (use `--dry-run` to suppress writes)
- CLI output prefixed with `[DEV_MODE]` per iteration

## Safety Constraints

- **max_iterations**: Loop halts after N iterations (default: 10, env: `RALPH_MAX_ITERATIONS`)
- **per_iteration_timeout**: Each iteration killed after N seconds (default: 300s, `RALPH_ITERATION_TIMEOUT`)
- **total_timeout**: Full loop killed after N seconds (default: 3600s, `RALPH_TOTAL_TIMEOUT`)
- **vault/STOP_RALPH**: Create this file to immediately halt all active loops
- **DRY_RUN**: All state writes suppressed; loop runs but no files created
- State written after **every iteration** — worst-case recovery = 1 iteration of lost work
- Stop hook never raises; always outputs valid JSON with exit 0

## Environment Variables

```
RALPH_MAX_ITERATIONS=10       # Maximum iterations per loop (default: 10)
RALPH_ITERATION_TIMEOUT=300   # Per-iteration timeout in seconds (default: 5 min)
RALPH_TOTAL_TIMEOUT=3600      # Total loop timeout in seconds (default: 60 min)
DEV_MODE=true                 # Simulate execution (no real subprocess calls)
VAULT_PATH=./vault            # Path to vault root
```
