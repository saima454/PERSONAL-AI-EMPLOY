# Demo Script: Personal AI Employee — Gold Tier

> Target duration: 5-10 minutes | Format: Screen recording + narration

---

## Pre-Demo Setup (5 minutes before recording)

**Environment checklist:**
- [ ] `DEV_MODE=true` confirmed in config/.env
- [ ] Obsidian open with vault/ folder loaded
- [ ] Terminal ready at project root
- [ ] Clear vault/Inbox/, vault/Needs_Action/, vault/Pending_Approval/
- [ ] vault/Dashboard.md visible in Obsidian
- [ ] Orchestrator NOT running yet (will start live)

**Terminal tabs to prepare:**
1. Tab 1: `uv run python main.py` (will run live)
2. Tab 2: `uv run pytest tests/ -v` (will run live)
3. Tab 3: Ralph loop demo commands

---

## PART 1: System Start + Architecture (0:00 – 1:30)

### [0:00] Opening

> "This is the Personal AI Employee — a Gold Tier autonomous agent built with Claude Code that manages personal and business affairs 24/7."

**Show**: The README.md architecture diagram in editor or terminal.

> "Three-layer architecture: Perception — Watchers that monitor Gmail and WhatsApp. Reasoning — Claude Code that analyzes and creates plans. Action — MCP servers that execute approved actions."

> "Everything flows through this Obsidian vault — a local file system that's simultaneously the database, message bus, and dashboard."

**Show**: Obsidian vault folder structure — point out Inbox, Needs_Action, Plans, Pending_Approval, Approved, Done.

---

### [1:30] Start the Orchestrator

**Switch to Terminal Tab 1:**

```bash
uv run python main.py
```

**Show the logs appearing:**

> "The orchestrator starts all watchers as supervised async tasks. Each watcher runs independently — if one crashes, the others keep running. Watch the watchdog supervision logs here."

**Point to output:**
```
INFO  Orchestrator started
INFO  WatcherTask: gmail_watcher → running
INFO  WatcherTask: whatsapp_watcher → running
INFO  ActionExecutor → polling Approved/
```

---

## PART 2: HITL Workflow — Email Processing (1:30 – 4:00)

### [1:30] Simulate Incoming Email

> "We're in DEV_MODE, so no real emails are sent. Let me simulate an incoming email."

**In a new terminal or file manager, create:**
`vault/Inbox/email_demo_001.md`

```markdown
---
id: email_demo_001
type: inbox_email
source: gmail
sender: client@example.com
subject: Invoice #1234 — Payment Due
received_at: 2026-02-25T10:00:00Z
priority: high
---

Hi,

I'm following up on invoice #1234 for $2,500 due February 28.
Please confirm receipt and expected payment date.

Thanks,
Alex
```

**Show**: File appearing in Obsidian Inbox folder in real-time.

> "Gmail watcher detected a new email. It's written to Inbox as a structured Markdown file."

---

### [2:00] AI Processes and Creates Plan

> "The orchestrator picks this up and invokes Claude Code to analyze it and create an action plan."

**Wait for, or show pre-created:**
`vault/Plans/plan_email_demo_001.md`

**Show**: Plan in Obsidian.

> "Claude analyzed the email as a high-priority payment inquiry. It's proposed a professional response acknowledging receipt and confirming payment timeline. The plan is now in Plans/ folder."

---

### [2:45] Human Approval Workflow

> "Sensitive actions always require human approval. This email reply goes to Pending_Approval."

**Show**: File in vault/Pending_Approval/ in Obsidian.

> "As the human operator, I review the plan. Looks good. I'll approve it."

**In Obsidian**: Drag/move file from Pending_Approval/ to Approved/ folder.

> "The action executor polls Approved/ every 30 seconds. Since we're in DEV_MODE, it logs what it would do rather than sending a real email."

**Show terminal log:**
```
INFO  [DEV_MODE] Would send email to client@example.com
INFO  Action completed: email_reply_sent
INFO  Moving email_demo_001 to Done/
```

**Show**: File appears in vault/Done/.

> "Complete audit trail — every action logged with timestamps and correlation IDs."

---

## PART 3: CEO Daily Briefing (4:00 – 5:30)

### [4:00] Show Today's Briefing

**Open**: `vault/Briefings/briefing_2026-02-25.md` in Obsidian.

> "Every morning, the orchestrator generates a CEO briefing. It aggregates the day's events — pending approvals, completed actions, any system issues — and asks Claude Code to synthesize it into an executive summary."

**Read out key sections:**
- Pending actions requiring attention
- Actions completed overnight
- System health (all watchers running)
- Today's priorities

> "This is the 'morning briefing' pattern — instead of checking 10 different dashboards, everything is in one markdown file."

---

## PART 4: Ralph Wiggum Loop — Multi-Step Task (5:30 – 7:30)

### [5:30] Introduce the Pattern

> "For complex multi-step tasks, we have the Ralph Wiggum pattern. Standard Claude Code exits after one attempt. Ralph Wiggum keeps it iterating until the job is done."

> "The name comes from 'I can stop any time I want' — but Ralph actually can't stop until the task is complete."

**Switch to Terminal Tab 3:**

```bash
uv run python -m backend.ralph_wiggum --completion-promise "TASK_COMPLETE" \
  --max-iterations 5 \
  "Process all unread emails in vault/Needs_Action and create action plans for each"
```

**Show output:**
```
INFO  Ralph Loop started: RW_20260225_100000
INFO  DEV_MODE: Simulating Claude iteration 1
INFO  Iteration 1 complete (1.0s) — task not yet complete
INFO  DEV_MODE: Simulating Claude iteration 2
INFO  Iteration 2 complete (1.0s) — task not yet complete
INFO  DEV_MODE: Simulating Claude iteration 3
INFO  Claude output contains TASK_COMPLETE marker
INFO  Loop completed successfully after 3 iterations
INFO  Exit code: 0
```

> "Three iterations to complete. The loop checked Claude's output after each iteration, looking for the TASK_COMPLETE marker."

---

### [6:30] Show Ralph State File

**Open in Obsidian**: `vault/ralph_wiggum/RW_20260225_100000.md`

> "Every Ralph loop writes a state file tracking each iteration — timestamps, duration, status, notes. Complete audit trail."

**Show the status command:**

```bash
uv run python -m backend.ralph_wiggum --status
```

```
Ralph Loop Status
═══════════════════════
Total loops: 1
  completed: 1
  halted:    0
  in_progress: 0

Recent loops:
  RW_20260225_100000 — completed (3 iterations)
```

---

## PART 5: Test Suite (7:30 – 8:30)

### [7:30] Run Tests Live

**Switch to Terminal Tab 2:**

```bash
uv run pytest tests/ -v --tb=short
```

**Show tests passing:**
```
tests/test_ralph_loop.py::TestRalphConfig::test_config_defaults PASSED
tests/test_ralph_loop.py::TestStateManager::test_create_task PASSED
... (45 tests)

============= 45 passed in 3.2s =============
```

> "45 tests across 8 test classes. Full coverage of the Ralph Wiggum system — config validation, state management, prompt injection, file movement, safety limits, status reporting, stop hook, and orchestrator integration."

---

## PART 6: Safety & Architecture Summary (8:30 – 10:00)

### [8:30] Safety Features

**Show**: config/.env.example

> "All credentials in environment variables. Never committed to git. DEV_MODE=true by default."

**Show**: Rate limits in action_executor.py or config/rate_limits.json

> "Built-in rate limiting: 10 emails/hour, 3 payments/hour, 5 social posts/day. These limits are enforced at the execution layer — impossible to bypass from the orchestrator."

> "Payments follow a special rule: NEVER auto-retry. If a payment action fails, it stays in Approved/ for human review. The risk of a double-payment is too high."

---

### [9:00] Tier Declaration

**Show**: Tier table (README.md or docs/ARCHITECTURE.md)

> "This is a Gold Tier submission. Let me walk through what that means:"

| Feature | Status |
|---------|--------|
| Vault structure + HITL workflow | ✅ |
| Gmail watcher (OAuth2, retry) | ✅ |
| WhatsApp watcher (Playwright) | ✅ |
| Gmail MCP sender | ✅ |
| Action executor | ✅ |
| Odoo integration | ✅ |
| Twitter/LinkedIn posting | ✅ |
| CEO daily briefing | ✅ |
| Ralph Wiggum stop-hook loop | ✅ |
| Error recovery (watchdog) | ✅ |
| 45 automated tests | ✅ |
| Skills documentation (13 skills) | ✅ |

> "12 skills documented, full HITL workflow, DEV_MODE safety, exponential backoff watchdog, CEO briefing, and the Ralph Wiggum loop pattern."

---

### [9:30] Closing

> "The Personal AI Employee is running. It's monitoring email, processing requests, and keeping humans in the loop for sensitive decisions. The vault is your dashboard. Claude Code is the executor. And the Ralph Wiggum pattern ensures complex tasks complete reliably."

> "All code on GitHub. All documentation in the vault. DEV_MODE by default — safe to run immediately."

**Show**: Obsidian Dashboard.md with live status.

> "Questions? The vault and code tell the whole story."

---

## Post-Demo Notes

### Common Questions + Answers

**Q: Is this running 24/7?**
A: Yes — `main.py` runs indefinitely. The orchestrator keeps watchers alive via the watchdog. In production, you'd run this as a system service.

**Q: What happens if Claude Code is unavailable?**
A: Ralph loops return `HaltReason.subprocess_error`. Orchestrator logs and marks the task. The HITL workflow continues for pre-approved actions.

**Q: How does it handle multiple email accounts?**
A: Currently one Gmail account per instance. Multiple accounts require multiple watcher instances (planned for Platinum tier).

**Q: Is it safe to run with real credentials?**
A: Yes — with `DEV_MODE=true`. Set to false only when you want real actions. Start with email-only, validate behavior, then enable social/payment actions one at a time.

**Q: What's the Obsidian vault for?**
A: It's your control panel. Every action the AI takes or proposes is visible as a Markdown file. You can edit, approve, or reject with Obsidian's UI — no code required.

---

## Troubleshooting During Demo

**Orchestrator not starting:**
```bash
uv run python main.py --dry-run  # Safe mode
```

**Tests failing:**
```bash
uv run pytest tests/test_ralph_loop.py -v -x  # Stop on first failure
```

**Ralph loop hanging:**
```bash
touch vault/STOP_RALPH  # Emergency stop (sentinel file)
```

**Obsidian not showing new files:**
- Files appear in real-time on macOS/Linux
- On Windows: may need to click refresh in Obsidian sidebar
