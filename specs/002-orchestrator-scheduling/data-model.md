# Data Model: Orchestrator + Scheduling

**Feature**: `002-orchestrator-scheduling` | **Date**: 2026-02-18

## Entities

### OrchestratorConfig

Configuration loaded from environment variables at startup.

| Field | Type | Default | Source |
|-------|------|---------|--------|
| vault_path | str | `"./vault"` | `VAULT_PATH` |
| check_interval | int | `30` | `ORCHESTRATOR_CHECK_INTERVAL` |
| dashboard_interval | int | `300` | `ORCHESTRATOR_DASHBOARD_UPDATE_INTERVAL` |
| max_restart_attempts | int | `3` | `ORCHESTRATOR_MAX_RESTART_ATTEMPTS` |
| dev_mode | bool | `true` | `DEV_MODE` |
| dry_run | bool | `false` | `DRY_RUN` |
| lock_file_path | str | `"config/.orchestrator.lock"` | hardcoded |
| log_level | str | `"INFO"` | `LOG_LEVEL` |

### WatcherStatus (Enum)

Represents the lifecycle state of a managed watcher task.

| Value | Description |
|-------|-------------|
| `pending` | Watcher created but not yet started |
| `running` | Watcher task is active and polling |
| `stopped` | Watcher was gracefully shut down |
| `error` | Watcher crashed, restart pending |
| `failed` | Watcher exceeded max restarts, permanently down |

### WatcherTask

Managed wrapper around a `BaseWatcher` with health tracking.

| Field | Type | Description |
|-------|------|-------------|
| name | str | Human-readable name (e.g., "Gmail", "WhatsApp", "LinkedIn") |
| watcher | BaseWatcher | The underlying watcher instance |
| task | asyncio.Task or None | The running asyncio task |
| status | WatcherStatus | Current lifecycle state |
| restart_count | int | Number of restarts since last clean start |
| max_restarts | int | Maximum allowed restarts (from config) |
| last_error | str or None | Last exception message |
| started_at | str or None | ISO 8601 timestamp of last start |
| stopped_at | str or None | ISO 8601 timestamp of last stop/crash |

**State Transitions**:
```
pending → running    (task started successfully)
running → error      (unhandled exception in watcher.run())
error → running      (restart succeeded, restart_count < max)
error → failed       (restart_count >= max_restarts)
running → stopped    (graceful shutdown via cancel)
failed → (terminal)  (no further transitions)
```

### DashboardState

Snapshot of the orchestrator's current state, used to render `Dashboard.md`.

| Field | Type | Description |
|-------|------|-------------|
| watchers | list[WatcherInfo] | Status of each managed watcher |
| vault_counts | dict[str, int] | File count per vault subfolder |
| dev_mode | bool | Whether DEV_MODE is active |
| last_update | str | ISO 8601 timestamp of this snapshot |
| uptime_seconds | int | Seconds since orchestrator started |
| errors | list[str] | Recent error messages (last 5) |

### WatcherInfo (for dashboard)

Lightweight view of a WatcherTask for dashboard rendering.

| Field | Type | Description |
|-------|------|-------------|
| name | str | Watcher name |
| status | str | Current status string |
| restart_count | int | Number of restarts |
| last_error | str or None | Last error message (truncated to 100 chars) |
| started_at | str or None | When the watcher last started |

### Lock File Format

Plain text file at `config/.orchestrator.lock`.

```
PID: 12345
STARTED: 2026-02-18T09:00:00Z
```

### Approval File Frontmatter (existing, for reference)

Files in `vault/Approved/` that the action executor processes.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| type | str | yes | Action type: `email_send`, `email_reply`, `linkedin_post` |
| status | str | yes | Must be `"approved"` |
| to | str | for email_send | Recipient email address |
| subject | str | for email_send | Email subject line |
| thread_id | str | for email_reply | Gmail thread ID to reply to |
| created | str | yes | ISO 8601 creation timestamp |

### Audit Log Entry (orchestrator events)

Appended to `vault/Logs/actions/<date>.json` via existing `log_action()`.

| Field | Type | Description |
|-------|------|-------------|
| timestamp | str | ISO 8601 UTC |
| correlation_id | str | UUID v4 for tracing |
| actor | str | `"orchestrator"`, `"action_executor"`, or `"watchdog"` |
| action_type | str | `"start"`, `"stop"`, `"watcher_crash"`, `"watcher_restart"`, `"action_executed"`, `"action_failed"` |
| target | str | Watcher name or approval file path |
| result | str | `"success"` or `"failure"` |
| parameters | dict | Additional context (error message, restart count, etc.) |

## Vault Folder Structure (for dashboard counts)

The dashboard counts `.md` files in these folders:

| Folder | Purpose |
|--------|---------|
| `vault/Inbox/` | Raw incoming items |
| `vault/Needs_Action/` | Items requiring processing |
| `vault/Plans/` | Documented plans |
| `vault/Pending_Approval/` | Awaiting human review |
| `vault/Approved/` | Ready for execution |
| `vault/Rejected/` | Declined with reason |
| `vault/Done/` | Completed actions |
