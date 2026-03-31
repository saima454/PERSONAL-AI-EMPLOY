# Quickstart: Orchestrator + Scheduling

**Feature**: `002-orchestrator-scheduling` | **Date**: 2026-02-18

## Prerequisites

- Python 3.13+ with `uv` package manager
- Existing Gmail credentials (`config/credentials.json`, `config/token.json`)
- Vault directory structure in place (`vault/` with subfolders)
- DEV_MODE=true in `config/.env` (default)

## 1. Start the Orchestrator

```bash
# Start in foreground (Ctrl+C to stop)
uv run python -m backend.orchestrator

# Start with dry-run (no actions executed even if DEV_MODE=false)
uv run python -m backend.orchestrator --dry-run
```

Expected output:
```
2026-02-18 09:00:00 [orchestrator] INFO: Acquiring lock...
2026-02-18 09:00:00 [orchestrator] INFO: Starting orchestrator (DEV_MODE=true)
2026-02-18 09:00:00 [orchestrator] INFO: Starting watcher: Gmail
2026-02-18 09:00:00 [orchestrator] WARNING: Skipping watcher: WhatsApp (playwright not installed)
2026-02-18 09:00:00 [orchestrator] WARNING: Skipping watcher: LinkedIn (playwright not installed)
2026-02-18 09:00:00 [orchestrator] INFO: Starting action executor (interval: 30s)
2026-02-18 09:00:00 [orchestrator] INFO: Starting dashboard updater (interval: 300s)
2026-02-18 09:00:00 [orchestrator] INFO: Orchestrator running. Press Ctrl+C to stop.
```

## 2. Check Dashboard

Open `vault/Dashboard.md` in Obsidian. It updates every 5 minutes with:
- Watcher status table (running/stopped/error)
- Vault folder file counts
- Last activity timestamp
- DEV_MODE indicator

## 3. Test Action Execution

Create an approval file to test the action executor:

```bash
# Create a test approval file
cat > vault/Approved/test-email-send.md << 'EOF'
---
type: email_send
status: approved
to: your-email@gmail.com
subject: Orchestrator Test
created: 2026-02-18T09:00:00Z
---
## Action Summary
Test email sent by the orchestrator's action executor.

## Email Content
Hello! This email was automatically sent by the AI Employee orchestrator.
EOF
```

The action executor will:
1. Detect the file within 30 seconds
2. Read the frontmatter
3. In DEV_MODE: log the action and move to `vault/Done/`
4. In production: send the email via Gmail and move to `vault/Done/`

## 4. Setup Windows Task Scheduler (Optional)

```powershell
# Register orchestrator to start on login
.\scripts\setup_scheduler.ps1

# Check status
Get-ScheduledTask -TaskName "AIEmployee-Orchestrator"

# Remove scheduled task
.\scripts\stop_all.ps1 -RemoveSchedule
```

## 5. Stop the Orchestrator

```bash
# If running in foreground: press Ctrl+C

# If running in background:
powershell .\scripts\stop_all.ps1
```

## Environment Variables

Add to `config/.env`:

```
ORCHESTRATOR_CHECK_INTERVAL=30        # Seconds between Approved folder checks
ORCHESTRATOR_DASHBOARD_UPDATE_INTERVAL=300  # Seconds between dashboard updates
ORCHESTRATOR_MAX_RESTART_ATTEMPTS=3   # Max watcher restarts before marking failed
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Another instance is running" | Check `config/.orchestrator.lock` — delete if stale (process not running) |
| Gmail watcher not starting | Verify `config/token.json` exists and is valid |
| WhatsApp/LinkedIn skipped | Install Playwright: `uv pip install playwright && playwright install` |
| Dashboard not updating | Check orchestrator is running and `ORCHESTRATOR_DASHBOARD_UPDATE_INTERVAL` setting |
| Actions not executing | Verify approval files have `status: approved` and recognized `type` in frontmatter |
