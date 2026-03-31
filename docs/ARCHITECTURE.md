# Architecture: Personal AI Employee

> Gold Tier — autonomous agent system built on Claude Code + Obsidian vault.

---

## System Overview

The Personal AI Employee is a **local-first, event-driven autonomous agent** that runs continuously on your machine. It monitors data sources, reasons using Claude Code, and executes approved actions via MCP servers — all while keeping you in control through a file-based approval workflow.

```
┌──────────────────────────────────────────────────────────────────┐
│                    PERSONAL AI EMPLOYEE                          │
│                                                                  │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────┐  │
│  │   PERCEPTION    │    │    REASONING    │    │   ACTION    │  │
│  │   (Watchers)    │───▶│  (Claude Code)  │───▶│(MCP Servers)│  │
│  │                 │    │                 │    │             │  │
│  │ • Gmail         │    │ • Orchestrator  │    │ • Gmail MCP │  │
│  │ • WhatsApp      │    │ • Skills system │    │ • Odoo MCP  │  │
│  │ • Calendar      │    │ • CEO Briefing  │    │ • Twitter   │  │
│  │ • Odoo feed     │    │ • Ralph Loop    │    │ • LinkedIn  │  │
│  └────────┬────────┘    └────────┬────────┘    └──────┬──────┘  │
│           │                      │                     │         │
│           ▼                      ▼                     ▼         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    OBSIDIAN VAULT                        │   │
│  │   Inbox → Needs_Action → Plans → Pending_Approval        │   │
│  │   → [HUMAN] → Approved → Done                           │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Core Architectural Patterns

### 1. Vault as Message Bus

All inter-component communication flows through the file system. The Obsidian vault is simultaneously:
- **The database** (YAML-frontmatter Markdown files)
- **The message bus** (file presence = event)
- **The dashboard** (Obsidian renders it as a UI)

This design means:
- No network required between components
- Human can inspect/modify any state by editing Markdown
- Complete audit trail in version-controlled files
- No database setup or maintenance

### 2. HITL Workflow (Human-in-the-Loop)

```
Watcher detects event
        │
        ▼
   vault/Inbox/
   (raw email/message MD)
        │
        ▼
   vault/Needs_Action/
   (flagged for AI processing)
        │
        ▼ Claude Code reads + reasons
   vault/Plans/
   (AI-generated action plan)
        │
        ▼
   vault/Pending_Approval/
   (awaiting human decision)
        │
    ┌───┴───┐
    ▼       ▼
 Approved  Rejected
    │
    ▼ Action Executor
  vault/Done/
  (completed with audit log)
```

**Sensitive actions NEVER bypass this flow:**
- Any payment
- Bulk email (>5 recipients)
- Social media posts
- Contract/agreement actions

### 3. Watchdog Supervision Pattern

Every watcher runs as a supervised asyncio task:

```
Orchestrator.run()
├── WatcherTask(gmail_watcher)     ← supervised by watchdog
├── WatcherTask(whatsapp_watcher)  ← supervised by watchdog
├── ActionExecutor polling loop    ← supervised by watchdog
├── DashboardUpdater               ← supervised by watchdog
├── CEOBriefingScheduler           ← supervised by watchdog
└── RalphLoopMonitor               ← supervised by watchdog

Watchdog restart policy:
  crash → sleep(2^restart_count, max=60s) → restart
  crash × 3 → status=FAILED → continue with remaining tasks
```

Each watcher failure is **isolated** — the system degrades gracefully rather than crashing.

### 4. Ralph Wiggum Stop-Hook Pattern

For multi-step tasks that require many Claude Code iterations:

```
Operator creates vault/Needs_Action/task.md with:
  type: ralph_loop_task
  completion_promise: TASK_COMPLETE
  max_iterations: 10

Orchestrator detects → spawns RalphLoop
  │
  ├── Mode A: Hook-based (interactive)
  │   └── .claude/settings.json onStop hook
  │       → stop_hook.py reads stdin JSON
  │       → if task incomplete: {"decision": "block", "reason": "..."}
  │       → if complete: {"decision": "approve"}
  │
  └── Mode B: Subprocess-based (programmatic)
      └── ralph_loop.py calls `claude -p prompt` in loop
          → checks Claude output for TASK_COMPLETE
          → or watches vault/Done/ for completion file
          → halts on max_iterations / timeout / STOP_RALPH
```

State persisted to `vault/ralph_wiggum/RW_YYYYMMDD_HHMMSS.md` after every iteration.

---

## Component Map

```
AI_Employee_Hackathon/
│
├── main.py                          # Entry point: starts orchestrator
│
├── backend/
│   ├── orchestrator/
│   │   ├── orchestrator.py          # Main coordinator (async task manager)
│   │   ├── watchdog.py              # Supervised task runner (exp. backoff)
│   │   └── action_executor.py       # Approved/ folder processor
│   │
│   ├── watchers/
│   │   ├── base_watcher.py          # Abstract polling base class
│   │   ├── gmail_watcher.py         # Gmail API monitor (OAuth2, retry)
│   │   └── whatsapp_watcher.py      # WhatsApp Web scraper (Playwright)
│   │
│   ├── ralph_wiggum/
│   │   ├── ralph_loop.py            # Loop controller + CLI
│   │   ├── stop_hook.py             # Claude Code onStop hook handler
│   │   ├── state_manager.py         # YAML state persistence
│   │   ├── prompt_injector.py       # Context-aware prompt builder
│   │   └── __init__.py              # Dataclasses/enums
│   │
│   ├── mcp_servers/
│   │   ├── gmail_mcp.py             # Send email actions
│   │   ├── odoo_mcp.py              # Odoo CRM/accounting actions
│   │   ├── twitter_mcp.py           # Twitter/X posting
│   │   └── linkedin_mcp.py          # LinkedIn posting
│   │
│   └── utils/
│       ├── logging_utils.py         # Structured JSON event logging
│       ├── timestamps.py            # UTC ISO-8601 helpers
│       └── uuid_utils.py            # Correlation ID generation
│
├── skills/                          # AI capability definitions (SKILL.md)
│   ├── gmail-watcher/               # Gmail monitoring skill
│   ├── email-sender/                # Email composition skill
│   ├── whatsapp-watcher/            # WhatsApp monitoring skill
│   ├── social-media-manager/        # Social media skill
│   ├── twitter-manager/             # Twitter-specific skill
│   ├── linkedin-poster/             # LinkedIn-specific skill
│   ├── odoo-integration/            # Odoo CRM skill
│   ├── ceo-briefing/                # Daily briefing skill
│   ├── content-scheduler/           # Scheduled content skill
│   ├── orchestrator/                # System coordination skill
│   ├── vault-manager/               # Vault operations skill
│   ├── ralph-wiggum/                # Stop-hook iteration skill
│   └── error-recovery/              # Error handling reference
│
├── vault/                           # Obsidian vault (live data)
│   ├── Dashboard.md                 # Real-time system status
│   ├── Company_Handbook.md          # AI employee rules
│   ├── Business_Goals.md            # Current objectives
│   ├── Inbox/                       # Raw incoming items
│   ├── Needs_Action/                # Queued for AI processing
│   ├── Plans/                       # AI-generated plans
│   ├── Pending_Approval/            # Awaiting human decision
│   ├── Approved/                    # Ready to execute
│   ├── Rejected/                    # Declined
│   ├── Done/                        # Completed
│   ├── Logs/                        # Structured event logs
│   │   ├── actions/                 # Action audit trail
│   │   ├── errors/                  # Error events
│   │   ├── decisions/               # AI reasoning logs
│   │   └── audit/                   # Security audit trail
│   ├── Briefings/                   # CEO daily briefings
│   ├── Accounting/                  # Financial records
│   └── ralph_wiggum/                # Ralph loop state files
│
├── config/
│   ├── .env                         # Secrets (never commit)
│   ├── .env.example                 # Template with documentation
│   ├── mcp.json                     # MCP server endpoints
│   └── rate_limits.json             # Rate limit configuration
│
├── tests/
│   ├── test_ralph_loop.py           # 45 tests, 8 test classes
│   └── test_orchestrator.py         # Orchestrator/watcher tests
│
└── specs/                           # Feature specifications
    ├── 001-ralph-loop/              # Ralph Wiggum stop-hook spec
    └── ...                          # Other feature specs
```

---

## Data Flow: Email Processing

```
1. Gmail Watcher polls every 30s
   └── gmail_watcher.check_for_updates()
       └── _fetch_messages_with_retry() [3 retries, exp. backoff]
           └── Returns list of email objects

2. Watcher creates vault/Inbox/email_<id>.md
   YAML frontmatter: sender, subject, timestamp, labels
   Body: email content (truncated for privacy)

3. Orchestrator detects new Inbox file
   └── Runs Claude Code: "analyze this email and create a plan"
   └── Claude writes vault/Plans/plan_<id>.md

4. Orchestrator moves Plan → Pending_Approval
   └── Sends notification (if configured)

5. Human opens Obsidian, reviews plan
   └── Drags file to Approved/ or Rejected/

6. Action Executor polls Approved/ every 30s
   └── Reads approved action from frontmatter
   └── Checks rate limits
   └── Calls appropriate MCP server (or DEV_MODE logs only)
   └── Moves to Done/ with result metadata
```

---

## Data Flow: CEO Daily Briefing

```
Orchestrator.run()
└── _check_briefing_schedule() [every 5 min]
    └── Reads vault/Company_Handbook.md for briefing_time
    └── At configured time:
        └── Collects: pending approvals, completed actions,
                      active Ralph loops, system errors
        └── Calls Claude Code with CEO briefing skill
        └── Writes vault/Briefings/briefing_YYYY-MM-DD.md
        └── Updates vault/Dashboard.md
```

---

## State Management

### Vault File Format (Standard)

```markdown
---
id: email_abc123
type: inbox_email          # inbox_email | action_plan | ralph_loop_task | ...
status: pending_approval   # State machine value
created_at: 2026-02-25T10:00:00Z
updated_at: 2026-02-25T10:05:00Z
source: gmail
correlation_id: corr_xyz   # Links related files
---

# Subject: Q1 Review Meeting

Body content here...
```

### Ralph Wiggum State File Format

```markdown
---
task_id: RW_20260225_100000
status: in_progress         # in_progress | completed | halted | error
current_iteration: 3
max_iterations: 10
completion_strategy: promise
completion_promise: TASK_COMPLETE
started_at: 2026-02-25T10:00:00Z
halt_reason: null
---

## Iterations

<!-- ITERATIONS_SECTION_START -->
| # | Started | Duration | Status | Notes |
|---|---------|----------|--------|-------|
| 1 | 10:00Z  | 45s      | ok     | ...   |
<!-- ITERATIONS_SECTION_END -->
```

---

## Security Architecture

### Credential Isolation

```
config/.env                    ← never committed (in .gitignore)
config/.env.example            ← committed (template only, no real values)
config/credentials.json        ← never committed (OAuth2 token)
```

All secrets accessed via `os.getenv()`. No hardcoded values anywhere.

### DEV_MODE Protection

When `DEV_MODE=true` (default):
- Gmail watcher reads real email, but MCP send is suppressed
- WhatsApp watcher reads real messages, but send is suppressed
- All social media posts are logged but not submitted
- All payment actions are blocked
- Action executor logs what it would do instead of doing it

### Rate Limiting

Enforced at the action executor level before calling any MCP server:

| Action | Limit | Window |
|--------|-------|--------|
| Email send | 10 | Per hour |
| Payment | 3 | Per hour |
| Social post | 5 per platform | Per day |

---

## Tier Progression

| Tier | Status | Features Implemented |
|------|--------|---------------------|
| **Bronze** | ✅ | Vault structure, Gmail watcher, 2-3 skills, basic HITL |
| **Silver** | ✅ | WhatsApp watcher, Gmail MCP sender, action executor, dashboard |
| **Gold** | ✅ | Odoo integration, Twitter/LinkedIn, CEO briefing, Ralph Wiggum loop |
| **Platinum** | Planned | Cloud deployment, mobile push, multi-agent coordination |

---

## Key Architectural Decisions

### ADR-001: File System as Message Bus
**Decision**: Use Markdown files in the Obsidian vault for all inter-component communication.
**Rationale**: Zero infrastructure, human-readable, version-controllable, works with Obsidian UI.
**Trade-off**: Not suitable for high-frequency events (>1/second). Acceptable for personal AI assistant workloads.

### ADR-002: Single-Process Async Architecture
**Decision**: All components run as asyncio tasks in one Python process.
**Rationale**: Simpler deployment, shared memory for configuration, no inter-process communication overhead.
**Trade-off**: One OOM crash affects all components. Mitigated by watchdog supervision.

### ADR-003: Skills as SKILL.md Files
**Decision**: All AI capabilities documented in `skills/*/SKILL.md` before code is written.
**Rationale**: Constitution Principle III requires skills-first design. Makes capabilities auditable and human-readable.
**Trade-off**: Extra documentation step. Worth it for system coherence.

### ADR-004: Ralph Wiggum Two-Mode Architecture
**Decision**: Support both hook-based (interactive) and subprocess-based (programmatic) iteration.
**Rationale**: Hook-based is natural for interactive Claude Code sessions; subprocess is needed for programmatic orchestrator integration.
**Trade-off**: Two code paths to maintain. Shared state_manager.py and prompt_injector.py reduce duplication.
