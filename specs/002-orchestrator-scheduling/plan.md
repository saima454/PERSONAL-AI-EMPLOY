# Implementation Plan: Orchestrator + Scheduling

**Branch**: `002-orchestrator-scheduling` | **Date**: 2026-02-18 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-orchestrator-scheduling/spec.md`

## Summary

Build the master Orchestrator that starts all watchers as concurrent async tasks, monitors their health with automatic restart, watches `vault/Approved/` for action files and executes them via the existing Email MCP pipeline, renders live status to `vault/Dashboard.md`, and provides PowerShell scripts for Windows Task Scheduler integration. Uses Python 3.13+ `asyncio` in a single process, reuses existing `BaseWatcher`, `GmailClient`, `approval.py`, and `logging_utils.py`.

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: `asyncio` (stdlib), `dotenv`, existing `backend.watchers.*`, existing `backend.mcp_servers.gmail_client`, existing `backend.utils.*`
**Storage**: File-based (Obsidian vault markdown files + JSON audit logs)
**Testing**: pytest + pytest-asyncio
**Target Platform**: Windows 11, local execution
**Project Type**: Single backend service (long-running async orchestrator)
**Performance Goals**: Startup < 5s (SC-001), crash detection < 60s (SC-002), action execution < 30s (SC-003)
**Constraints**: Windows (no POSIX signals — use `KeyboardInterrupt`), stdout for user-facing logs, DEV_MODE default true
**Scale/Scope**: Single user, single machine, 3 watchers max, ~10 approval files/day

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | How Addressed |
|---|-----------|--------|---------------|
| I | Local-First & Privacy | PASS | All data stays in local vault. No cloud services. Creds in `config/` (gitignored). Logs redact sensitive data via existing `logging_utils`. |
| II | Separation of Concerns | PASS | Orchestrator is a COORDINATION layer — it starts watchers (PERCEPTION) and dispatches to MCP pipelines (ACTION). It does NOT reason about email content. |
| III | Agent Skills | PASS | `skills/orchestrator/SKILL.md` defines the skill. Orchestrator coordinates existing skills. |
| IV | HITL Safety | PASS | Action executor only processes files in `vault/Approved/` (human-approved). Never auto-approves. Uses existing `find_approval()` + `consume_approval()`. |
| V | DEV_MODE Safety | PASS | Respects `DEV_MODE` env var. When true, action executor logs actions but does not execute them. Dashboard shows DEV_MODE status prominently. |
| VI | Rate Limiting | PASS | Action executor uses existing `RateLimiter` for email sends. Rate limits from `config/rate_limits.json`. |
| VII | Logging & Auditability | PASS | All orchestrator events → `vault/Logs/actions/` via existing `log_action()`. Watcher crashes, restarts, action executions all logged with correlation IDs. |
| VIII | Error Handling | PASS | Watchdog restarts crashed watchers (max 3 attempts, exponential backoff). Action executor handles failures gracefully (file stays in Approved). Lock file prevents duplicate instances. |

**Gate Result**: ALL PASS — proceed to implementation.

**Post-Phase 1 Re-check**: All principles remain satisfied. No violations introduced.

## Project Structure

### Documentation (this feature)

```text
specs/002-orchestrator-scheduling/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete)
├── data-model.md        # Phase 1 output (complete)
├── quickstart.md        # Phase 1 output (complete)
├── contracts/
│   └── orchestrator-api.md  # Phase 1 output (internal API)
└── tasks.md             # Phase 2 output (created by /sp.tasks)
```

### Source Code (repository root)

```text
backend/
├── orchestrator/
│   ├── __init__.py              # Package init + version
│   ├── __main__.py              # Entry point: python -m backend.orchestrator
│   ├── orchestrator.py          # Main Orchestrator class - starts watchers, runs loops
│   ├── action_executor.py       # Polls vault/Approved/, dispatches actions
│   ├── dashboard.py             # Renders vault/Dashboard.md from current state
│   └── watchdog.py              # WatcherTask wrapper with health tracking + restart logic
├── watchers/                    # [EXISTING] Perception layer
│   ├── base_watcher.py          # [EXISTING] BaseWatcher ABC
│   ├── gmail_watcher.py         # [EXISTING] GmailWatcher
│   ├── whatsapp_watcher.py      # [EXISTING] WhatsAppWatcher
│   └── linkedin_watcher.py      # [EXISTING] LinkedInWatcher
├── mcp_servers/                 # [EXISTING] Action layer
│   ├── gmail_client.py          # [EXISTING] GmailClient (send_message, reply_to_thread)
│   ├── approval.py              # [EXISTING] find_approval, consume_approval
│   └── rate_limiter.py          # [EXISTING] RateLimiter
└── utils/                       # [EXISTING] Shared utilities
    ├── frontmatter.py           # [EXISTING] extract_frontmatter, update_frontmatter
    ├── logging_utils.py         # [EXISTING] log_action
    ├── timestamps.py            # [EXISTING] now_iso, today_iso
    └── uuid_utils.py            # [EXISTING] correlation_id

skills/
└── orchestrator/
    └── SKILL.md                 # Orchestrator skill definition

scripts/
├── start_all.ps1                # Start orchestrator (foreground or background)
├── stop_all.ps1                 # Stop running orchestrator
└── setup_scheduler.ps1          # Register with Windows Task Scheduler

config/
├── .env                         # [UPDATE] Add ORCHESTRATOR_* vars
└── .orchestrator.lock           # [RUNTIME] PID lock file (auto-created)

tests/
├── test_orchestrator.py         # Orchestrator lifecycle tests
├── test_action_executor.py      # Action executor dispatch tests
├── test_dashboard.py            # Dashboard rendering tests
└── test_watchdog.py             # Watchdog restart logic tests
```

**Structure Decision**: New modules go in `backend/orchestrator/` as defined by the canonical folder structure. The orchestrator coordinates existing modules — it imports watchers and MCP pipelines, never duplicating their logic. Each concern (orchestration, action dispatch, dashboard, health monitoring) is a separate module following the same separation pattern as `backend/mcp_servers/`.

## Module Design

### `orchestrator.py` — Main Orchestrator

**Responsibility**: Single entry point that creates all subsystems, starts them as async tasks, and manages the event loop lifecycle.

**Key Design**:
- `Orchestrator` class with `async run()` as the main loop
- Constructor takes `config: OrchestratorConfig` dataclass (loaded from env)
- `_start_watchers()` — creates `WatcherTask` for each enabled watcher, launches as `asyncio.Task`
- `_start_action_executor()` — launches `ActionExecutor` as async task
- `_start_dashboard_loop()` — launches periodic dashboard update as async task
- `_acquire_lock()` / `_release_lock()` — PID lock file management
- `_ensure_vault_dirs()` — creates missing vault subdirectories at startup
- Shutdown: `try/except KeyboardInterrupt` catches Ctrl+C, cancels all tasks, awaits cleanup
- Each watcher is loaded with `try/except ImportError` to skip unavailable ones

**Dependencies**: `watchdog.WatcherTask`, `action_executor.ActionExecutor`, `dashboard.render_dashboard`, `backend.utils.logging_utils`

### `watchdog.py` — Watcher Health Monitor

**Responsibility**: Wraps each `BaseWatcher` in a managed task with crash detection, restart logic, and status tracking.

**Key Design**:
- `WatcherTask` dataclass/class tracking: `name`, `watcher` instance, `task` (asyncio.Task), `status` (enum: running/stopped/error/failed), `restart_count`, `max_restarts`, `last_error`, `started_at`
- `async run_supervised()` — runs `watcher.run()` in a loop, catches exceptions, increments restart counter, applies exponential backoff (1s, 2s, 4s)
- When `restart_count >= max_restarts` → set status to `failed`, stop retrying
- Exposes `cancel()` for graceful shutdown
- Status is readable by the dashboard renderer

### `action_executor.py` — Approved Action Dispatcher

**Responsibility**: Polls `vault/Approved/` for new files, reads frontmatter to determine action type, dispatches to the appropriate handler, moves completed files to `vault/Done/`.

**Key Design**:
- `ActionExecutor` class with `async run()` polling loop
- `_scan_approved()` — lists `.md` files in `vault/Approved/`, returns list of `(path, frontmatter)` tuples
- `_dispatch(path, frontmatter)` — routes by `type` field to handler methods
- `_handle_email_send(path, fm)` — uses `GmailClient.send_message()` via `asyncio.to_thread()`, with `RateLimiter` check, then `consume_approval()`
- `_handle_email_reply(path, fm)` — uses `GmailClient.reply_to_thread()` via `asyncio.to_thread()`
- `_handle_linkedin_post(path, fm)` — placeholder, logs "not implemented" warning
- Unknown types → log warning, leave file in place
- On failure → leave file in `vault/Approved/`, log error
- DEV_MODE → log action, move to Done with `[DEV_MODE]` note

### `dashboard.py` — Dashboard Renderer

**Responsibility**: Generates `vault/Dashboard.md` from current orchestrator state.

**Key Design**:
- `render_dashboard(state: DashboardState) -> str` — pure function, returns markdown string
- `DashboardState` dataclass: `watchers: list[WatcherStatus]`, `vault_counts: dict[str, int]`, `dev_mode: bool`, `last_update: str`, `errors: list[str]`
- `count_vault_files(vault_path) -> dict[str, int]` — counts `.md` files in each vault subfolder
- `async write_dashboard(vault_path, state)` — writes to temp file, then renames atomically
- Dashboard format: markdown table for watchers, folder counts, timestamps, error log

### `__main__.py` — CLI Entry Point

**Responsibility**: Parse args, load config from env, create Orchestrator, run it.

**Key Design**:
- `python -m backend.orchestrator` entry point
- Loads `config/.env` via `dotenv`
- Supports `--dry-run` flag
- Constructs `OrchestratorConfig` from env vars
- Calls `asyncio.run(orchestrator.run())`

## Dependency Graph

```
__main__.py
└── orchestrator.py
    ├── watchdog.py
    │   └── backend.watchers.base_watcher.BaseWatcher
    │       ├── backend.watchers.gmail_watcher.GmailWatcher
    │       ├── backend.watchers.whatsapp_watcher.WhatsAppWatcher
    │       └── backend.watchers.linkedin_watcher.LinkedInWatcher
    ├── action_executor.py
    │   ├── backend.mcp_servers.gmail_client.GmailClient
    │   ├── backend.mcp_servers.approval (find_approval, consume_approval)
    │   ├── backend.mcp_servers.rate_limiter.RateLimiter
    │   └── backend.utils.frontmatter (extract_frontmatter)
    ├── dashboard.py
    │   └── backend.utils.timestamps (now_iso)
    └── backend.utils.logging_utils (log_action)
```

## Env Additions

```
# Add to config/.env
ORCHESTRATOR_CHECK_INTERVAL=30
ORCHESTRATOR_DASHBOARD_UPDATE_INTERVAL=300
ORCHESTRATOR_MAX_RESTART_ATTEMPTS=3
```

## Complexity Tracking

No constitution violations to justify. All gates pass cleanly.

## Risks & Follow-ups

1. **Windows signal handling**: `asyncio` on Windows does not support `add_signal_handler()`. Mitigation: use `try/except KeyboardInterrupt` around `asyncio.run()`, which works reliably on Windows.
2. **Watcher import failures**: WhatsApp and LinkedIn watchers depend on Playwright, which may not be installed. Mitigation: each watcher is imported inside a `try/except ImportError` block; unavailable watchers are skipped with a warning.
3. **Lock file stale PID**: If the orchestrator crashes hard (kill -9), the lock file persists with a dead PID. Mitigation: on startup, check if the PID in the lock file is still alive; if not, overwrite it.
4. **Atomic file rename on Windows**: `os.replace()` is atomic on Windows for same-volume renames. Dashboard writes use this for safe Obsidian updates.
