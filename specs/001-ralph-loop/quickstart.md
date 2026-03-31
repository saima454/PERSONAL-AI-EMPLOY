# Quickstart: Ralph Wiggum Loop

**Feature**: 001-ralph-loop
**Prerequisites**: `DEV_MODE=true` (default), vault/ exists with standard folders

---

## Scenario 1: Promise-Based Loop (DEV_MODE Simulation)

Test the core loop mechanic — AI outputs completion marker after N iterations.

```bash
DEV_MODE=true uv run python -m backend.ralph_wiggum \
  "Process all files in vault/Needs_Action and move each to Done" \
  --completion-promise "TASK_COMPLETE" \
  --max-iterations 5
```

**Expected output**:
```
🔄 Starting Ralph loop: RW_20260224_080000
   Strategy: promise (marker: TASK_COMPLETE)
   Max iterations: 5

[DEV_MODE] Iteration 1/5: simulated (2.1s)
[DEV_MODE] Iteration 2/5: simulated (1.8s)
[DEV_MODE] Iteration 3/5: simulated — completion marker detected

✅ Loop completed: RW_20260224_080000
   Iterations: 3/5
   Duration: 0m 06s
   State file: vault/ralph_wiggum/RW_20260224_080000.md
```

**Verify**:
- `vault/ralph_wiggum/RW_20260224_080000.md` exists
- Frontmatter shows `status: completed`, `current_iteration: 3`
- Log entry appears in `vault/Logs/actions/2026-02-24.json`

---

## Scenario 2: File-Movement Completion (DEV_MODE)

Test file-based completion detection.

```bash
DEV_MODE=true uv run python -m backend.ralph_wiggum \
  "Draft a response to INVOICE_123.md and save to vault/Done/" \
  --completion-file "vault/Done/INVOICE_123.md" \
  --max-iterations 10
```

**Expected output**:
```
🔄 Starting Ralph loop: RW_20260224_080001
   Strategy: file_movement (pattern: vault/Done/INVOICE_123.md)
   Max iterations: 10

[DEV_MODE] Iteration 1/10: simulated
[DEV_MODE] Iteration 2/10: simulated
[DEV_MODE] Iteration 3/10: simulated — completion file detected

✅ Loop completed: RW_20260224_080001
   Iterations: 3/10
   Artifact: vault/Done/INVOICE_123.md
   State file: vault/ralph_wiggum/RW_20260224_080001.md
```

---

## Scenario 3: Max Iterations Safety Limit

Test that the loop halts after the configured maximum.

```bash
DEV_MODE=true uv run python -m backend.ralph_wiggum \
  "An impossible task that never completes" \
  --completion-promise "__NEVER_OUTPUT_THIS__" \
  --max-iterations 3
```

**Expected output**:
```
🔄 Starting Ralph loop: RW_20260224_080002
   Strategy: promise (marker: __NEVER_OUTPUT_THIS__)
   Max iterations: 3

[DEV_MODE] Iteration 1/3: simulated
[DEV_MODE] Iteration 2/3: simulated
[DEV_MODE] Iteration 3/3: simulated — max iterations reached

⚠️  Loop halted: RW_20260224_080002
   Reason: max_iterations_reached (3/3 used)
   Duration: 0m 07s
   State file: vault/ralph_wiggum/RW_20260224_080002.md
```

**Verify**:
- State file shows `status: halted`, `halt_reason: max_iterations_reached`
- Exit code 1 (`echo $?`)

---

## Scenario 4: Status Command

Check all loop states.

```bash
uv run python -m backend.ralph_wiggum --status
```

**Expected output** (after running Scenarios 1-3):
```
Ralph Loop Status
=================
Emergency Stop: INACTIVE

Completed Loops (2):
  RW_20260224_080000 — completed (iter 3/5, 0m 06s)
  RW_20260224_080001 — completed (iter 3/10, 0m 07s)

Halted Loops (1):
  RW_20260224_080002 — halted: max_iterations_reached (3/3, 0m 07s)
```

---

## Scenario 5: Emergency Stop

Test the sentinel file halt mechanism.

```bash
# Terminal 1: Start a slow loop
DEV_MODE=true uv run python -m backend.ralph_wiggum \
  "Long task" \
  --completion-promise "__NEVER__" \
  --max-iterations 100 &

# Terminal 2: Within 2 seconds, create the sentinel
touch vault/STOP_RALPH
```

**Expected**: Loop halts within 1 iteration cycle with `reason: emergency_stop`. Remove sentinel after:
```bash
rm vault/STOP_RALPH
```

---

## Scenario 6: DRY_RUN Mode

Test that no files are written.

```bash
# Record file count before
before=$(ls vault/ralph_wiggum/ 2>/dev/null | wc -l)

DEV_MODE=true uv run python -m backend.ralph_wiggum \
  "Test task" \
  --completion-promise "TASK_COMPLETE" \
  --dry-run

# Verify no new files
after=$(ls vault/ralph_wiggum/ 2>/dev/null | wc -l)
echo "Files before: $before, after: $after"  # Should be equal
```

---

## Scenario 7: Status Command — Specific Loop

```bash
uv run python -m backend.ralph_wiggum --status RW_20260224_080000
```

**Expected**:
```
Loop: RW_20260224_080000
  Status:     completed
  Strategy:   promise (TASK_COMPLETE)
  Iterations: 3/5
  Duration:   6s
  Started:    2026-02-24 08:00:00 UTC
  Completed:  2026-02-24 08:00:06 UTC
```

---

## Scenario 8: Orchestrator Integration

Verify auto-spawn from vault task file.

```bash
# Create a ralph_loop_task in Needs_Action
cat > vault/Needs_Action/RALPH_test_task.md << 'EOF'
---
type: ralph_loop_task
subject: "Test orchestrator integration"
prompt: "Do something simple and output TASK_COMPLETE when done"
completion_strategy: promise
completion_promise: TASK_COMPLETE
max_iterations: 5
priority: low
received: "2026-02-24T08:00:00Z"
---
EOF

# Start orchestrator (it will pick up the task)
DEV_MODE=true uv run python -m backend.orchestrator --once
```

**Expected**: Orchestrator detects the `ralph_loop_task` file, spawns a Ralph loop, loop completes in DEV_MODE, task file moves to `vault/Done/`, log entry in `vault/Logs/actions/`.

---

## Scenario 9: Stop Hook (Interactive Mode)

Verify the `onStop` hook intercepts Claude Code's exit.

**Prerequisites**: `.claude/settings.json` configured with `onStop` hook (set up during implementation).

```bash
# Start Claude Code with a task
DEV_MODE=true claude --task "Process all files in vault/Needs_Action"

# Claude Code will work, try to stop, and the hook will re-inject if task is incomplete
# Check state file to see iteration count increase
ls -la vault/ralph_wiggum/
```

**Expected**: State file updated with `current_iteration > 1` before Claude exits.

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `RALPH_MAX_ITERATIONS` | `10` | Maximum iterations per loop |
| `RALPH_ITERATION_TIMEOUT` | `300` | Per-iteration timeout (seconds) |
| `RALPH_TOTAL_TIMEOUT` | `3600` | Total loop timeout (seconds) |
| `DEV_MODE` | `true` | Simulate execution (no real subprocess calls) |
| `VAULT_PATH` | `./vault` | Path to vault root |
