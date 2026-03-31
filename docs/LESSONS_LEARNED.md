# Lessons Learned: Personal AI Employee Hackathon

> Gold Tier submission — 2026-02-25

---

## Overview

This document captures technical insights, design decisions, and hard-won lessons from building the Personal AI Employee system to Gold Tier. It's intended for future reference, team retrospectives, and anyone building similar autonomous agent systems.

---

## 1. Architecture Lessons

### The File System IS the Right Message Bus (for this use case)

**What we did**: Used Markdown files with YAML frontmatter as the communication layer between all components.

**Why it worked**:
- Zero infrastructure (no Redis, no Kafka, no database)
- Human can read and modify state with any text editor
- Obsidian renders it as a beautiful UI for free
- Git provides history, diff, and rollback for free
- Component coupling is zero — they share only file conventions

**When it would fail**:
- High-frequency events (>1/second) — file I/O becomes a bottleneck
- Multi-machine deployment — file system isn't distributed (need a cloud vault)
- Real-time notifications — file polling has inherent latency

**Lesson**: For personal automation workflows, the file system message bus pattern is surprisingly powerful. Don't reach for Kafka when file polling every 30 seconds is fine.

---

### Watchdog Pattern Solves 90% of Reliability Problems

**What we built**: `watchdog.py` supervises each watcher as an independent asyncio task with exponential backoff restarts (max 3, capped at 60s).

**Key insight**: The most important resilience property is **blast radius isolation**. One crashed watcher must not affect others. We achieved this by giving each watcher its own asyncio task with its own try/except loop.

**Exponential backoff formula**:
```python
sleep_time = min(2 ** restart_count, 60)
# Restart 1: sleep 2s
# Restart 2: sleep 4s
# Restart 3: sleep 8s
# Restart 4: sleep 16s (if max_restarts > 4)
```

**Lesson**: Build the watchdog first. Everything else can be iteratively improved — but without supervision, every crash is a user-visible failure.

---

### DEV_MODE is a First-Class Feature, Not a Flag

**What we did**: Made `DEV_MODE=true` the default. Every component checks it before real external actions.

**Critical moment**: During development, WhatsApp watcher was reading real messages. The action executor was calling real Gmail MCP. With `DEV_MODE=true`, we could run the full pipeline without accidentally sending real emails.

**Implementation rule**: The check must be in the action code, not the caller:
```python
# WRONG: caller checks DEV_MODE
if not dev_mode:
    gmail_mcp.send(email)

# RIGHT: MCP server checks DEV_MODE internally
# (so even if caller forgets, real action is blocked)
```

**Lesson**: DEV_MODE is a safety system, not a developer convenience. Treat it like a circuit breaker — always on until explicitly disabled for production.

---

## 2. Claude Code Integration Lessons

### The Ralph Wiggum Pattern: Keeping Claude Iterating

**Problem**: Claude Code defaults to attempting a task once and exiting. Multi-step tasks (filing 50 emails, processing an entire inbox) often require many iterations.

**Solution**: The Ralph Wiggum stop-hook pattern:
1. Register an `onStop` hook in `.claude/settings.json`
2. Hook intercepts Claude's exit attempt
3. Hook checks if the task is actually complete (promise-based or file-based)
4. If incomplete: returns `{"decision": "block", "reason": "Continue working"}` — Claude sees its previous output and continues
5. If complete: returns `{"decision": "approve"}` — exit allowed

**Critical insight**: The hook receives the full `claude_project_dir` in its stdin JSON payload. Use this to find the vault path:
```python
vault_path = Path(hook_data["claude_project_dir"]) / "vault"
```

Do NOT hardcode or guess the vault path — it won't match in tests.

**DEV_MODE simulation bug**: In DEV_MODE, we simulated Claude's output. Initially we output `task.completion_promise` regardless of its value. Tests that used `__NEVER__` as the promise accidentally triggered completion. Fix: only auto-output completion when `completion_promise == "TASK_COMPLETE"`.

---

### Skills-First Design Pays Off

**What we did**: Created `skills/*/SKILL.md` for every capability before writing any code.

**Why it mattered**: When implementing the Ralph Wiggum loop, having `skills/ralph-wiggum/SKILL.md` already written meant Claude Code (and the human developer) had a clear spec for what the skill should do. No ambiguity about triggers, permissions, or state format.

**Unexpected benefit**: Skills documentation forces you to think about error cases, rate limits, and DEV_MODE behavior before you write the code. Bugs caught at documentation time cost nothing.

---

### Claude Code CLI Invocation Pattern

For subprocess-based Ralph loops, we call Claude like this:
```python
cmd = ["claude", "-p", prompt, "--output-format", "json"]
if session_id:
    cmd.extend(["--resume", session_id])
result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True)
```

**Lesson**: `--output-format json` makes parsing Claude's response much more reliable. Always use it for programmatic invocations.

---

## 3. Testing Lessons

### The Vault Path Mismatch Bug (TestStopHook)

**Bug**: 4 of 6 `TestStopHook` tests failed with `assert 'block' == 'approve'`.

**Root cause**: Tests created tasks using `StateManager(tmp_path)`, writing to `tmp_path/ralph_wiggum/`. But the stop hook resolves `vault_path = claude_project_dir/vault = tmp_path/vault`. Different directories → hook found no active tasks → always returned `approve`.

**Fix**: Tests must use the same path resolution as the code:
```python
# WRONG:
state_mgr = StateManager(tmp_path)

# RIGHT (matches hook's path resolution):
vault_path = tmp_path / "vault"
state_mgr = StateManager(vault_path)
```

**Lesson**: When testing code that resolves paths from context (stdin payload, environment), mirror that exact resolution in your tests. Don't assume paths.

---

### TDD With asyncio: Patterns That Work

All async test methods need `@pytest.mark.asyncio`. We used a simple pattern:
```python
@pytest.mark.asyncio
async def test_loop_completes():
    # Use tmp_path fixture for isolation
    # Patch external calls (subprocess.run, asyncio.to_thread)
    # Assert on state files written to tmp_path
```

**Key fixture**: `tmp_path` (pytest builtin). Every test gets a clean temp directory. No test pollution, no file cleanup needed.

**Patching asyncio.to_thread**: We patched this to return canned Claude output:
```python
with patch("backend.ralph_wiggum.ralph_loop.asyncio.to_thread") as mock:
    mock.return_value = mock_claude_output
```

---

### 45/45 Tests: What the Test Suite Covers

| Class | Tests | What It Tests |
|-------|-------|---------------|
| `TestRalphConfig` | 4 | Config validation, env var loading, defaults |
| `TestStateManager` | 8 | YAML read/write, iteration logging, emergency stop detection |
| `TestPromptInjector` | 4 | Prompt building, context injection, truncation |
| `TestFileMovement` | 4 | File-based completion strategy |
| `TestSafetyLimits` | 8 | Max iterations, timeouts, STOP_RALPH sentinel |
| `TestStatus` | 6 | Status aggregation, RalphStatusResult |
| `TestStopHook` | 6 | Hook block/approve decisions, path resolution |
| `TestOrchestratorInteg` | 5 | Orchestrator detecting/processing ralph_loop tasks |

---

## 4. Operational Lessons

### The Obsidian Vault as a Debugging Tool

During development, we could see exactly what the AI was thinking by opening the vault in Obsidian. The Plans/ folder shows every reasoning step. The Logs/ folder shows every action with timestamps and correlation IDs.

**Lesson**: The file-based architecture gives you debugging tools for free. No log aggregation service needed — just open Obsidian.

---

### Rate Limits Must Be Enforced at the Executor, Not the Caller

**Temptation**: Check rate limits before queuing an action.
**Problem**: Race conditions. Two concurrent action processors could both check and both think they're under the limit.

**Solution**: Rate limit check is in `action_executor.py`, not in the watcher or orchestrator:
```python
if not rate_limiter.check_and_consume(action_type):
    raise RuntimeError(f"Rate limit exceeded for {action_type}")
```

**Lesson**: Enforce safety constraints at the execution boundary, not at the planning boundary.

---

### Payment Safety: Never Auto-Retry

Every payment system lesson: **never automatically retry financial transactions**. A network timeout on a payment doesn't mean the payment failed — it might mean you lost the confirmation. Retrying could double-charge.

**Our implementation**:
- Payment actions that fail stay in `Approved/` with error metadata
- No retry logic for payment handlers
- Human must manually review and re-initiate if appropriate

**Lesson**: When in doubt about idempotency, err on the side of "human must review." The cost of a manual review is far less than a double-payment.

---

## 5. What We'd Do Differently

### Add Jitter to Backoff

The current exponential backoff is deterministic. If multiple watchers crash simultaneously (e.g., due to a transient network outage), they all restart at the same time:
```
t=0: all 3 watchers crash
t=2: all 3 watchers restart simultaneously (thundering herd)
t=2: all 3 crash again (same network issue)
t=4: all 3 restart simultaneously (again)
```

**Fix**: Add jitter — `sleep(min(2**n, 60) * random.uniform(0.5, 1.5))`.

### Unified Error Taxonomy From Day One

Each component has its own error handling style. Gmail watcher catches `HttpError`; WhatsApp catches `Exception`; base_watcher catches `Exception`. A unified `RecoverableError` / `FatalError` / `TransientError` hierarchy would make the retry logic more consistent and testable.

### WhatsApp Watcher: Use `_backoff_delay`

The field is defined but never used for sleeping. The exponential backoff logic exists in watchdog.py (supervisor level) but not inside the WhatsApp watcher itself. Adding request-level backoff similar to Gmail watcher would improve resilience to WhatsApp rate limits.

---

## 6. The Hackathon Build Process

### Specify → Plan → Tasks → Implement

We used the SpecKit Plus workflow for every feature:
1. `/sp.specify` — write user stories (technology-agnostic)
2. `/sp.plan` — research + architecture decisions + data model
3. `/sp.tasks` — break down into 30-task executable plans
4. `/sp.implement` — execute all tasks phase by phase

**What worked**: Starting with skills-first (`SKILL.md` before code) caught design issues early. The spec→plan→tasks separation prevented premature optimization.

**What was challenging**: The task granularity. Tasks that seemed small (T010: "Implement `_call_claude()`") could hide significant complexity. Better to over-specify than under-specify task steps.

---

## Conclusion

The Personal AI Employee demonstrates that a thoughtful local-first architecture using Claude Code, file-based messaging, and a skills-driven design can produce a robust autonomous agent system without complex infrastructure. The most important lessons:

1. **Watchdog supervision** is non-negotiable for multi-component reliability
2. **DEV_MODE** must be a first-class safety system, not an afterthought
3. **Vault = message bus** is a surprisingly powerful pattern for personal automation
4. **Skills-first design** catches bugs at documentation time
5. **Never auto-retry payments** — this is a hard rule, not a suggestion
