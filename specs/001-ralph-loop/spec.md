# Feature Specification: Ralph Wiggum Loop

**Feature Branch**: `001-ralph-loop`
**Created**: 2026-02-24
**Status**: Draft
**Input**: "Ralph Wiggum Loop (Gold Tier) — stop-hook pattern that keeps Claude Code iterating until a multi-step task is complete."

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Promise-Based Task Loop (Priority: P1)

An operator starts a long-running multi-step task (e.g., "process every file in Needs_Action and move each to Done"). The system runs the task, and each time the AI tries to exit before finishing, the loop intercepts and continues. When the AI explicitly signals completion (by outputting an agreed-upon marker), the loop ends cleanly. The operator returns to a fully completed task without having to manually restart anything.

**Why this priority**: This is the core "Ralph Wiggum" pattern — preventing premature exit on multi-step tasks. All other completion strategies and safety features build on this loop-and-intercept foundation.

**Independent Test**: Start a loop with a multi-step prompt and a completion marker. Verify that: (a) the loop continues past the first exit attempt, (b) the loop terminates cleanly when the completion marker is detected in the output, (c) a task state file exists with status="completed" and accurate iteration count.

**Acceptance Scenarios**:

1. **Given** a task prompt is submitted with a promise-based completion marker, **When** the AI finishes its first iteration without outputting the marker, **Then** the loop intercepts the exit, re-injects the original prompt with the previous output appended, and starts the next iteration.
2. **Given** the AI outputs the agreed completion marker anywhere in its response, **When** the stop hook evaluates the output, **Then** the loop exits cleanly and the task state file shows status="completed".
3. **Given** `DEV_MODE=true`, **When** any loop is started, **Then** no real external actions are taken; the loop uses simulated outputs to demonstrate the pattern.
4. **Given** `DRY_RUN=true`, **When** any loop is started, **Then** the loop runs but writes no state files or logs (reads-only, console output only).

---

### User Story 2 — File-Movement Completion Detection (Priority: P2)

An operator starts a task loop targeting a specific file or pattern (e.g., "draft a response to INVOICE_123.md and save to Done"). Instead of requiring the AI to output a special marker, the loop watches for the target file to appear in the Done folder. When detected, the loop ends. This is useful for tasks with concrete, verifiable output artifacts.

**Why this priority**: Many AI Employee tasks produce physical files as output. Detecting real file artifacts as completion signals is more reliable than text markers for these workflows, but requires the promise-based loop to exist first.

**Independent Test**: Start a file-movement loop targeting a glob pattern. Verify that: (a) the loop continues while the target file is absent from Done, (b) once the file appears in Done (simulated in DEV_MODE), the loop exits cleanly, (c) the task state file reflects the detected artifact path.

**Acceptance Scenarios**:

1. **Given** a task loop is started with a file-movement completion target (`vault/Done/task_*.md`), **When** the AI has not yet created the target file in Done, **Then** each exit attempt is intercepted and the task continues.
2. **Given** the target file now exists in `vault/Done/` matching the configured pattern, **When** the stop hook evaluates completion, **Then** the loop exits cleanly and the state file records the completed artifact path.
3. **Given** multiple files match the completion pattern, **When** the first match appears, **Then** the loop exits (earliest match wins).

---

### User Story 3 — Safety Limits and Emergency Stop (Priority: P3)

An operator needs confidence that a runaway loop cannot consume unlimited time or resources. The system enforces a maximum number of iterations, a per-iteration time limit, and an overall session time limit. Additionally, any operator can drop an emergency stop file to instantly halt all running loops.

**Why this priority**: Without safety limits, a loop could run indefinitely on a stuck or misunderstood task. These guardrails make the feature safe for production use on real business workflows.

**Independent Test**: Configure a loop with max 3 iterations. Verify that: (a) the loop halts after 3 iterations even without a completion signal, (b) the task state file shows status="halted" with reason="max_iterations_reached", (c) creating `vault/STOP_RALPH` halts the loop within one iteration cycle.

**Acceptance Scenarios**:

1. **Given** a loop has reached its configured maximum iterations (default: 10), **When** the stop hook checks completion, **Then** the loop halts with status="halted", reason="max_iterations_reached", and the operator is notified.
2. **Given** a single iteration runs longer than the per-iteration timeout (default: 5 minutes), **When** the timeout elapses, **Then** that iteration is terminated, counted, and the loop either continues to the next iteration or halts if total timeout is also reached.
3. **Given** the loop has been running longer than the total session timeout (default: 60 minutes), **When** any exit attempt occurs, **Then** the loop halts regardless of completion status, with reason="total_timeout_exceeded".
4. **Given** a file named `STOP_RALPH` is created in the vault root during an active loop, **When** the stop hook next evaluates, **Then** all active loops halt immediately with status="halted", reason="emergency_stop".
5. **Given** a loop halts for any safety reason, **When** the operator reviews logs, **Then** the final iteration, halt reason, and total duration are all recorded.

---

### User Story 4 — Status Monitoring (Priority: P4)

An operator wants to know the current state of any running or recently completed Ralph loops. The status command shows task ID, current iteration, completion strategy, elapsed time, and final status for all loops (active, completed, or halted).

**Why this priority**: Observability is essential for production workflows. Operators need to verify loops are progressing, identify stuck tasks, and audit past loops.

**Independent Test**: Start a loop, then run `--status` before it completes. Verify that: (a) the running loop appears with current iteration count and elapsed time, (b) after loop completion, status shows "completed" with total iterations and duration.

**Acceptance Scenarios**:

1. **Given** a loop is in progress, **When** `--status` is run, **Then** output shows the task ID, current iteration number, elapsed time, completion strategy, and "in_progress" status.
2. **Given** a loop has completed or halted, **When** `--status` is run, **Then** output shows final status, total iterations run, completion signal that triggered exit, and total duration.
3. **Given** no loops have ever run, **When** `--status` is run, **Then** output states "No Ralph loops found."
4. **Given** multiple loops have run, **When** `--status` is run, **Then** all loops appear (most recent first) with their individual statuses.

---

### User Story 5 — Orchestrator Integration (Priority: P5)

The orchestrator automatically spawns a Ralph loop for complex multi-step tasks that it identifies from the vault. The operator does not have to manually start the loop; the orchestrator recognises the task type, creates a loop with appropriate parameters, and the loop runs to completion autonomously.

**Why this priority**: Autonomous orchestration is the "Digital FTE" product promise. Manual CLI invocation is useful for testing, but real business value comes from hands-free operation.

**Independent Test**: Configure the orchestrator to monitor for tasks tagged as "requires_loop" in Needs_Action. Verify that: (a) such a task triggers automatic Ralph loop creation, (b) the loop runs to completion, (c) the task file ends up in Done, and (d) the action appears in vault/Logs/.

**Acceptance Scenarios**:

1. **Given** a task file in `vault/Needs_Action/` is tagged with a loop-eligible type, **When** the orchestrator processes it, **Then** a Ralph loop is spawned automatically without operator intervention.
2. **Given** the orchestrator spawns a loop, **When** the loop completes, **Then** the result is logged in `vault/Logs/` and the task file is moved to `vault/Done/`.
3. **Given** a loop spawned by the orchestrator hits a safety limit, **When** the loop halts, **Then** the task file remains in `vault/Needs_Action/` (not moved to Done) and the orchestrator logs the halt reason for human review.

---

### Edge Cases

- What happens if the AI crashes mid-iteration (rather than attempting a clean exit)?
- What if the completion file pattern matches zero files because the path is wrong?
- What if `vault/STOP_RALPH` is created while an iteration is actively running (mid-output)?
- What if `vault/Logs/` does not exist when the first loop starts?
- What if a loop is started with max_iterations=0 or a negative timeout value?
- What if the same task prompt is submitted twice simultaneously (duplicate loops)?
- What if the completion marker appears in quoted/example text rather than as a final signal?

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a task prompt and a completion strategy (promise-based or file-movement) to start a loop.
- **FR-002**: System MUST intercept each AI exit attempt and evaluate whether the task is complete before allowing exit.
- **FR-003**: System MUST re-inject the original prompt plus a summary of previous output each time the task continues.
- **FR-004**: System MUST detect promise-based completion by scanning each iteration's output for the configured completion marker string.
- **FR-005**: System MUST detect file-movement completion by checking whether a file matching the configured path pattern exists in `vault/Done/`.
- **FR-006**: System MUST halt a loop after reaching the configured maximum iteration count (default: 10) if no completion signal has been detected.
- **FR-007**: System MUST enforce a per-iteration time limit (default: 5 minutes); iterations exceeding this limit are terminated and counted.
- **FR-008**: System MUST enforce a total session time limit (default: 60 minutes); loops exceeding this halt regardless of completion status.
- **FR-009**: System MUST detect and honour a `vault/STOP_RALPH` sentinel file — all active loops halt within one evaluation cycle.
- **FR-010**: System MUST persist task state (task ID, prompt, strategy, iteration count, status, timestamps) to a state file in the vault after every iteration.
- **FR-011**: System MUST log every iteration outcome (started, completed, interrupted, halted) to `vault/Logs/`.
- **FR-012**: System MUST provide a `--status` command that reports the current state of all running and completed loops.
- **FR-013**: System MUST respect `DEV_MODE` — no real external actions; use simulated behaviour to demonstrate loop mechanics.
- **FR-014**: System MUST respect `DRY_RUN` — loop logic runs but no state files or logs are written.
- **FR-015**: System MUST accept configurable limits via environment variables (`RALPH_MAX_ITERATIONS`, `RALPH_ITERATION_TIMEOUT`, `RALPH_TOTAL_TIMEOUT`) with documented defaults.
- **FR-016**: Orchestrator MUST be able to spawn Ralph loops programmatically for eligible tasks without requiring CLI invocation.

### Key Entities

- **Ralph Task**: A single loop session — contains task ID, prompt text, completion strategy, current iteration count, status (in_progress / completed / halted), start time, last-iteration time, and halt reason if applicable.
- **Iteration Record**: A per-cycle log entry recording the iteration number, what happened (completed / intercepted / timed-out), and any completion signals detected.
- **Completion Signal**: Either a promise string detected in AI output, or a file path confirmed present in `vault/Done/`.
- **Safety Limit**: A configured ceiling on iterations, per-iteration duration, or total session duration that triggers an automatic halt.
- **Emergency Stop**: The presence of `vault/STOP_RALPH` sentinel file, which overrides all other loop state and triggers an immediate halt.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Multi-step tasks that previously required 3+ manual restarts complete in a single unattended session in 90% of cases.
- **SC-002**: No loop exceeds its configured maximum iteration count; 100% of loops halt at or before the limit.
- **SC-003**: Emergency stop halts all active loops within one full iteration cycle (at most the per-iteration timeout duration).
- **SC-004**: 100% of iterations are logged — every loop produces a complete audit trail in `vault/Logs/`.
- **SC-005**: Status command accurately reflects loop state (within one iteration cycle of any state change) for 100% of running and recently completed loops.
- **SC-006**: Orchestrator-spawned loops require zero operator intervention for tasks that complete within safety limits.

---

## Assumptions

- The AI (Claude Code) is the sole executor inside each loop iteration; no human performs work mid-loop.
- "Re-injecting the prompt" means prepending the original task prompt to a summary of what was accomplished in previous iterations, so the AI has full context on each restart.
- The promise completion marker defaults to `TASK_COMPLETE` but is configurable per-loop; it may appear anywhere in the output (not just at the end).
- File-movement completion checks `vault/Done/` using a glob pattern; the first match triggers exit.
- `vault/STOP_RALPH` is a plain file (any content); presence alone is the signal — the file is not deleted by the system.
- Each loop has a globally unique task ID generated at start time (e.g., timestamp-based).
- DEV_MODE simulates loop behaviour without executing real prompts against external services; the loop still iterates through its state machine to demonstrate correctness.
- Task state files live in `vault/ralph_wiggum/` (a new subdirectory within the vault).
- The orchestrator integration is opt-in — tasks must be explicitly tagged or matched by a configured rule to trigger automatic loop spawning.

---

## Out of Scope

- Parallel execution of multiple iterations of the same loop simultaneously (loops are strictly sequential).
- Human-in-the-loop approval between individual iterations (HITL applies at the task level, not within the loop).
- Pausing and resuming a loop (loops are always in-progress or terminated; no suspended state).
- Distributed loop execution across multiple machines.
