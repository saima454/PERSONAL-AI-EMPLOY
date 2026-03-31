---
name: orchestrator
version: 1.0.0
description: |
  COORDINATION layer skill that manages the AI Employee lifecycle. Starts all
  watchers as concurrent async tasks, monitors their health with automatic
  crash recovery, processes approved actions from vault/Approved/, and renders
  a live status dashboard to vault/Dashboard.md.

  TRIGGERS: Use this skill when you need to:
  - Start the AI Employee ("start all watchers", "run the orchestrator")
  - Check system status ("what's the orchestrator doing", "watcher status")
  - Process approved actions ("execute approved emails", "run pending actions")
  - Schedule the AI Employee ("set up auto-start", "register with task scheduler")

  NOTE: The orchestrator respects DEV_MODE. When true, actions are logged but
  not executed against external services.
dependencies:
  - vault-manager
  - email-sender
  - gmail-watcher
permissions:
  - read: vault/Approved/*.md
  - write: vault/Done/*.md
  - write: vault/Dashboard.md
  - write: vault/Logs/actions/*.json
  - read: config/.env
  - write: config/.orchestrator.lock
sensitivity: medium
rate_limits:
  inherited: email (10 sends/hour via email-sender)
---

# Orchestrator Skill

## Decision Tree

```
User request received
├─ "Start" / "Run" → Launch orchestrator via python -m backend.orchestrator
├─ "Status" / "Health" → Read vault/Dashboard.md and report
├─ "Stop" → Run scripts/stop_all.ps1
├─ "Schedule" → Run scripts/setup_scheduler.ps1
└─ "Process actions" → Check vault/Approved/ for pending files
```

## Components

| Module | Purpose |
|--------|---------|
| `backend/orchestrator/orchestrator.py` | Main coordinator — starts watchers, runs loops |
| `backend/orchestrator/watchdog.py` | WatcherTask with health monitoring + restart |
| `backend/orchestrator/action_executor.py` | Polls vault/Approved/, dispatches by type |
| `backend/orchestrator/dashboard.py` | Renders vault/Dashboard.md from state |
| `backend/orchestrator/__main__.py` | CLI entry point |

## HITL Workflow

The orchestrator's action executor processes files that have already been
human-approved (in vault/Approved/). It never auto-approves actions.

```
vault/Needs_Action/ → Human reviews → vault/Approved/ → ActionExecutor → vault/Done/
```

## Safety

- DEV_MODE respected for all action execution
- Lock file prevents duplicate instances
- Max 3 watcher restart attempts before permanent failure
- All events logged to vault/Logs/actions/
