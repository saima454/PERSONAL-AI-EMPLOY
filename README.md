# Personal AI Employee

> **Gold Tier** — A "Digital FTE" autonomous agent that proactively manages personal and business affairs 24/7 using Claude Code as the executor and Obsidian as the management dashboard.

[![Tests](https://img.shields.io/badge/tests-45%20passing-brightgreen)](tests/)
[![Tier](https://img.shields.io/badge/tier-Gold-gold)](docs/ARCHITECTURE.md)
[![DEV_MODE](https://img.shields.io/badge/DEV__MODE-enabled-blue)](config/.env.example)

---

## What This Is

The Personal AI Employee monitors your email and WhatsApp, analyzes incoming items with Claude Code, creates action plans, and executes approved actions — all while keeping you in control through a file-based Human-in-the-Loop workflow. Your Obsidian vault is the dashboard.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   PERCEPTION    │────▶│    REASONING    │────▶│     ACTION      │
│    (Watchers)   │     │  (Claude Code)  │     │  (MCP Servers)  │
│                 │     │                 │     │                 │
│ • Gmail         │     │ • Orchestrator  │     │ • Send email    │
│ • WhatsApp      │     │ • Skills system │     │ • Post social   │
│ • Calendar      │     │ • CEO Briefing  │     │ • Odoo CRM      │
│ • Odoo feed     │     │ • Ralph Loop    │     │ • Payments      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
   vault/Inbox          vault/Plans           vault/Done
   vault/Needs_Action   vault/Pending_Approval
                        vault/Approved
```

---

## Tier Declaration: Gold ✅

| Requirement | Status |
|-------------|--------|
| Vault structure + HITL workflow | ✅ Implemented |
| Gmail watcher (OAuth2, retry, backoff) | ✅ Implemented |
| WhatsApp watcher (Playwright) | ✅ Implemented |
| Gmail MCP sender | ✅ Implemented |
| Action executor with rate limiting | ✅ Implemented |
| Odoo CRM/accounting integration | ✅ Implemented |
| Twitter/X social media posting | ✅ Implemented |
| LinkedIn posting | ✅ Implemented |
| CEO daily briefing | ✅ Implemented |
| Ralph Wiggum stop-hook loop | ✅ Implemented |
| Error recovery & watchdog supervision | ✅ Implemented |
| 45 automated tests | ✅ 45/45 passing |
| Skills documentation (13 skills) | ✅ 13 SKILL.md files |
| Project documentation | ✅ docs/ |

---

## Quick Start (Windows)

### Prerequisites

- Python 3.13+ (`python --version`)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — `winget install astral-sh.uv`
- [Obsidian](https://obsidian.md/) — for the vault dashboard
- [Claude Code CLI](https://claude.ai/code) — `npm install -g @anthropic-ai/claude-code`

### Installation

**1. Navigate to the project:**
```powershell
cd "AI_Employee_Hackathon"
```

**2. Install Python dependencies:**
```powershell
uv sync
```

**3. Set up environment:**
```powershell
copy config\.env.example config\.env
```

**4. Edit `config\.env` with your credentials:**
```env
# Minimum required for Gmail monitoring:
GMAIL_CLIENT_ID=your_client_id
GMAIL_CLIENT_SECRET=your_client_secret
GMAIL_REFRESH_TOKEN=your_refresh_token

# Keep this true during development!
DEV_MODE=true
```

**5. Open the vault in Obsidian:**
- Launch Obsidian
- "Open folder as vault" → select `.\vault\`

**6. Start the AI Employee:**
```powershell
uv run python main.py
```

### Gmail Setup (Required for email features)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Gmail API**
3. Create **OAuth 2.0 credentials** (Desktop application type)
4. Download `credentials.json` → save to `config\credentials.json`
5. Run the auth flow once to generate a refresh token
6. Add Client ID, Secret, and Refresh Token to `config\.env`

### WhatsApp Setup (Optional)

WhatsApp Web automation requires Playwright and an active WhatsApp account:
```powershell
uv run playwright install chromium
```
First run will show a QR code — scan with your phone.

---

## Running the System

### Start Everything
```powershell
uv run python main.py
```

### Start in Dry Run Mode (No File Changes)
```powershell
uv run python main.py --dry-run
```

### Run Tests
```powershell
uv run pytest tests/ -v
```

### Run Specific Test Class
```powershell
uv run pytest tests/test_ralph_loop.py::TestSafetyLimits -v
```

### Check Ralph Loop Status
```powershell
uv run python -m backend.ralph_wiggum --status
```

### Start a Ralph Wiggum Loop
```powershell
uv run python -m backend.ralph_wiggum `
  --completion-promise "TASK_COMPLETE" `
  --max-iterations 10 `
  "Process all emails in vault/Needs_Action"
```

### Emergency Stop All Ralph Loops
```powershell
New-Item vault\STOP_RALPH -ItemType File
# or on bash:
touch vault/STOP_RALPH
```

### Linting
```powershell
uv run ruff check .
uv run ruff format .
```

---

## Project Structure

```
AI_Employee_Hackathon/
├── main.py                     # Entry point
├── backend/
│   ├── orchestrator/
│   │   ├── orchestrator.py     # Main coordinator
│   │   ├── watchdog.py         # Supervised task runner
│   │   └── action_executor.py  # Approved action processor
│   ├── watchers/
│   │   ├── gmail_watcher.py    # Gmail monitor
│   │   └── whatsapp_watcher.py # WhatsApp monitor
│   ├── ralph_wiggum/           # Stop-hook loop system
│   │   ├── ralph_loop.py       # Core loop controller
│   │   ├── stop_hook.py        # Claude Code onStop hook
│   │   ├── state_manager.py    # State persistence
│   │   └── prompt_injector.py  # Context-aware prompt builder
│   └── mcp_servers/            # Action executors
│       ├── gmail_mcp.py
│       ├── odoo_mcp.py
│       ├── twitter_mcp.py
│       └── linkedin_mcp.py
├── skills/                     # AI skill definitions (SKILL.md)
│   ├── gmail-watcher/
│   ├── email-sender/
│   ├── whatsapp-watcher/
│   ├── social-media-manager/
│   ├── twitter-manager/
│   ├── linkedin-poster/
│   ├── odoo-integration/
│   ├── ceo-briefing/
│   ├── content-scheduler/
│   ├── orchestrator/
│   ├── vault-manager/
│   ├── ralph-wiggum/
│   └── error-recovery/         # Error handling reference
├── vault/                      # Obsidian vault (your dashboard)
│   ├── Dashboard.md
│   ├── Company_Handbook.md     # Your AI employee rules
│   ├── Business_Goals.md
│   ├── Inbox/
│   ├── Needs_Action/
│   ├── Plans/
│   ├── Pending_Approval/
│   ├── Approved/
│   ├── Rejected/
│   ├── Done/
│   ├── Logs/
│   ├── Briefings/
│   └── ralph_wiggum/           # Ralph loop state files
├── docs/
│   ├── ARCHITECTURE.md         # System design deep dive
│   ├── LESSONS_LEARNED.md      # Technical retrospective
│   └── DEMO_SCRIPT.md          # Video demo script
├── config/
│   ├── .env.example            # Environment template
│   └── mcp.json                # MCP server config
└── tests/
    └── test_ralph_loop.py      # 45 tests
```

---

## Safety Features

### DEV_MODE (Default: ON)

When `DEV_MODE=true` (the default):
- **No real emails sent** — logged only
- **No real payments processed** — logged only
- **No real social media posts** — logged only
- **WhatsApp reads** still work (read-only is safe)

**Keep `DEV_MODE=true` during all development. Set to `false` only for production.**

### Human-in-the-Loop (HITL)

Sensitive actions require your explicit approval before execution:

1. AI creates a plan → `vault/Plans/`
2. Plan auto-moves → `vault/Pending_Approval/`
3. **You review and move** → `vault/Approved/` or `vault/Rejected/`
4. Only approved items are executed

**Never auto-approved:**
- Any payment
- Emails to >5 recipients
- Social media posts
- Contracts or agreements

### Rate Limits

Built-in enforcement at the action executor layer:

| Action Type | Limit |
|-------------|-------|
| Email sends | 10/hour |
| Payments | 3/hour |
| Social posts | 5/day per platform |

### Watchdog Supervision

Each watcher runs under supervision with exponential backoff restart:
- Crash → wait `2^n` seconds (max 60s) → restart
- After 3 crashes: mark `FAILED`, continue with other watchers

### Payment Safety

Payment actions are **never automatically retried**. If a payment fails, the file remains in `Approved/` for manual review. You must explicitly re-initiate.

---

## Architecture Overview

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full system design including:
- Component map with file paths
- Data flow diagrams for email processing and CEO briefing
- State management format
- Security architecture
- Key architectural decisions (ADRs)

---

## Skills

All AI capabilities are documented as Skills in `skills/*/SKILL.md`:

| Skill | Purpose |
|-------|---------|
| `gmail-watcher` | Monitor Gmail inbox |
| `email-sender` | Compose and send emails |
| `whatsapp-watcher` | Monitor WhatsApp Web |
| `social-media-manager` | Multi-platform posting coordination |
| `twitter-manager` | Twitter/X specific posting |
| `linkedin-poster` | LinkedIn posting |
| `odoo-integration` | Odoo CRM/accounting actions |
| `ceo-briefing` | Daily executive briefing generation |
| `content-scheduler` | Scheduled content publication |
| `orchestrator` | System coordination and supervision |
| `vault-manager` | Vault file operations |
| `ralph-wiggum` | Stop-hook iterative task completion |
| `error-recovery` | Error handling reference and taxonomy |

---

## Tier Progression

| Tier | Hours | Key Features |
|------|-------|-------------|
| **Bronze** | 8-12h | Vault structure, 1 watcher, 2-3 skills, basic HITL |
| **Silver** | 20-30h | 2+ watchers, Gmail MCP, action executor, dashboard |
| **Gold** ← **HERE** | 40+h | Odoo, social media, CEO briefings, Ralph Wiggum loop |
| **Platinum** | 60+h | Cloud deployment, mobile notifications, multi-agent |

---

## Development

### Running Tests

```powershell
# All tests
uv run pytest

# With verbose output
uv run pytest -v

# Single test class
uv run pytest tests/test_ralph_loop.py::TestStopHook -v

# With coverage
uv run pytest --cov=backend tests/
```

### Type Checking

```powershell
uv run mypy backend/
```

### Code Quality

```powershell
uv run ruff check .    # Lint
uv run ruff format .   # Format
```

---

## Lessons Learned

See [docs/LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md) for a full technical retrospective including:
- Why the file system message bus pattern works for personal automation
- The Ralph Wiggum stop-hook pattern design
- Testing asyncio code
- Payment safety rules
- What we'd do differently

---

## Security Notes

- All credentials stored in `config/.env` — never committed to git
- `.gitignore` excludes `.env`, `credentials.json`, `*.lock`, `__pycache__`
- `DEV_MODE=true` by default prevents accidental real actions
- All secrets accessed via `os.getenv()` — no hardcoded values
- Rate limits enforced at execution layer, not planning layer

---

## License

MIT

---

Built for the Personal AI Employee Hackathon — Gold Tier
