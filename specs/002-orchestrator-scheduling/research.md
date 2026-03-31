# Research: Orchestrator + Scheduling

**Feature**: `002-orchestrator-scheduling` | **Date**: 2026-02-18

## R1: asyncio Task Management on Windows

**Decision**: Use `asyncio.create_task()` for concurrency and `try/except KeyboardInterrupt` for shutdown.

**Rationale**: Windows does not support `loop.add_signal_handler(signal.SIGTERM, ...)` — it raises `NotImplementedError`. However, `KeyboardInterrupt` (Ctrl+C) is reliably caught by `asyncio.run()` on Windows. We wrap the main `asyncio.run()` call in a try/except block, and in the except handler we cancel all tasks and await their cleanup.

**Alternatives considered**:
- `signal.signal(SIGINT, handler)` — works but less clean with asyncio event loop integration
- Third-party library (`trio`, `anyio`) — adds dependency; `asyncio` is sufficient for our use case
- `multiprocessing` — overkill for 3 lightweight watchers; adds complexity

## R2: Watcher Instance Creation Pattern

**Decision**: Import each watcher class inside a `try/except ImportError` block. Instantiate with parameters from `.env`. Skip unavailable watchers.

**Rationale**: The Gmail watcher requires `google-api-python-client`, WhatsApp/LinkedIn require `playwright`. Not all dependencies will be installed. Lazy imports prevent startup crashes.

**Alternatives considered**:
- Plugin system with dynamic discovery — over-engineered for 3 known watchers
- Configuration file listing enabled watchers — adds config complexity; import-try is simpler and self-documenting

**Existing watcher constructors** (all take consistent params):
```
GmailWatcher(vault_path, credentials_path, token_path, check_interval, gmail_config, dry_run, dev_mode)
WhatsAppWatcher(vault_path, session_path, check_interval, keywords, headless, dry_run, dev_mode)
LinkedInWatcher(vault_path, session_path, check_interval, keywords, headless, dry_run, dev_mode)
```

All inherit from `BaseWatcher` and expose `async run()`.

## R3: Lock File Strategy

**Decision**: Write PID to `config/.orchestrator.lock` on startup. Check if existing PID is alive before overwriting.

**Rationale**: Prevents duplicate orchestrator instances which would cause duplicate action executions and watcher conflicts. PID check handles stale lock files from crashes.

**Implementation**:
- On startup: if lock file exists, read PID, check `os.kill(pid, 0)` (signal 0 = alive check on Windows via `psutil` or `ctypes`)
- Simpler alternative: use `os.getpid()` check — if the PID doesn't exist, overwrite the lock
- On shutdown: delete lock file in finally block

**Alternatives considered**:
- `fcntl.flock()` — not available on Windows
- Named mutex via `ctypes` — platform-specific, fragile
- TCP port binding — adds network dependency

## R4: Action Executor Dispatch Pattern

**Decision**: Dictionary-based dispatch mapping `type` string to handler coroutines.

**Rationale**: Clean, extensible pattern. Adding a new action type requires one dict entry and one handler method. The `type` field is already standardized in approval file frontmatter.

**Dispatch map**:
```python
HANDLERS = {
    "email_send": _handle_email_send,
    "email_reply": _handle_email_reply,
    "linkedin_post": _handle_linkedin_post,
}
```

**For email actions**, reuse the existing pipeline:
1. `GmailClient().authenticate()` (token refresh)
2. `RateLimiter().check()` (rate limit)
3. `GmailClient().send_message(to, subject, body)` or `.reply_to_thread(thread_id, body)`
4. `RateLimiter().record_send()`
5. `consume_approval(path, vault_path)` (move to Done)
6. `log_action(...)` (audit trail)

## R5: Dashboard Rendering

**Decision**: Pure function that generates markdown string from a state snapshot. Written atomically via temp file + `os.replace()`.

**Rationale**: Pure function is easy to test. Atomic write prevents Obsidian from reading partial files. `os.replace()` is atomic on Windows for same-volume operations.

**Dashboard sections**:
1. Header with last update timestamp and DEV_MODE badge
2. Watcher status table (name, status, uptime, restart count, last error)
3. Vault folder counts table
4. Recent errors (last 5)

## R6: Windows Task Scheduler

**Decision**: PowerShell scripts using `Register-ScheduledTask` cmdlet.

**Rationale**: Native Windows approach, no third-party tools needed. Task Scheduler handles logon triggers, crash restarts, and daily triggers natively.

**Scripts**:
- `start_all.ps1` — starts orchestrator as foreground process (or `-Background` switch for background)
- `stop_all.ps1` — finds orchestrator process by lock file PID and stops it
- `setup_scheduler.ps1` — registers scheduled task with logon trigger + restart on failure

**Alternatives considered**:
- `nssm` (Non-Sucking Service Manager) — third-party dependency
- Python `schedule` library — doesn't survive system restarts
- Windows Service via `pywin32` — much more complex, overkill for single-user system
