# Feature Specification: Orchestrator + Scheduling

**Feature Branch**: `002-orchestrator-scheduling`
**Created**: 2026-02-18
**Status**: Draft
**Input**: User description: "Create the master Orchestrator that connects all watchers, reasoning, and actions together — the glue that makes the AI Employee autonomous."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Single Command Startup (Priority: P1)

The user runs `python -m backend.orchestrator` and all configured watchers (Gmail, WhatsApp, LinkedIn) start as background tasks. The terminal shows a live status summary of what launched, what is running, and any startup errors.

**Why this priority**: Without a single entry point, the user must manually start each watcher in separate terminals. This is the foundational capability — everything else builds on the orchestrator being alive and managing processes.

**Independent Test**: Can be fully tested by running the orchestrator and observing that it prints startup status for each watcher and stays running. Delivers immediate value — one command replaces three manual launches.

**Acceptance Scenarios**:

1. **Given** the orchestrator is started with valid configuration, **When** the process launches, **Then** all enabled watchers start as concurrent tasks and the orchestrator prints the name and status of each watcher within 5 seconds.
2. **Given** one watcher fails to start (e.g., missing credentials), **When** the orchestrator launches, **Then** the healthy watchers still start and the failed watcher is reported with a clear error message.
3. **Given** the user presses Ctrl+C, **When** the signal is received, **Then** all watchers are gracefully stopped within 10 seconds and the orchestrator exits cleanly.
4. **Given** DEV_MODE is true, **When** the orchestrator starts, **Then** all watchers run in observation-only mode and the dashboard shows DEV_MODE status.

---

### User Story 2 - Automatic Crash Recovery (Priority: P2)

A running watcher crashes (exception, network failure, memory error). The orchestrator detects the crash within one check interval (default 30s) and automatically restarts the watcher up to a configurable maximum number of attempts (default 3).

**Why this priority**: Long-running autonomous agents must self-heal. Without crash recovery, a single watcher failure silently degrades the system. This is critical for the "24/7 Digital FTE" promise.

**Independent Test**: Can be tested by starting the orchestrator, then simulating a watcher crash (e.g., raising an unhandled exception in a watcher task). Verify the orchestrator detects the crash, logs it, increments the restart counter, and relaunches the watcher.

**Acceptance Scenarios**:

1. **Given** a watcher task raises an unhandled exception, **When** the orchestrator detects the failure, **Then** it logs the error, waits a brief backoff period, and restarts the watcher.
2. **Given** a watcher has been restarted the maximum number of times (default 3) within a window, **When** it crashes again, **Then** the orchestrator marks the watcher as permanently failed and alerts the user via the dashboard and logs.
3. **Given** a watcher crashes and is restarted, **When** the restart succeeds, **Then** the restart counter for that watcher is preserved and the dashboard shows the watcher's new status.

---

### User Story 3 - Approved Action Execution (Priority: P3)

A human reviews a proposed action and moves the approval file to `vault/Approved/`. The orchestrator's action executor detects the new file, reads its frontmatter to determine the action type (email_send, email_reply, linkedin_post), executes the corresponding action via the appropriate backend, and moves the file to `vault/Done/` with completion metadata.

**Why this priority**: This closes the HITL loop — without it, approved actions sit unexecuted. Builds on the Email MCP server (feature 001) and the vault workflow. High impact but depends on watchers running (P1) and recovery (P2).

**Independent Test**: Can be tested by placing a pre-approved email_send file in `vault/Approved/`, running the action executor, and verifying the email is sent (or logged in DEV_MODE) and the file moves to `vault/Done/`.

**Acceptance Scenarios**:

1. **Given** a file with `type: email_send` and `status: approved` appears in `vault/Approved/`, **When** the action executor processes it, **Then** the email is sent via the Email MCP server pipeline (approval check, rate limit, send, audit log) and the file is moved to `vault/Done/` with `completed_at` timestamp.
2. **Given** a file with `type: email_reply` and a valid `thread_id`, **When** the action executor processes it, **Then** the reply is sent via the Email MCP reply pipeline and the file is moved to `vault/Done/`.
3. **Given** a file with an unrecognized type, **When** the action executor processes it, **Then** it logs a warning and leaves the file in `vault/Approved/` for manual handling.
4. **Given** the action execution fails (e.g., rate limit exceeded, auth error), **When** the error occurs, **Then** the file remains in `vault/Approved/` with an error note appended, and the error is logged.
5. **Given** DEV_MODE is true, **When** the action executor processes a file, **Then** the action is logged but not executed, and the file is moved to `vault/Done/` with a `[DEV_MODE]` note.

---

### User Story 4 - Live Dashboard Updates (Priority: P4)

The orchestrator periodically updates `vault/Dashboard.md` (default every 5 minutes) with the current status of all watchers, counts of files in each vault folder, last activity timestamp, DEV_MODE status, and any active errors.

**Why this priority**: The dashboard is the user's primary visibility into the system. Without it, the user has no way to know if the AI Employee is healthy without checking logs manually. Lower priority because the system works without it — it's observability, not functionality.

**Independent Test**: Can be tested by running the orchestrator for one dashboard interval and verifying that `vault/Dashboard.md` is updated with accurate watcher statuses and folder counts.

**Acceptance Scenarios**:

1. **Given** the orchestrator is running, **When** the dashboard update interval elapses, **Then** `vault/Dashboard.md` is overwritten with current watcher statuses (running/stopped/error), file counts per vault folder, last activity timestamp, and DEV_MODE status.
2. **Given** a watcher has crashed and been restarted, **When** the dashboard updates, **Then** the watcher's status shows the restart count and last error message.
3. **Given** the vault contains files in Needs_Action, Approved, and Done folders, **When** the dashboard updates, **Then** the counts accurately reflect the number of `.md` files in each folder.

---

### User Story 5 - Windows Task Scheduler Integration (Priority: P5)

PowerShell scripts enable the user to register the orchestrator as a scheduled task in Windows Task Scheduler. The orchestrator starts automatically on user login, restarts if it crashes, and can optionally trigger a daily briefing generation at a configured time (default 8:00 AM).

**Why this priority**: Scheduling makes the AI Employee truly autonomous — it runs without the user remembering to start it. Lowest priority because it's a deployment concern, not core functionality, and the orchestrator must work correctly first (P1-P4).

**Independent Test**: Can be tested by running the setup script and verifying the scheduled task appears in Windows Task Scheduler with correct triggers (logon, daily).

**Acceptance Scenarios**:

1. **Given** the user runs the setup scheduler script, **When** it completes, **Then** a Windows scheduled task is registered that starts the orchestrator on user login.
2. **Given** the orchestrator process crashes, **When** the scheduled task detects the exit, **Then** it restarts the orchestrator automatically.
3. **Given** the user runs the stop script, **When** it completes, **Then** the orchestrator process is terminated and the scheduled task is removed or disabled.

---

### Edge Cases

- What happens when the vault folders don't exist at startup? The orchestrator creates any missing vault subdirectories before starting watchers.
- What happens when two approval files for the same action exist? The action executor processes files one at a time in creation-time order; the second file will fail the approval check (already consumed) and be left for manual review.
- What happens when the orchestrator is started while another instance is already running? A lock file (`config/.orchestrator.lock`) prevents duplicate instances. The second instance exits with a clear error message.
- What happens when a watcher's dependencies aren't installed (e.g., Playwright for LinkedIn)? The orchestrator logs the import error and skips that watcher, continuing with the others.
- What happens when the Dashboard.md file is open in Obsidian during an update? The orchestrator writes to a temp file and atomically renames it, preventing partial reads.
- What happens when the config/.env file is missing? The orchestrator falls back to default values for all settings and logs a warning.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a single entry point (`python -m backend.orchestrator`) that starts all configured watchers as concurrent async tasks.
- **FR-002**: System MUST monitor each watcher task's health and detect crashes within one check interval (configurable, default 30 seconds).
- **FR-003**: System MUST automatically restart crashed watchers up to a configurable maximum (default 3 attempts) with exponential backoff between restarts.
- **FR-004**: System MUST mark watchers as permanently failed after exceeding the restart limit and log the failure.
- **FR-005**: System MUST handle Ctrl+C (SIGINT) by gracefully shutting down all watchers and the action executor within 10 seconds.
- **FR-006**: System MUST watch `vault/Approved/` for new `.md` files and execute the corresponding action based on the file's `type` frontmatter field.
- **FR-007**: System MUST support action types: `email_send`, `email_reply`, and `linkedin_post` (extensible to new types).
- **FR-008**: System MUST move executed approval files to `vault/Done/` with `status: done` and `completed_at` timestamp after successful execution.
- **FR-009**: System MUST leave approval files in place and log the error when action execution fails.
- **FR-010**: System MUST update `vault/Dashboard.md` at a configurable interval (default 300 seconds) with watcher statuses, vault folder counts, last activity time, and DEV_MODE status.
- **FR-011**: System MUST log all orchestrator events (starts, stops, crashes, restarts, action executions) to the vault audit trail.
- **FR-012**: System MUST prevent duplicate instances via a lock file mechanism.
- **FR-013**: System MUST create any missing vault subdirectories at startup.
- **FR-014**: System MUST respect DEV_MODE — when true, actions are logged but not executed against external services.
- **FR-015**: System MUST provide PowerShell scripts for starting, stopping, and scheduling the orchestrator via Windows Task Scheduler.
- **FR-016**: System MUST skip watchers whose dependencies are not available (e.g., missing packages) and continue with the remaining watchers.

### Key Entities

- **Watcher Task**: A managed async task wrapping a watcher (Gmail, WhatsApp, LinkedIn). Tracks name, status (running/stopped/error/failed), restart count, last error, and last heartbeat timestamp.
- **Action Executor**: A background loop that polls `vault/Approved/` for new files and dispatches them to the appropriate handler based on frontmatter type.
- **Dashboard State**: A snapshot of the orchestrator's current state rendered to `vault/Dashboard.md`. Includes watcher statuses, vault folder file counts, timestamps, and error summaries.
- **Lock File**: A file (`config/.orchestrator.lock`) containing the process PID, used to prevent duplicate orchestrator instances.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The user can start all watchers and the action executor with a single command and see status confirmation within 5 seconds.
- **SC-002**: A crashed watcher is detected and restart-attempted within 60 seconds of the crash.
- **SC-003**: Approved actions in `vault/Approved/` are detected and executed within one check interval (default 30 seconds) of the file appearing.
- **SC-004**: `vault/Dashboard.md` reflects the current system state within one dashboard interval (default 5 minutes) of any status change.
- **SC-005**: The orchestrator shuts down all watchers gracefully within 10 seconds of receiving a stop signal.
- **SC-006**: The orchestrator operates continuously for 24+ hours without memory leaks or unhandled errors in a stable network environment.
- **SC-007**: PowerShell scheduler scripts can register, verify, and remove the orchestrator from Windows Task Scheduler in under 30 seconds.
- **SC-008**: All orchestrator events produce audit log entries within 1 second of occurrence.

## Assumptions

- All three watchers (Gmail, WhatsApp, LinkedIn) are implemented as async classes inheriting from `BaseWatcher` with a standard `run()` method.
- The Email MCP server pipeline (gmail_client, approval, rate_limiter, logging_utils) is fully functional from feature 001.
- The vault folder structure and frontmatter conventions are already established.
- Windows is the primary deployment platform (PowerShell scripts target Windows Task Scheduler).
- The orchestrator runs in a single process using async concurrency (no multiprocessing).
- Environment variables are loaded from `config/.env`.
- Watchers that are not yet fully implemented (WhatsApp, LinkedIn) can be gracefully skipped without affecting the orchestrator.

## Scope Boundaries

**In Scope:**
- Orchestrator process management (start, stop, restart watchers)
- Action executor for `vault/Approved/` files
- Dashboard generation at `vault/Dashboard.md`
- Watchdog health monitoring with restart logic
- PowerShell scripts for Windows Task Scheduler
- Lock file for single-instance enforcement
- Graceful shutdown on Ctrl+C
- DEV_MODE respect for all actions
- Logging all orchestrator events

**Out of Scope:**
- Web UI or API for orchestrator management
- Remote monitoring or alerting (email/SMS notifications)
- Multi-machine orchestration or distributed processing
- Custom watcher plugin system (watchers are hard-coded for now)
- Daily briefing generation logic (separate future feature)
- Cloud deployment or containerization
- Mobile push notifications for approvals
- Orchestrator configuration hot-reload (requires restart for config changes)
