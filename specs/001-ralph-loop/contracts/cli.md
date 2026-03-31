# CLI Contract: Ralph Wiggum Loop

**Module**: `backend.ralph_wiggum` (invoked as `python -m backend.ralph_wiggum`)
**Feature**: 001-ralph-loop

---

## Command: Start Loop (Promise-Based)

```bash
python -m backend.ralph_wiggum "PROMPT" \
  --completion-promise "TASK_COMPLETE" \
  [--max-iterations N] \
  [--vault-path PATH] \
  [--dry-run]
```

**Arguments**:
| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `PROMPT` | Yes | — | The task prompt text (positional) |
| `--completion-promise STR` | Conditional | — | Required if not using --completion-file. Marker string to detect in output. |
| `--completion-file GLOB` | Conditional | — | Required if not using --completion-promise. Glob pattern in vault/Done/. |
| `--max-iterations N` | No | RALPH_MAX_ITERATIONS | Override max iterations for this loop |
| `--vault-path PATH` | No | VAULT_PATH env | Override vault directory path |
| `--dry-run` | No | false | Run without writing files or logs |

**Mutual exclusion**: `--completion-promise` and `--completion-file` are mutually exclusive but one is required.

**Exit codes**:
- `0` — Loop completed (completion signal detected)
- `1` — Loop halted (safety limit reached)
- `2` — Loop error (unexpected failure)

**Stdout output (success)**:
```
✅ Loop completed: RW_20260224_080000
   Iterations: 3/10
   Duration: 2m 34s
   State file: vault/ralph_wiggum/RW_20260224_080000.md
```

**Stdout output (halted)**:
```
⚠️  Loop halted: RW_20260224_080001
   Reason: max_iterations_reached (10/10 used)
   Duration: 12m 01s
   State file: vault/ralph_wiggum/RW_20260224_080001.md
```

---

## Command: Start Loop (File-Movement)

```bash
python -m backend.ralph_wiggum "PROMPT" \
  --completion-file "vault/Done/task_*.md" \
  [--max-iterations N]
```

Same arguments as above with `--completion-file` instead of `--completion-promise`.

---

## Command: Status

```bash
python -m backend.ralph_wiggum --status [TASK_ID]
```

**Arguments**:
| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `TASK_ID` | No | — | Show specific loop only (optional) |

**Stdout output (running loops)**:
```
CEO Briefing Loop Status
========================
Emergency Stop: INACTIVE

Active Loops (1):
  RW_20260224_080000 — in_progress
    Iteration: 4/10 | Elapsed: 3m 42s | Strategy: promise
    Started: 2026-02-24 08:00:00 UTC

Completed Loops (2):
  RW_20260223_140000 — completed (iter 3/10, 2m 10s)
  RW_20260222_091500 — halted: max_iterations_reached (10/10, 60m 00s)
```

**Stdout output (no loops)**:
```
No Ralph loops found.
```

---

## Command: Emergency Stop

The emergency stop is triggered externally (not a CLI command):

```bash
# Trigger:
touch vault/STOP_RALPH

# Clear (after loops have halted):
rm vault/STOP_RALPH
```

---

## Stop Hook Contract

**Script**: `backend/ralph_wiggum/stop_hook.py`
**Invoked by**: Claude Code `onStop` event (configured in `.claude/settings.json`)

**Input** (stdin, JSON):
```json
{
  "session_id": "string",
  "hook_event_name": "onStop",
  "cwd": "/absolute/path",
  "claude_project_dir": "/absolute/path"
}
```

**Output on BLOCK** (stdout, JSON, exit 0):
```json
{
  "decision": "block",
  "reason": "Task RW_20260224_080000 incomplete. Iteration 3/10. Continue processing files in vault/Needs_Action/."
}
```

**Output on ALLOW** (exit 0, no JSON or approve):
```json
{"decision": "approve"}
```

**No active task** (allow exit, no blocking):
```json
{"decision": "approve"}
```

**Environment variables available to hook**:
- `CLAUDE_PROJECT_DIR` — absolute project root
- `TASK_ID` — set by orchestrator when spawning a loop (optional; hook searches vault if absent)

---

## Orchestrator API Contract

**Method**: `Orchestrator._check_ralph_loops()`

**Trigger**: Vault file in `vault/Needs_Action/` with `type: ralph_loop_task` frontmatter.

**Inputs from vault file frontmatter**:
```yaml
type: ralph_loop_task
prompt: "string"
completion_strategy: promise | file_movement    # optional, default: promise
completion_promise: "TASK_COMPLETE"             # optional, default: TASK_COMPLETE
max_iterations: 10                             # optional, default: RALPH_MAX_ITERATIONS
```

**Outputs**:
- On completion: task file moved to `vault/Done/`, log entry created
- On halt: task file remains in `vault/Needs_Action/` with updated frontmatter, log entry created with halt_reason
- On error: log entry with error, task file not moved

**Log entry format** (`vault/Logs/actions/YYYY-MM-DD.json`):
```json
{
  "timestamp": "2026-02-24T08:15:00Z",
  "action_type": "ralph_loop_completed",
  "actor": "ralph_wiggum",
  "task_id": "RW_20260224_080000",
  "iterations_run": 3,
  "status": "completed",
  "duration_seconds": 154.2
}
```
