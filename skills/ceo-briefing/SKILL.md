# Skill: CEO Briefing Generator

## Metadata

```yaml
name: ceo-briefing
version: 1.0.0
layer: REASONING
sensitivity: LOW
```

## Triggers

Invoke this skill when the user says:
- "generate briefing" / "generate CEO briefing"
- "weekly report" / "weekly briefing"
- "Monday briefing" / "morning briefing"
- "run briefing" / "create briefing"
- "show briefing status" / "briefing status"
- "preview briefing" / "preview report"
- "is briefing due?" / "when is the next briefing?"
- "generate now" (in context of CEO briefing)
- "briefing for last N days" / "--period"

## What This Skill Does

The CEO Briefing Generator is a REASONING layer skill. It reads data from 7 sources (Odoo financials, vault task folders, action logs, and business goals), formats a structured weekly Markdown report, and saves it to `vault/Briefings/`.

**It does NOT send emails, WhatsApp messages, or external notifications.** It is a local read + local write operation — a deterministic audit report of the past N days.

## End-to-End Flow

```
7 Data Sources (read-only)
        ↓
[Odoo] Revenue, invoices, payments, bank balance
[vault/Done/] Completed tasks in review period
[vault/Needs_Action/] Pending items (with age)
[vault/Pending_Approval/] Pending approvals (with age)
[vault/Logs/actions/] Email, WhatsApp, LinkedIn, social counts
[vault/Business_Goals.md] Revenue targets, KPIs, deadlines
[vault/Content_Strategy.md] Social posting context
        ↓
DataCollectors (data_collectors.py) — one method per source
        ↓
ReportFormatter (report_formatter.py) — BriefingData → Markdown
        ↓
vault/Briefings/YYYY-MM-DD_Monday_Briefing.md   ← final artifact
        ↓
vault/Dashboard.md  ← updated with "Latest Briefing" sentinel block
        ↓
vault/Logs/actions/YYYY-MM-DD.json  ← briefing_generated entry logged
```

## No HITL Required

**No human approval needed.** The CEO briefing is a read-only audit report:
- All Odoo calls are read-only (`list_invoices`, `get_account_balance`, `list_transactions`)
- Output is a Markdown file in `vault/Briefings/` — local write only
- No emails sent, no social posts, no payments, no external actions

Per constitution Principle IV: HITL is required for payments, social posts, emails, and account modifications. Briefing generation triggers none of these.

## Permissions

```yaml
permissions:
  vault_read:
    - vault/Done/*.md
    - vault/Needs_Action/*.md
    - vault/Pending_Approval/*.md
    - vault/Logs/actions/*.json
    - vault/Business_Goals.md
    - vault/Content_Strategy.md
    - vault/Dashboard.md
  vault_write:
    - vault/Briefings/YYYY-MM-DD_Monday_Briefing.md
    - vault/Dashboard.md  # sentinel block update only
    - vault/Logs/actions/YYYY-MM-DD.json  # briefing_generated entry
  external_apis:
    - Odoo XML-RPC (read-only: list_invoices, get_account_balance, list_transactions)
  browser: none
```

## Dependencies

- `backend/mcp_servers/odoo/odoo_client.py` — OdooClient for financial data (Feature 006)
- `backend/utils/frontmatter.py` — extract_frontmatter(), parse_frontmatter()
- `backend/utils/logging_utils.py` — log_action(), read_logs_for_date()
- `backend/utils/timestamps.py` — now_iso(), parse_iso()
- `vault/Done/`, `vault/Logs/actions/`, `vault/Needs_Action/` — must exist (created by orchestrator)

## CLI Commands

```bash
# Generate briefing immediately (DEV_MODE uses mock Odoo data)
DEV_MODE=true uv run python -m backend.briefing.briefing_generator --generate-now

# Force overwrite an existing same-day briefing
uv run python -m backend.briefing.briefing_generator --generate-now --force

# Preview briefing in console (no files written)
uv run python -m backend.briefing.briefing_generator --preview

# Custom period (30-day lookback instead of 7-day default)
uv run python -m backend.briefing.briefing_generator --generate-now --period 30

# Check system status (last run, next scheduled, vault health, Odoo ping)
uv run python -m backend.briefing.briefing_generator --status

# Normal run (respects Monday schedule — skips if not due)
uv run python -m backend.briefing.briefing_generator
```

## Decision Tree

```
Briefing trigger (manual or orchestrator Monday check)
    ↓
Is it Monday (local timezone: Asia/Karachi) AND time >= 08:00 PKT?
    NO → Skip (log DEBUG "briefing not due")
    YES ↓ (or --generate-now bypasses this check)
Briefing already exists for today?
    YES → Skip (idempotency) unless --force
    NO ↓
Collect data from all 7 sources:
    ├── Odoo financials (DEV_MODE=true → mock data)
    ├── vault/Done/ completed tasks (date-range filtered)
    ├── vault/Needs_Action/ + vault/Pending_Approval/ pending items
    ├── vault/Logs/actions/ communication summary
    ├── vault/Business_Goals.md KPI targets
    └── Detect bottlenecks + generate suggestions
        ↓
Format report: 7 sections + YAML frontmatter
        ↓
Write vault/Briefings/YYYY-MM-DD_Monday_Briefing.md
        ↓
Update vault/Dashboard.md (sentinel pattern — preserves orchestrator content)
        ↓
Log briefing_generated entry to vault/Logs/actions/YYYY-MM-DD.json
```

## Output Format

Generated briefings follow this canonical structure:

```markdown
---
generated: YYYY-MM-DDTHH:MM:SSZ
period: YYYY-MM-DD to YYYY-MM-DD
period_start: YYYY-MM-DD
period_end: YYYY-MM-DD
period_days: 7
type: ceo_briefing
sources: [odoo, vault_done, vault_logs, vault_needs_action, business_goals]
dev_mode: false
---

# Monday Morning CEO Briefing

## Executive Summary
[2-3 sentence overview comparing actuals to Business_Goals.md targets]

## Revenue & Financial Health
- **This Week Revenue**: $X,XXX
- **MTD Revenue**: $X,XXX (XX% of monthly target)
- **Outstanding Invoices**: X invoices ($X,XXX total)
- **Recent Payments Received**: X payments ($X,XXX)
- **Cash Position**: $X,XXX (bank balance)
- **Trend**: [On track / Behind / Ahead]

## Completed Tasks This Week
- [x] Task 1 — YYYY-MM-DD
...

## Pending Items
- [ ] Item 1 — waiting N days
...

## Communication Summary
- **Emails processed**: X
- **WhatsApp messages**: X flagged
- **LinkedIn messages**: X flagged
- **Social media posts**: X published this week

## Bottlenecks & Delays
| Task | Reason | Age |
|------|--------|-----|

## Proactive Suggestions
### Cost Optimization
### Upcoming Deadlines
### Recommendations

---
*Generated by AI Employee v1.0*
```

## Automated Schedule (Orchestrator Integration)

The orchestrator checks for a due briefing every time it starts:

```python
# In Orchestrator.run() — fires on every startup:
await self._check_briefing_schedule()
# If Monday AND time >= CEO_BRIEFING_TIME AND no briefing today → generate
```

**Expected log entries** (in `vault/Logs/actions/YYYY-MM-DD.json`):
- `briefing_generated` — new briefing created
- `briefing_skipped` — already exists or not due today
- `briefing_checked` — schedule check ran (debug level)

## Environment Variables

```
CEO_BRIEFING_DAY=monday              # Day of week for auto-generation
CEO_BRIEFING_TIME=08:00              # Time (HH:MM, 24-hour, local timezone)
CEO_BRIEFING_TIMEZONE=Asia/Karachi   # IANA timezone (UTC+5, PKT)
CEO_BRIEFING_PERIOD_DAYS=7           # Default lookback window in days
```

## DEV_MODE Behavior

When `DEV_MODE=true`:
- Odoo calls are replaced with mock `FinancialSnapshot` data (no real API calls)
- Generated briefing contains banner: `⚠️ DEV MODE — Data is simulated`
- All other data sources (vault/ directories) are read normally
- Files are still written to disk (not suppressed — use `--preview` for no writes)

## Idempotency

- Running `--generate-now` twice on the same day produces **one file** (second run warns and skips)
- `--force` flag overwrites the existing same-day briefing
- `briefing_exists_today()` checks `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md` using local-timezone date

## Safety Constraints

- Never modifies `vault/Done/`, `vault/Needs_Action/`, `vault/Approved/`, or `vault/Rejected/`
- Never calls external APIs other than Odoo (read-only)
- Always respects `DEV_MODE` flag (mock Odoo data, no real financial calls in dev)
- Always respects `--dry-run` flag (log actions, no file writes)
- Dashboard.md update uses sentinel pattern — never fully rewrites the dashboard
- `received` field in Needs_Action files is RFC 2822 format — NOT parsed; file mtime used for age
