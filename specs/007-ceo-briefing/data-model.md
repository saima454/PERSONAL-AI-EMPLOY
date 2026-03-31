# Data Model: Weekly CEO Briefing Generator

**Feature**: 007-ceo-briefing
**Phase**: Phase 1 — Design
**Date**: 2026-02-24

---

## Entities

### 1. BriefingConfig
Configuration loaded from environment variables and defaults.

| Field | Type | Source | Default |
|-------|------|--------|---------|
| `vault_path` | `Path` | `VAULT_PATH` env | `./vault` |
| `briefing_day` | `str` | `CEO_BRIEFING_DAY` env | `"monday"` |
| `briefing_time` | `str` | `CEO_BRIEFING_TIME` env | `"08:00"` |
| `briefing_timezone` | `str` | `CEO_BRIEFING_TIMEZONE` env | `"Asia/Karachi"` |
| `period_days` | `int` | `CEO_BRIEFING_PERIOD_DAYS` env | `7` |
| `dev_mode` | `bool` | `DEV_MODE` env | `True` |
| `dry_run` | `bool` | `DRY_RUN` env | `False` |

**Validation rules**:
- `period_days` must be > 0; if 0 or negative, default to 7 and log WARNING
- `briefing_timezone` must be a valid IANA timezone name; if invalid, fall back to `UTC` and log WARNING
- `briefing_time` must match `HH:MM` format (24-hour)

---

### 2. BriefingData
The complete collected data for one briefing period. Passed from `DataCollectors` to `ReportFormatter`.

| Field | Type | Description |
|-------|------|-------------|
| `period_start` | `date` | First day of the review period (inclusive) |
| `period_end` | `date` | Last day of the review period (inclusive, = generation date) |
| `generated_at` | `datetime` | UTC timestamp of generation |
| `financial` | `FinancialSnapshot \| None` | Odoo financial data; `None` if Odoo unavailable |
| `financial_error` | `str \| None` | Error message if Odoo failed |
| `completed_tasks` | `list[CompletedTask]` | Tasks from `vault/Done/` in period |
| `pending_items` | `list[PendingItem]` | Items from `vault/Needs_Action/` + `vault/Pending_Approval/` |
| `communication` | `CommunicationSummary` | Counts from `vault/Logs/actions/` |
| `bottlenecks` | `list[BottleneckEntry]` | Detected delays/patterns |
| `business_goals` | `BusinessGoals \| None` | Parsed from `vault/Business_Goals.md`; `None` if absent |
| `suggestions` | `list[str]` | Generated suggestion strings |
| `dev_mode` | `bool` | Whether DEV_MODE was active during generation |

---

### 3. FinancialSnapshot
Financial data collected from Odoo for the review period.

| Field | Type | Description |
|-------|------|-------------|
| `weekly_revenue` | `float` | Sum of `amount_total` for invoices with `invoice_date` in period |
| `mtd_revenue` | `float` | Sum of `amount_total` for invoices from 1st of month to period_end |
| `monthly_target` | `float \| None` | From `Business_Goals.md` Monthly Revenue target; `None` if not set |
| `mtd_pct_of_target` | `float \| None` | `(mtd_revenue / monthly_target) * 100` if target known |
| `outstanding_invoices_count` | `int` | Number of unpaid posted invoices |
| `outstanding_invoices_total` | `float` | Sum of outstanding invoice amounts |
| `payments_received_count` | `int` | Payments logged in period |
| `payments_received_total` | `float` | Sum of payment amounts in period |
| `bank_balance` | `float` | Current bank account balance |
| `receivables_balance` | `float` | Current receivables account balance |
| `trend` | `str` | `"On track"` / `"Behind"` / `"Ahead"` based on mtd_pct_of_target |
| `currency` | `str` | Currency code from Odoo (e.g., `"USD"`) |

**Trend logic**:
- `Ahead` if `mtd_pct_of_target >= 100`
- `On track` if `75 <= mtd_pct_of_target < 100`
- `Behind` if `mtd_pct_of_target < 75`
- `Unknown` if `monthly_target` is None

---

### 4. CompletedTask
A task from `vault/Done/` completed within the review period.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `title` | `str` | File H1 heading or filename | Human-readable task title |
| `completed_at` | `datetime` | `completed_at` frontmatter (fallback: file mtime) | When the task was marked done |
| `completed_date` | `str` | `completed_at.date().isoformat()` | Display date |
| `task_type` | `str` | `type` frontmatter | e.g., `odoo_invoice`, `linkedin_post`, `email_reply` |
| `source_file` | `str` | Filename | e.g., `ODOO_INVOICE_2026-02-22_E2E.md` |

**Date filtering rule**: Include if `period_start <= completed_at.date() <= period_end`.

---

### 5. PendingItem
A file in `vault/Needs_Action/` or `vault/Pending_Approval/` awaiting human attention.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `title` | `str` | `subject` frontmatter or H1 or filename | Item description |
| `item_type` | `str` | `type` frontmatter | e.g., `email`, `linkedin_post`, `odoo_invoice` |
| `priority` | `str` | `priority` frontmatter | `high`, `medium`, `low`; default `medium` |
| `vault_folder` | `str` | `"Needs_Action"` or `"Pending_Approval"` | Which vault folder |
| `created_at` | `datetime \| None` | `received` or `generated_at` frontmatter; fallback file ctime | When item appeared |
| `age_days` | `int` | `(today - created_at.date()).days` | How many days waiting |
| `source_file` | `str` | Filename | For reference |

**Bottleneck threshold**: `age_days >= 2` (48 hours) flags the item as a bottleneck candidate.

---

### 6. CommunicationSummary
Aggregated counts from `vault/Logs/actions/*.json` for the period.

| Field | Type | Confirmed action_type values (from vault logs) |
|-------|------|------------------------------------------------|
| `emails_processed` | `int` | `email_detected`, `email_processed`, `send_email` |
| `whatsapp_flagged` | `int` | `whatsapp_processed` |
| `linkedin_flagged` | `int` | `linkedin_processed` |
| `social_posts_published` | `int` | `twitter_post_published`, `linkedin_post`, `facebook_post_published`, `instagram_post_published` |
| `total_actions` | `int` | All non-system entries |

**Excluded from counts** (system events): `orchestrator_start`, `orchestrator_stop`, `watcher_stop`, `watcher_crash`, `watcher_restart`, `briefing_generated`, `briefing_checked`.

**Log scanning**: Iterate `vault/Logs/actions/YYYY-MM-DD.json` files for all dates in the period. Parse `entries[].action_type`. Use prefix matching (`startswith`) for forward-compatibility as new action types are added.

**Needs_Action file age**: Since `Needs_Action` files have `received` in RFC 2822 format (not ISO 8601), use file `mtime` (`Path.stat().st_mtime`) as the creation proxy for age calculation.

---

### 7. BottleneckEntry
A detected delay or problematic pattern.

| Field | Type | Description |
|-------|------|-------------|
| `item` | `str` | Task or action description |
| `reason` | `str` | Why it's flagged (e.g., "Waiting 5 days in Needs_Action") |
| `age_days` | `int \| None` | For age-based bottlenecks |
| `frequency` | `int \| None` | For frequency-based bottlenecks |
| `bottleneck_type` | `str` | `"age"` / `"frequency"` / `"pattern"` |

**Detection rules**:
1. **Age-based**: Any `PendingItem` with `age_days >= 2` → bottleneck
2. **Frequency-based**: Any `action_type` prefix appearing 3+ times in period without corresponding `*_done` completion → bottleneck candidate (e.g., 5 email drafts, 0 email sends)
3. **Pattern**: Zero tasks completed this period despite active watchers → bottleneck

---

### 8. BusinessGoals
Parsed from `vault/Business_Goals.md`. Returns `None` if file absent or all targets are placeholder strings.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `monthly_revenue_target` | `float \| None` | Revenue Targets table | Monthly Revenue target (numeric) |
| `new_clients_target` | `int \| None` | Revenue Targets table | New clients target |
| `key_results` | `list[KeyResult]` | Key Results table | OKR key results |
| `upcoming_deadlines` | `list[Deadline]` | Key Initiatives | Initiatives with future deadlines |
| `raw_text` | `str` | First 1000 chars | For fallback display |

**Parsing rule**: If the target value is a placeholder (contains `[` or `$[` or is empty), treat as `None`.

---

### 9. BriefingRunResult
Return value from `generate_now()` / `run_if_due()`.

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | `"generated"` / `"skipped"` / `"error"` |
| `briefing_path` | `Path \| None` | Path to generated file; `None` if skipped/error |
| `period_start` | `str \| None` | ISO date of period start |
| `period_end` | `str \| None` | ISO date of period end |
| `reason` | `str` | Human-readable explanation |

---

### 10. BriefingStatusResult
Return value from `status()` CLI command.

| Field | Type | Description |
|-------|------|-------------|
| `last_briefing_path` | `Path \| None` | Most recent briefing file path |
| `last_briefing_date` | `str \| None` | Date of last briefing |
| `next_scheduled` | `str` | Human-readable next run time (e.g., "Monday 2026-03-02 08:00 PKT") |
| `is_due_today` | `bool` | Whether a briefing should run today |
| `briefings_dir_exists` | `bool` | `vault/Briefings/` present |
| `done_dir_exists` | `bool` | `vault/Done/` present |
| `logs_dir_exists` | `bool` | `vault/Logs/actions/` present |
| `odoo_reachable` | `bool \| None` | Result of lightweight Odoo ping; `None` if DEV_MODE |

---

## Entity Relationships

```
BriefingConfig ──── configures ────► BriefingGenerator
                                          │
                              ┌───────────┴───────────────────┐
                              ▼                               ▼
                      DataCollectors                   BriefingScheduler
                              │                               │
        ┌─────────────────────┼──────────┐            is_briefing_due()
        ▼                     ▼          ▼            briefing_exists()
 FinancialSnapshot   [CompletedTask]  [PendingItem]   next_run_str()
 CommunicationSummary BusinessGoals  [BottleneckEntry]
        │
        └─────────────────────► BriefingData
                                       │
                               ReportFormatter
                                       │
                               Markdown string
                                       │
                            vault/Briefings/YYYY-MM-DD_Monday_Briefing.md
```

---

## State Transitions

### Briefing File Lifecycle

```
[Not generated]
      │
      │ run_if_due() or generate_now()
      ▼
[vault/Briefings/YYYY-MM-DD_Monday_Briefing.md] — final state (read-only artifact)
```

No state transitions after creation. Briefing files are immutable artifacts. `--force` creates a new file (same name, overwritten).

### Orchestrator Integration

```
Orchestrator.run() starts
      │
      ├── _check_content_schedule()   (existing)
      │
      └── _check_briefing_schedule()  (NEW — Feature 007)
               │
               ├── is Monday AND time >= 08:00 PKT AND no briefing today?
               │       └── YES → run_if_due() → generate → log
               │       └── NO  → log DEBUG "briefing not due"
               └── Done (never raises)
```

---

## Vault File Schema (Generated Output)

### `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md`

```yaml
---
generated: "2026-02-24T03:01:00Z"    # UTC ISO 8601
period: "2026-02-17 to 2026-02-24"   # Human-readable
period_start: "2026-02-17"            # ISO date
period_end: "2026-02-24"              # ISO date
period_days: 7
type: ceo_briefing
sources:
  - odoo
  - vault_done
  - vault_logs
  - vault_needs_action
  - vault_pending_approval
  - business_goals
dev_mode: false
---
```

### Dashboard Update Block

Written to `vault/Dashboard.md` between sentinel comments:

```markdown
<!-- BRIEFING_SECTION_START -->
## Latest Briefing
- **Date**: 2026-02-24 (Monday)
- **File**: vault/Briefings/2026-02-24_Monday_Briefing.md
- **Period**: 2026-02-17 to 2026-02-24
- **Revenue this week**: $1,000.00
- **Tasks completed**: 3
- **Pending items**: 2
- **Generated**: 2026-02-24T03:01:00Z
<!-- BRIEFING_SECTION_END -->
```
