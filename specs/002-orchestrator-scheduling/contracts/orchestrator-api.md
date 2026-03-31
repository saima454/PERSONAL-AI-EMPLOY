# Internal API Contracts: Orchestrator

**Feature**: `002-orchestrator-scheduling` | **Date**: 2026-02-18

## Orchestrator Class

```python
class Orchestrator:
    """Main orchestrator - coordinates watchers, action executor, and dashboard."""

    def __init__(self, config: OrchestratorConfig) -> None: ...
    async def run(self) -> None:
        """Main entry point. Acquires lock, starts all subsystems, blocks until shutdown."""
    async def shutdown(self) -> None:
        """Cancel all tasks and release lock. Called on KeyboardInterrupt."""
```

**Lifecycle**: `__init__` → `run()` (blocks) → `shutdown()` (on Ctrl+C or error)

## WatcherTask Class

```python
class WatcherTask:
    """Supervised wrapper for a BaseWatcher with health monitoring."""

    def __init__(self, name: str, watcher: BaseWatcher, max_restarts: int = 3) -> None: ...
    async def run_supervised(self) -> None:
        """Run watcher in a loop with crash recovery. Sets status accordingly."""
    async def cancel(self) -> None:
        """Gracefully stop the watcher task."""

    # Properties
    @property
    def status(self) -> WatcherStatus: ...
    @property
    def info(self) -> WatcherInfo: ...
```

**Contract**: `run_supervised()` MUST:
- Set status to `running` when watcher starts
- Catch all exceptions from `watcher.run()`
- Set status to `error` on crash, increment `restart_count`
- Wait `2^restart_count` seconds before restart (exponential backoff)
- Set status to `failed` when `restart_count >= max_restarts`
- Log every crash and restart via `log_action()`

## ActionExecutor Class

```python
class ActionExecutor:
    """Polls vault/Approved/ and dispatches approved actions."""

    def __init__(self, config: OrchestratorConfig) -> None: ...
    async def run(self) -> None:
        """Polling loop - scans Approved folder every check_interval seconds."""
    async def process_file(self, file_path: Path) -> bool:
        """Process a single approval file. Returns True on success."""
```

**Contract**: `process_file()` MUST:
- Read frontmatter from the file
- Validate `status == "approved"` and `type` is recognized
- If DEV_MODE: log the action, move to Done with `[DEV_MODE]` note, return True
- If not DEV_MODE: dispatch to handler, on success move to Done, on failure leave in place
- Return True on success, False on failure
- Never raise exceptions (all errors caught and logged)

**Handler signatures**:
```python
async def _handle_email_send(self, path: Path, fm: dict) -> None:
    """Send email using GmailClient. Rate-limited."""
async def _handle_email_reply(self, path: Path, fm: dict) -> None:
    """Reply to thread using GmailClient. Rate-limited."""
async def _handle_linkedin_post(self, path: Path, fm: dict) -> None:
    """Placeholder - logs 'not implemented' warning."""
```

## Dashboard Functions

```python
@dataclass
class DashboardState:
    watchers: list[WatcherInfo]
    vault_counts: dict[str, int]
    dev_mode: bool
    last_update: str
    uptime_seconds: int
    errors: list[str]

def render_dashboard(state: DashboardState) -> str:
    """Pure function: state → markdown string."""

def count_vault_files(vault_path: str | Path) -> dict[str, int]:
    """Count .md files in each vault subfolder."""

async def write_dashboard(vault_path: str | Path, content: str) -> None:
    """Write dashboard to temp file, then atomically rename."""
```

**Contract**: `render_dashboard()` MUST:
- Return valid markdown
- Include DEV_MODE badge if active
- Include watcher status table
- Include vault folder counts
- Include last update timestamp
- Include recent errors (max 5)

## Lock File Functions

```python
def acquire_lock(lock_path: str | Path) -> bool:
    """Write PID to lock file. Returns False if another instance is running."""

def release_lock(lock_path: str | Path) -> None:
    """Delete the lock file."""

def is_process_alive(pid: int) -> bool:
    """Check if a process with given PID exists."""
```

## CLI Entry Point

```python
# backend/orchestrator/__main__.py
def main() -> None:
    """Parse args, load config, run orchestrator."""
    # Supports: --dry-run
    # Loads: config/.env
    # Runs: asyncio.run(Orchestrator(config).run())
```

**Invocation**: `python -m backend.orchestrator` or `uv run python -m backend.orchestrator`
