# Tasks: Orchestrator + Scheduling

**Input**: Design documents from `/specs/002-orchestrator-scheduling/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Included — spec acceptance criteria explicitly require "Tests for orchestrator logic".

**Organization**: Tasks grouped by user story (P1-P5) for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1-US5)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, package structure, configuration

- [X] T001 Create orchestrator package structure with `__init__.py` in `backend/orchestrator/__init__.py`
- [X] T002 [P] Add ORCHESTRATOR_* environment variables to `config/.env`
- [X] T003 [P] Create orchestrator skill definition in `skills/orchestrator/SKILL.md`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data types and utilities that ALL user stories depend on

- [X] T004 Implement `WatcherStatus` enum and `WatcherInfo` dataclass in `backend/orchestrator/watchdog.py`
- [X] T005 [P] Implement `OrchestratorConfig` dataclass in `backend/orchestrator/orchestrator.py`
- [X] T006 [P] Implement lock file functions (`acquire_lock`, `release_lock`, `is_process_alive`) in `backend/orchestrator/orchestrator.py`

**Checkpoint**: Foundation ready — all data types and utilities available for user story implementation

---

## Phase 3: User Story 1 — Single Command Startup (Priority: P1) MVP

**Goal**: User runs `python -m backend.orchestrator` and all watchers start as concurrent async tasks with status output.

**Independent Test**: Run the orchestrator, verify it prints startup status for each watcher and stays running. Ctrl+C shuts down gracefully.

### Implementation for User Story 1

- [X] T007 [US1] Implement `WatcherTask.run_supervised()` core loop (start watcher, catch exceptions, set status) in `backend/orchestrator/watchdog.py`
- [X] T008 [US1] Implement `WatcherTask.cancel()` for graceful shutdown in `backend/orchestrator/watchdog.py`
- [X] T009 [US1] Implement `Orchestrator.__init__()` and `_ensure_vault_dirs()` in `backend/orchestrator/orchestrator.py`
- [X] T010 [US1] Implement `Orchestrator._start_watchers()` with try/except ImportError per watcher in `backend/orchestrator/orchestrator.py`
- [X] T011 [US1] Implement `Orchestrator.run()` main loop with lock acquisition in `backend/orchestrator/orchestrator.py`
- [X] T012 [US1] Implement `Orchestrator.shutdown()` — cancel all tasks, release lock in `backend/orchestrator/orchestrator.py`
- [X] T013 [US1] Implement CLI entry point with arg parsing and asyncio.run() in `backend/orchestrator/__main__.py`
- [X] T014 [US1] Add startup and shutdown audit logging via `log_action()` in `backend/orchestrator/orchestrator.py`

**Checkpoint**: Orchestrator starts all available watchers, prints status, Ctrl+C shuts down cleanly

---

## Phase 4: User Story 2 — Automatic Crash Recovery (Priority: P2)

**Goal**: Crashed watchers are detected and restarted automatically with exponential backoff, up to a maximum retry count.

**Independent Test**: Start orchestrator, simulate a watcher crash, verify it restarts and logs the event. After max restarts, verify it marks the watcher as permanently failed.

### Implementation for User Story 2

- [X] T015 [US2] Add exponential backoff restart logic to `WatcherTask.run_supervised()` in `backend/orchestrator/watchdog.py`
- [X] T016 [US2] Implement max restart limit — set status to `failed` after exceeding max in `backend/orchestrator/watchdog.py`
- [X] T017 [US2] Add crash and restart audit logging in `backend/orchestrator/watchdog.py`

**Checkpoint**: Watchers auto-restart on crash with backoff; permanent failure after max restarts

---

## Phase 5: User Story 3 — Approved Action Execution (Priority: P3)

**Goal**: Action executor polls `vault/Approved/`, dispatches actions by type, moves completed files to `vault/Done/`.

**Independent Test**: Place an `email_send` approval file in `vault/Approved/`, verify it gets executed (or DEV_MODE logged) and moved to `vault/Done/`.

### Implementation for User Story 3

- [X] T018 [US3] Implement `ActionExecutor.__init__()` and `_scan_approved()` in `backend/orchestrator/action_executor.py`
- [X] T019 [US3] Implement `ActionExecutor.run()` polling loop in `backend/orchestrator/action_executor.py`
- [X] T020 [US3] Implement `_handle_email_send()` using GmailClient + RateLimiter + consume_approval in `backend/orchestrator/action_executor.py`
- [X] T021 [P] [US3] Implement `_handle_email_reply()` using GmailClient + consume_approval in `backend/orchestrator/action_executor.py`
- [X] T022 [P] [US3] Implement `_handle_linkedin_post()` placeholder (log warning, skip) in `backend/orchestrator/action_executor.py`
- [X] T023 [US3] Implement DEV_MODE handling — log action, move to Done with `[DEV_MODE]` note in `backend/orchestrator/action_executor.py`
- [X] T024 [US3] Implement error handling — leave file in Approved on failure, log error in `backend/orchestrator/action_executor.py`
- [X] T025 [US3] Integrate ActionExecutor into Orchestrator.run() as async task in `backend/orchestrator/orchestrator.py`

**Checkpoint**: Approved files are detected, dispatched by type, executed (or DEV_MODE logged), and moved to Done

---

## Phase 6: User Story 4 — Live Dashboard Updates (Priority: P4)

**Goal**: `vault/Dashboard.md` is periodically updated with watcher statuses, vault folder counts, and system info.

**Independent Test**: Run orchestrator for one dashboard interval, verify `vault/Dashboard.md` has accurate content.

### Implementation for User Story 4

- [X] T026 [P] [US4] Implement `count_vault_files()` in `backend/orchestrator/dashboard.py`
- [X] T027 [P] [US4] Implement `DashboardState` dataclass in `backend/orchestrator/dashboard.py`
- [X] T028 [US4] Implement `render_dashboard()` pure function (generates markdown from state) in `backend/orchestrator/dashboard.py`
- [X] T029 [US4] Implement `write_dashboard()` with atomic temp-file + os.replace in `backend/orchestrator/dashboard.py`
- [X] T030 [US4] Integrate dashboard update loop into Orchestrator.run() as async task in `backend/orchestrator/orchestrator.py`

**Checkpoint**: Dashboard.md shows live watcher statuses, folder counts, DEV_MODE status, timestamps

---

## Phase 7: User Story 5 — Windows Task Scheduler (Priority: P5)

**Goal**: PowerShell scripts to start/stop orchestrator and register it with Windows Task Scheduler.

**Independent Test**: Run setup script, verify scheduled task appears in Task Scheduler with logon trigger.

### Implementation for User Story 5

- [X] T031 [P] [US5] Create start script in `scripts/start_all.ps1`
- [X] T032 [P] [US5] Create stop script in `scripts/stop_all.ps1`
- [X] T033 [US5] Create scheduler setup script in `scripts/setup_scheduler.ps1`

**Checkpoint**: Orchestrator can be registered/removed from Task Scheduler via PowerShell

---

## Phase 8: Tests & Polish

**Purpose**: Test coverage for orchestrator logic, linting, validation

### Tests

- [X] T034 [P] Write unit tests for WatcherTask (status transitions, restart logic, cancel) in `tests/test_watchdog.py`
- [X] T035 [P] Write unit tests for ActionExecutor (dispatch, email_send, DEV_MODE, error handling) in `tests/test_action_executor.py`
- [X] T036 [P] Write unit tests for dashboard (render_dashboard, count_vault_files) in `tests/test_dashboard.py`
- [X] T037 Write integration tests for Orchestrator (startup, shutdown, lock file) in `tests/test_orchestrator.py`

### Polish

- [X] T038 Run `ruff check` and `ruff format` on all new files
- [X] T039 Run `pytest tests/` — verify all tests pass (existing + new)
- [X] T040 Validate quickstart flow — start orchestrator, check dashboard, test action execution

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1 - Startup)**: Depends on Phase 2 — MVP, must complete first
- **Phase 4 (US2 - Recovery)**: Depends on Phase 3 (needs working WatcherTask)
- **Phase 5 (US3 - Actions)**: Depends on Phase 2 only — can run parallel with US1/US2
- **Phase 6 (US4 - Dashboard)**: Depends on Phase 3 (needs WatcherTask.info for status)
- **Phase 7 (US5 - Scheduler)**: Depends on Phase 3 (needs working orchestrator to schedule)
- **Phase 8 (Polish)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (Startup)**: Depends only on Foundational — MVP, no cross-story deps
- **US2 (Recovery)**: Depends on US1 (extends WatcherTask with restart logic)
- **US3 (Actions)**: Depends on Foundational only — independent of US1/US2
- **US4 (Dashboard)**: Depends on US1 (reads WatcherTask status)
- **US5 (Scheduler)**: Depends on US1 (schedules the orchestrator entry point)

### Within Each User Story

- Data types before logic
- Core implementation before integration
- Error handling after happy path
- Logging throughout

### Parallel Opportunities

- T002, T003 can run parallel (different files)
- T005, T006 can run parallel (same file but independent sections)
- T021, T022 can run parallel (independent handler methods)
- T026, T027 can run parallel (independent functions/types)
- T031, T032 can run parallel (independent scripts)
- T034, T035, T036 can ALL run parallel (different test files)

---

## Parallel Example: User Story 3

```bash
# Independent handler implementations can run in parallel:
Task T021: "_handle_email_reply() in action_executor.py"
Task T022: "_handle_linkedin_post() in action_executor.py"

# These depend on T018-T019 (core executor) but not on each other
```

## Parallel Example: Phase 8 Tests

```bash
# All test files can be written in parallel:
Task T034: "tests/test_watchdog.py"
Task T035: "tests/test_action_executor.py"
Task T036: "tests/test_dashboard.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T003)
2. Complete Phase 2: Foundational (T004-T006)
3. Complete Phase 3: US1 - Startup (T007-T014)
4. **STOP and VALIDATE**: Run orchestrator, verify watchers start, Ctrl+C shuts down
5. Demo: Single-command startup of all watchers

### Incremental Delivery

1. Setup + Foundational → Package ready
2. US1 (Startup) → Orchestrator starts watchers → **MVP Demo**
3. US2 (Recovery) → Crashed watchers auto-restart
4. US3 (Actions) → Approved files auto-executed
5. US4 (Dashboard) → Live status in Obsidian
6. US5 (Scheduler) → Runs on system login
7. Tests + Polish → Production-ready

---

## Notes

- Total tasks: **40** (T001-T040)
- Tasks per story: Setup=3, Foundational=3, US1=8, US2=3, US3=8, US4=5, US5=3, Polish=7
- Parallel opportunities: 7 groups identified
- MVP scope: Phases 1-3 (14 tasks) delivers a working orchestrator with single-command startup
- All orchestrator modules reuse existing code (GmailClient, approval, rate_limiter, logging_utils) — no new external dependencies
