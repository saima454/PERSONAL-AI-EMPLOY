# Skill: Error Recovery & Graceful Degradation

> **Constitution Principle III**: Skills are the atomic units of AI capability. This SKILL.md is the authoritative reference for how the Personal AI Employee handles errors, partial failures, and degraded operating conditions.

---

## Overview

The AI Employee operates as a distributed, multi-component system. Any individual component may fail without bringing down the entire system. This skill documents the complete error taxonomy, recovery strategies by component, and the system-level behaviors that ensure graceful degradation.

**Core philosophy**: Fail loud, degrade gracefully, never auto-retry payments.

---

## Error Taxonomy

### Category 1: Transient Errors (Auto-Retry)
Errors caused by temporary external conditions. Safe to retry with backoff.

| Error Type | Examples | Max Retries | Backoff |
|------------|----------|-------------|---------|
| Network timeout | `TimeoutError`, `ConnectionError` | 3 | Exponential (2^n, cap 60s) |
| API rate limit | HTTP 429 | 3 | Exponential (2^n, cap 60s) |
| Service unavailable | HTTP 503 | 3 | Fixed 30s |
| Gmail quota | `HttpError 429` | 3 | Exponential |

### Category 2: Auth Errors (Escalate Immediately)
Authentication failures. Retrying without credential refresh is pointless.

| Error Type | Examples | Action |
|------------|----------|--------|
| Token expired | HTTP 401 | Refresh token → 1 retry |
| Token invalid | `InvalidCredentials` | Log + halt watcher |
| Permission denied | HTTP 403 | Log + escalate to operator |
| File not found | Missing credentials.json | Halt watcher, log startup error |

### Category 3: Data Errors (Skip and Continue)
Malformed or unexpected data. The system skips the problematic item and continues.

| Error Type | Examples | Action |
|------------|----------|--------|
| Parse failure | Invalid YAML frontmatter | Log warning, skip file |
| Unicode decode | Corrupt vault file | Log warning, skip file |
| Schema mismatch | Missing required field | Log warning, use defaults |
| DOM not found | WhatsApp selector changed | Log warning, return empty list |

### Category 4: Fatal Errors (Halt Component)
Unrecoverable failures that require human intervention.

| Error Type | Examples | Action |
|------------|----------|--------|
| Crash loop | Restart count > max_restarts | Mark FAILED, notify via vault |
| Payment attempt error | Any error during payment | NEVER retry, log and halt |
| Emergency stop | `vault/STOP_RALPH` present | Halt all Ralph loops |
| Out of memory | `MemoryError` | Halt all, log alert |

---

## Component-Specific Recovery Behaviors

### Orchestrator / Watchdog (`backend/orchestrator/watchdog.py`)

The watchdog is the **primary resilience layer**. It supervises all watcher tasks independently.

**Restart policy:**
```
Crash detected
  → restart_count < max_restarts (default: 3)?
      YES → sleep(min(2^restart_count, 60))  ← exponential backoff, 60s cap
           → restart watcher
      NO  → mark status=FAILED
           → write failure record to vault/Logs/errors/
           → other watchers continue unaffected
```

**Key behaviors:**
- Each watcher runs in an independent asyncio task — one crash never affects others
- `asyncio.CancelledError` on shutdown is handled cleanly (not counted as a crash)
- Status transitions: `starting → running → restarting → failed`
- Backoff sleeps are cancellable (catch `CancelledError` during sleep)

**What happens when a watcher crashes permanently:**
- System continues with remaining watchers
- Operator must restart the process or fix the underlying error
- No automatic resurrection after FAILED state

### Gmail Watcher (`backend/watchers/gmail_watcher.py`)

**Three-tier error handling:**

**Tier 1 — Per-request retry (inside `_fetch_messages_with_retry`):**
```python
for attempt in range(3):
    try:
        return api.list(...)
    except HttpError as e:
        if e.status == 429:           # Rate limit
            sleep(2**attempt * 10)    # 10s, 20s, 40s
        elif e.status == 401:         # Auth expired
            refresh_token()           # Refresh and retry
        elif e.status == 403:         # Permission denied
            raise                     # Do NOT retry
    except (ConnectionError, TimeoutError):
        sleep(2**attempt * 5)         # 5s, 10s, 20s
```

**Tier 2 — Per-poll-cycle recovery (inside `check_for_updates`):**
- Catches all exceptions from `_fetch_messages_with_retry`
- Increments `_consecutive_errors` counter
- Resets `_backoff_delay` to 0 on success
- Returns `[]` on any error — polling loop continues

**Tier 3 — Watcher-level (watchdog):**
- If `check_for_updates` raises (unexpected), watchdog catches and applies restart policy

**Gmail API unavailable behavior:**
- Returns empty list for that polling cycle
- Next poll attempt at normal interval
- No queue of pending checks (next poll is effectively the retry)
- After 3 consecutive polling errors, `_consecutive_errors` is logged but polling continues

### WhatsApp Watcher (`backend/watchers/whatsapp_watcher.py`)

**Browser automation resilience:**
- Multiple CSS selector strategies with fallback per element
- `try/finally` in browser lifecycle to suppress `TargetClosedError` during shutdown
- Chat processing catches exceptions per-chat; continues to next chat on error
- `_wait_for_chats_to_render()` polls with fixed 1s interval (not exponential)

**Session state handling:**
- `phone_disconnected` or `qr_code_required` states: returns `[]` and continues polling
- Browser crash: watchdog applies restart policy
- WhatsApp session not restored on restart (user must re-scan QR)

**Known limitation**: `_backoff_delay` field is defined but not actively used for sleeping. Fixed-delay polls are used instead.

### Action Executor (`backend/orchestrator/action_executor.py`)

**Payment safety (CRITICAL):**
- Rate limiter enforced before ANY payment action
- Payment actions that hit rate limit: `RuntimeError` raised, logged, NO RETRY
- Payment errors: logged and action file left in `Approved/` for manual review
- **Payments are NEVER automatically retried** — human must re-initiate

**Per-file error isolation:**
```
process_cycle():
  for file in approved_dir:
    try:
      process_action(file)
    except Exception:
      log error
      # File stays in Approved/ for manual review
      continue  # Next file
```

**Malformed file handling:**
- `OSError` or `UnicodeDecodeError` reading file → log warning, skip file
- File remains in directory for manual inspection

**Action handler errors:**
- Exception inside handler → logged as error, action marked failed
- File moved to `Done/` with failure status recorded in frontmatter

### Base Watcher (`backend/watchers/base_watcher.py`)

The base class provides a minimal safety net — the watchdog provides the full resilience.

```python
# Polling loop in base_watcher.py
while not self._stop_event.is_set():
    try:
        await self.check_for_updates()
    except Exception:
        logger.exception("Error in polling cycle")  # Continues polling
    await asyncio.sleep(self.config.poll_interval)
```

**No backoff at base level** — backoff is handled by:
1. The watchdog (restart-level backoff)
2. Each watcher's internal `_fetch_with_retry` (request-level backoff)

### Ralph Wiggum Loop (`backend/ralph_wiggum/ralph_loop.py`)

**Per-iteration timeout** (`asyncio.wait_for`):
- Iteration exceeds `RALPH_ITERATION_TIMEOUT` → `HaltReason.per_iteration_timeout`
- Loop halted cleanly, state persisted, exit code 1

**Total timeout**:
- Loop running longer than `RALPH_TOTAL_TIMEOUT` → `HaltReason.total_timeout_exceeded`
- Checked at the top of each iteration before running Claude

**Emergency stop**:
- `vault/STOP_RALPH` file created → background sentinel detects within 1s
- `HaltReason.emergency_stop` — all active Ralph loops stop

**Max iterations**:
- `current_iteration >= max_iterations` → `HaltReason.max_iterations_reached`
- Prevents infinite loops

**Safety hierarchy** (checked in order):
1. Emergency stop sentinel (`STOP_RALPH` file)
2. Total timeout
3. Max iterations
4. Per-iteration timeout

---

## System-Level Graceful Degradation

### Scenario: Gmail API Goes Down

```
Gmail watcher: fetch fails → returns [] → orchestrator sees no new mail
→ Next poll cycle attempts again
→ System functional; no email processing during outage
→ On recovery: next successful poll picks up unread messages
```

### Scenario: WhatsApp Browser Crash

```
WhatsApp watcher crashes → watchdog detects
→ Restart attempt 1: sleep 2s → restart
→ If crash again: sleep 4s → restart
→ If crash again: sleep 8s → restart
→ After 3 restarts: status=FAILED, logged to vault/Logs/errors/
→ All other watchers continue normally
→ Email and other integrations unaffected
```

### Scenario: Odoo Connection Timeout

```
Odoo action requested
→ Action executor calls Odoo MCP → timeout or connection error
→ Exception caught, action handler returns failure
→ Action file stays in Approved/ with error metadata
→ NEVER auto-retried (Odoo actions may be financial)
→ Operator reviews and re-initiates if appropriate
```

### Scenario: Claude Code Subprocess Unavailable (Ralph Loop)

```
RalphLoop._call_claude() fails (subprocess error)
→ HaltReason.subprocess_error recorded in state file
→ Ralph loop halted, exit code 1
→ Orchestrator marks task with ralph_halt_reason in frontmatter
→ Task stays visible for operator review
```

### Scenario: All Watchers Failed

```
All watchers reach FAILED state
→ Orchestrator main loop still running (orchestrator.run() keeps its tasks alive)
→ Action executor continues processing Approved/ items
→ CEO briefing scheduler continues
→ System degrades to "outbox only" mode
→ No new data perception; existing approvals still execute
```

---

## Monitoring & Observability

### Vault Error Logs

All errors are written to `vault/Logs/errors/` with structured JSON:
```json
{
  "timestamp": "2026-02-25T10:00:00Z",
  "component": "gmail_watcher",
  "correlation_id": "abc123",
  "error_type": "HttpError",
  "message": "Rate limit exceeded",
  "restart_count": 0,
  "action": "retry_with_backoff"
}
```

### Watchdog Status Tracking

Watcher statuses are tracked in memory and logged:
- `starting` → `running` → `restarting` → `failed`

### Ralph Wiggum State Files

`vault/ralph_wiggum/RW_*.md` records every iteration outcome including errors, timeouts, and halt reasons with full timestamps.

---

## Emergency Procedures

### Stop All Ralph Loops Immediately
```bash
touch vault/STOP_RALPH
```
The sentinel monitor detects this within 1 second and halts all active loops.

### Restart a Failed Watcher
Failed watchers do not auto-resurrect. Restart the orchestrator:
```bash
uv run python main.py  # or Ctrl+C and relaunch
```

### Recover from Stuck Approved Action
If an action file is stuck in `Approved/` due to repeated errors:
1. Review the file's frontmatter for error metadata
2. Move to `Rejected/` if action should be cancelled
3. Fix the underlying issue, then move back to `Approved/` to retry

### Clear Emergency Stop
```bash
rm vault/STOP_RALPH
```

---

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RALPH_MAX_ITERATIONS` | `10` | Max iterations per Ralph loop |
| `RALPH_ITERATION_TIMEOUT` | `300` | Per-iteration timeout (seconds) |
| `RALPH_TOTAL_TIMEOUT` | `3600` | Total loop timeout (seconds) |
| `MAX_RESTART_ATTEMPTS` | `3` | Watchdog max restarts per watcher |
| `DEV_MODE` | `true` | Prevents real external actions |

---

## Audit Evidence

This skill was generated from a full code audit conducted 2026-02-25. Files audited:

| File | Retry | Backoff | Error Types |
|------|-------|---------|-------------|
| `base_watcher.py` | No | No | Generic Exception |
| `gmail_watcher.py` | Yes (3x) | Yes (2^n, 60s cap) | HttpError, ConnectionError, TimeoutError |
| `whatsapp_watcher.py` | Partial (DOM) | No (field unused) | Generic Exception |
| `watchdog.py` | Yes (3x) | Yes (2^n, 60s cap) | CancelledError, generic |
| `action_executor.py` | No | No | OSError, UnicodeDecodeError, generic |
| `ralph_loop.py` | No (halt) | N/A | TimeoutError, subprocess error |

---

*Constitution Principle VI: All errors are logged. Principle VII: Graceful degradation over crash propagation.*
