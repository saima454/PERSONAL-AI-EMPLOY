# Feature Specification: Weekly CEO Briefing Generator

**Feature Branch**: `007-ceo-briefing`
**Created**: 2026-02-22
**Updated**: 2026-02-24
**Status**: Ready for Planning
**Input**: "Weekly CEO Briefing Generator (Gold Tier) — autonomous CEO Briefing system that audits all activity and generates a comprehensive weekly report every Monday at 8 AM."

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — On-Demand Briefing Generation (Priority: P1)

The CEO runs `--generate-now` and within 60 seconds receives a complete, structured briefing saved to `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md`. The report covers the last 7 days (default), includes real Odoo financials, vault task summaries, log analysis, and AI-generated suggestions. `vault/Dashboard.md` is updated with a link.

**Why this priority**: Core value proposition — without this working, nothing else matters. All other stories depend on the underlying data collection and formatting pipeline built here.

**Independent Test**: Run `--generate-now` against a vault with sample data and DEV_MODE Odoo mock; verify a correctly structured Markdown file with YAML frontmatter appears in `vault/Briefings/`.

**Acceptance Scenarios**:

1. **Given** vault contains `Done/`, `Logs/actions/`, `Needs_Action/`, `Business_Goals.md`, **When** `--generate-now` is run, **Then** a file `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md` appears with all 7 sections populated within 60 seconds.
2. **Given** Odoo is reachable (`DEV_MODE=false`), **When** `--generate-now` is run, **Then** "Revenue & Financial Health" shows real invoice totals, MTD revenue, outstanding invoices, and bank balance from Odoo for the past 7 days.
3. **Given** Odoo is unreachable, **When** `--generate-now` is run, **Then** the briefing is still generated with "Odoo unavailable — financial data omitted" in the financial section; no crash occurs.
4. **Given** `vault/Business_Goals.md` has Revenue Targets and Key Results, **When** briefing is generated, **Then** Executive Summary and financial section reference those targets (e.g., "MTD Revenue: $X,XXX — 75% of monthly target").
5. **Given** `DEV_MODE=true`, **When** `--generate-now` is run, **Then** briefing is generated with mock data and the document header states "⚠️ DEV MODE — Data is simulated".
6. **Given** a briefing for today already exists, **When** `--generate-now` is run without `--force`, **Then** existing file is preserved and a warning is shown; with `--force` it is overwritten.

---

### User Story 2 — Automated Monday 8 AM Schedule (Priority: P2)

The orchestrator detects on startup (or periodic check) that it is Monday and no briefing has been generated yet for this week. It automatically invokes the briefing generator without human intervention. The CEO opens their Obsidian vault Monday morning to find a fresh briefing.

**Why this priority**: "Autonomous" is the product promise. The Monday auto-generation differentiates this from a manual reporting script.

**Independent Test**: Set `CEO_BRIEFING_DAY=monday`, start orchestrator on a Monday before configured time, advance system clock past `CEO_BRIEFING_TIME`, verify briefing appears in `vault/Briefings/` without any manual command.

**Acceptance Scenarios**:

1. **Given** it is Monday and `vault/Briefings/` has no file dated this Monday, **When** the orchestrator runs its Monday check, **Then** briefing generation is triggered automatically.
2. **Given** a briefing already exists for this Monday, **When** the orchestrator checks again, **Then** generation is skipped (idempotent).
3. **Given** the system was offline during `CEO_BRIEFING_TIME=08:00`, **When** orchestrator next starts on the same Monday, **Then** a late briefing is generated with a note: "Generated late — scheduled for 08:00, generated at HH:MM."
4. **Given** `CEO_BRIEFING_TIMEZONE=Asia/Karachi` (UTC+5), **When** Monday arrives at 08:00 PKT, **Then** the briefing triggers correctly in local time, not UTC.

---

### User Story 3 — Preview Mode (Priority: P3)

The CEO or developer runs `--preview` to see the complete briefing content printed to console without writing any files or modifying `vault/Dashboard.md`. Useful for verifying data sources and output format before enabling the automated schedule.

**Why this priority**: Safe onboarding — essential for testing configuration without polluting the vault.

**Independent Test**: Run `--preview`, verify full briefing renders to console, verify no file created in `vault/Briefings/`, verify `vault/Dashboard.md` is unchanged.

**Acceptance Scenarios**:

1. **Given** `--preview` is run, **Then** full briefing with all 7 sections is printed to stdout and NO file is written to `vault/Briefings/`.
2. **Given** `--preview` is run, **Then** `vault/Dashboard.md` is NOT modified.
3. **Given** `--preview --period 30` is run, **Then** console output shows 30-day data ranges in section headers.

---

### User Story 4 — Custom Period Analysis (Priority: P4)

The CEO runs `--period N` to generate a briefing covering any lookback window (e.g., `--period 30` for monthly review, `--period 90` for quarterly). All data sections — Odoo transactions, completed tasks, log activity — respect the custom date range.

**Why this priority**: Monthly and quarterly management reviews are standard practice and significantly extend the tool's utility.

**Independent Test**: Run `--period 30`, verify the report header shows a 30-day date range and Odoo `list_transactions` is called with the correct `date_from` parameter.

**Acceptance Scenarios**:

1. **Given** `--period 30`, **When** briefing is generated, **Then** frontmatter shows `period: YYYY-MM-DD to YYYY-MM-DD` spanning 30 days, and all data collection functions receive that range.
2. **Given** `--period 1`, **When** briefing is generated, **Then** a valid 24-hour briefing is produced without errors.
3. **Given** `--period 0` or negative value, **When** briefing is invoked, **Then** system defaults to 7 days and logs a config warning.

---

### User Story 5 — System Status Check (Priority: P5)

The operator runs `--status` to inspect system health: last briefing timestamp, path of most recent briefing, next scheduled generation time, and connectivity check for each data source (Odoo, vault directories).

**Why this priority**: Operational visibility for autonomous agents is non-negotiable in a production environment.

**Independent Test**: Run `--status`, verify structured output with last-run time, next-run time, and Odoo connectivity indicator appears without any file being created.

**Acceptance Scenarios**:

1. **Given** a prior briefing exists, **When** `--status` is run, **Then** output shows: last run timestamp, path of most recent briefing, next scheduled time, vault directory presence (Done ✓, Logs ✓, etc.), and Odoo connectivity.
2. **Given** no prior briefing exists, **When** `--status` is run, **Then** output states "No briefings generated yet" and the next scheduled run time.
3. **Given** `--status` is run, **Then** no briefing is generated and no files are modified.

---

### Edge Cases

- **`vault/Business_Goals.md` absent** → Briefing is generated without KPI comparison; Executive Summary notes "Business Goals not configured — add `vault/Business_Goals.md` to enable KPI tracking."
- **`vault/Done/` empty for the period** → "Completed Tasks" section reports "No tasks completed in this period."
- **`vault/Needs_Action/` empty** → "Pending Items" reports "No pending items."
- **Odoo returns partial data** → Partial data included with per-field warning; briefing not blocked.
- **`vault/Briefings/` does not exist** → Auto-created before first write.
- **All vault folders empty** → Briefing is generated with all sections showing zero-state messages; no crash.
- **`CEO_BRIEFING_PERIOD_DAYS` env var set** → Used as default period when `--period` flag not supplied.
- **`vault/Pending_Approval/` files present** → Included in "Pending Items" section alongside `vault/Needs_Action/`.
- **Large vault with 1000+ log entries** → System processes efficiently without timeout; summarises by category rather than listing every entry.

---

## Output Format *(canonical template)*

Every generated briefing MUST follow this structure exactly:

```markdown
---
generated: YYYY-MM-DDTHH:MM:SSZ
period: YYYY-MM-DD to YYYY-MM-DD
type: ceo_briefing
period_days: 7
sources: [odoo, vault_done, vault_logs, vault_needs_action, business_goals]
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
- [x] Task 1 — completed date
- [x] Task 2 — completed date

## Pending Items
- [ ] Item 1 — waiting since date
- [ ] Item 2 — waiting since date

## Communication Summary
- **Emails processed**: X (X replied, X archived)
- **WhatsApp messages**: X flagged
- **LinkedIn messages**: X flagged
- **Social media posts**: X published this week

## Bottlenecks & Delays
| Task | Expected | Actual | Delay |
|------|----------|--------|-------|

## Proactive Suggestions
### Cost Optimization
- [Suggestions based on transaction analysis]

### Upcoming Deadlines
- [From Business_Goals.md]

### Recommendations
- [AI-generated suggestions based on observed patterns]

---
*Generated by AI Employee v1.0*
```

---

## Requirements *(mandatory)*

### Functional Requirements

**Data Collection**

- **FR-001**: System MUST read `vault/Business_Goals.md` (if present) and extract revenue targets, KPIs, and upcoming deadlines for use in Executive Summary and Proactive Suggestions.
- **FR-002**: System MUST query Odoo via `odoo_client.py` for: invoices created/paid in the period, outstanding invoice total, payments received, and current bank account balance.
- **FR-003**: System MUST scan `vault/Done/` for files with `completed_at` or `moved_at` timestamps within the review period and list them as Completed Tasks.
- **FR-004**: System MUST scan `vault/Logs/actions/*.json` for all action entries within the review period and produce a Communication Summary (email sends, WhatsApp flags, LinkedIn flags, social posts).
- **FR-005**: System MUST scan `vault/Needs_Action/` and `vault/Pending_Approval/` for all current pending items and list them in the Pending Items section with age (days waiting).
- **FR-006**: System MUST detect bottlenecks by identifying: tasks in `Needs_Action/` older than 48 hours, repeated failed actions in logs, and any action type appearing more than 3 times in the period without resolution.

**Report Generation**

- **FR-007**: System MUST generate a briefing file at `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md` (where the date is the generation date) with YAML frontmatter containing: `generated`, `period`, `type: ceo_briefing`, `period_days`, `sources`.
- **FR-008**: System MUST include all 7 sections in every briefing: Executive Summary, Revenue & Financial Health, Completed Tasks This Week, Pending Items, Communication Summary, Bottlenecks & Delays, Proactive Suggestions.
- **FR-009**: System MUST update `vault/Dashboard.md` with a "Latest Briefing" block containing the filename, generation timestamp, and a one-line summary after each successful generation.
- **FR-010**: System MUST generate at least one actionable Proactive Suggestion in the Proactive Suggestions section based on observed patterns (cost, deadlines, or operational recommendations).

**CLI & Configuration**

- **FR-011**: System MUST support `--generate-now` flag for immediate on-demand generation.
- **FR-012**: System MUST support `--preview` flag: render briefing to console without writing any files.
- **FR-013**: System MUST support `--period N` flag to override the default lookback window (N integer days, default from `CEO_BRIEFING_PERIOD_DAYS` env var, fallback 7).
- **FR-014**: System MUST support `--status` flag to report last run, next scheduled run, and data source connectivity without generating a briefing.
- **FR-015**: System MUST support `--force` flag to overwrite an existing same-day briefing file.
- **FR-016**: System MUST be configurable via environment variables: `CEO_BRIEFING_DAY` (default `monday`), `CEO_BRIEFING_TIME` (default `08:00`), `CEO_BRIEFING_TIMEZONE` (default `Asia/Karachi`), `CEO_BRIEFING_PERIOD_DAYS` (default `7`).

**Scheduling & Integration**

- **FR-017**: System MUST integrate with the orchestrator via a Monday check: on each orchestrator cycle, if `CEO_BRIEFING_DAY` matches today and no briefing exists for today, trigger generation.
- **FR-018**: System MUST support invocation via Windows Task Scheduler (every Monday at `CEO_BRIEFING_TIME`) as an alternative scheduling mechanism.
- **FR-019**: System MUST be idempotent: running generator multiple times on the same day produces one file unless `--force` is specified.

**Safety & Reliability**

- **FR-020**: System MUST respect `DEV_MODE=true` — use mock/sample data for all Odoo calls and label output clearly as simulated.
- **FR-021**: System MUST log every generation run (start, end, sources used, errors) to `vault/Logs/actions/` using the existing logging infrastructure.
- **FR-022**: System MUST gracefully degrade: if any individual data source fails, include the partial data with an inline warning rather than aborting the entire briefing.

**Implementation Order**

The implementation MUST follow this order:
1. `skills/ceo-briefing/SKILL.md` — complete skill documentation first
2. `backend/briefing/` module — all four source files
3. `tests/` — test files for data collection, formatting, and scheduling

### Key Entities

- **Briefing Report**: Output artifact with YAML frontmatter, 7 sections, stored as `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md`.
- **Financial Snapshot**: Aggregated Odoo data for the period — weekly revenue, MTD revenue, outstanding invoices, payments received, bank balance, trend assessment.
- **Completed Task Entry**: A `vault/Done/` file within the review period — has title, completion timestamp, and category derived from frontmatter.
- **Pending Item**: A `vault/Needs_Action/` or `vault/Pending_Approval/` file — has title, age in days, priority from frontmatter.
- **Communication Event**: A single action log entry of type `email_send`, `email_reply`, `whatsapp_flag`, `linkedin_flag`, or `social_post`.
- **Bottleneck**: A heuristically detected delay — task age > 48h, or repeated failure type in logs, or unresolved action type > 3 occurrences.
- **Business Goal**: A revenue target or KPI from `vault/Business_Goals.md` — has metric name, target value, current value, and status.
- **Briefing Schedule**: Config tuple `(day, time, timezone)` controlling automated generation timing.

### Architecture

```
backend/briefing/
├── __init__.py              # Package init; exports BriefingGenerator
├── briefing_generator.py    # Orchestrates: calls collectors → formatter → writes vault
├── data_collectors.py       # 7 collector functions, one per data source
├── report_formatter.py      # Formats collected data into the canonical Markdown template
└── scheduler.py             # Monday check logic + --status + Windows Task Scheduler helper

skills/ceo-briefing/
└── SKILL.md                 # Full skill documentation (created first)
```

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `--generate-now` completes and saves a file to `vault/Briefings/` in under 60 seconds when all data sources are available.
- **SC-002**: The automated Monday check triggers generation within 5 minutes of the configured time in `Asia/Karachi` timezone without manual intervention.
- **SC-003**: 100% of generated briefings contain all 7 required sections, even in degraded mode (some data sources unavailable).
- **SC-004**: Briefings are idempotent — same-day double invocation results in exactly one file (no `--force`) or one updated file (with `--force`).
- **SC-005**: `vault/Dashboard.md` is updated with the latest briefing link within 5 seconds of every successful generation.
- **SC-006**: System handles complete Odoo unavailability without crashing — briefing is still saved with a financial section warning.
- **SC-007**: `--preview` produces no side effects — zero vault file writes, zero `Dashboard.md` changes.
- **SC-008**: All acceptance criteria checkboxes from the feature description are satisfied:
  - `briefing_generator.py` orchestrates all data collection
  - `data_collectors.py` with one collector per data source (7 sources)
  - `report_formatter.py` generates Markdown following the canonical template
  - Real Odoo data via `odoo_client.py`
  - Vault folder scanning for completed/pending tasks
  - Log analysis for communication summary
  - Proactive suggestions based on patterns
  - All 4 CLI flags functional (`--generate-now`, `--preview`, `--period`, `--status`)
  - Orchestrator Monday check integrated
  - `vault/Briefings/` output with proper YAML frontmatter
  - `vault/Dashboard.md` updated after each generation
  - Tests for data collection, formatting, and scheduling
  - `skills/ceo-briefing/SKILL.md` present

---

## Data Collection Sources

| # | Source | File/API | Data Collected |
|---|--------|----------|---------------|
| 1 | Odoo MCP | `backend/mcp_servers/odoo/odoo_client.py` | Revenue, invoices (created/paid), payments received, account balance |
| 2 | Completed tasks | `vault/Done/*.md` | Titles + completion timestamps within review period |
| 3 | Pending items | `vault/Needs_Action/*.md` | Titles + age (days since creation) |
| 4 | Pending approvals | `vault/Pending_Approval/*.md` | Titles + age |
| 5 | Action logs | `vault/Logs/actions/*.json` | Email/WhatsApp/LinkedIn/social event counts by type |
| 6 | Business goals | `vault/Business_Goals.md` | Revenue targets, Key Results, upcoming deadlines |
| 7 | Content strategy | `vault/Content_Strategy.md` | Social posting activity context |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CEO_BRIEFING_DAY` | `monday` | Day of week for auto-generation |
| `CEO_BRIEFING_TIME` | `08:00` | Time for auto-generation (24-hour, local) |
| `CEO_BRIEFING_TIMEZONE` | `Asia/Karachi` | Timezone for scheduling (UTC+5) |
| `CEO_BRIEFING_PERIOD_DAYS` | `7` | Default lookback window in days |

---

## Dependencies

- **Feature 006 (Odoo MCP)**: `backend/mcp_servers/odoo/odoo_client.py` — required for financial data collection.
- **Feature 002 (Orchestrator)**: `backend/orchestrator/orchestrator.py` — Monday check hook added here.
- **Feature 002 (Utils)**: `backend/utils/frontmatter.py`, `backend/utils/logging_utils.py`, `backend/utils/timestamps.py` — used by all collectors.
- **Vault structure**: `vault/Done/`, `vault/Logs/actions/`, `vault/Needs_Action/`, `vault/Pending_Approval/` — must exist (created by prior features).

---

## Assumptions

- `vault/Business_Goals.md` uses YAML frontmatter + Markdown tables as shown in the existing template; the parser reads the Revenue Targets table and Key Results table.
- Communication Summary is derived from existing `vault/Logs/actions/*.json` entries written by email/WhatsApp/social watchers — no new communication integration needed.
- "Bottleneck detection" is heuristic (age-based + frequency-based), not ML-based.
- The `--status` connectivity check for Odoo is a lightweight `authenticate()` call, not a full data pull.
- Generated briefing files are read-only artifacts; humans read them in Obsidian but do not edit them.
- `vault/Briefings/` directory is created automatically if missing.

---

## Out of Scope

- Emailing or WhatsApp-delivering the briefing (vault file only in this feature).
- LLM-generated narrative prose (all sections use deterministic templates + real data).
- Multi-user or role-based access to briefings.
- Trend comparison across multiple weeks (future Platinum tier).
- Interactive web dashboard.
