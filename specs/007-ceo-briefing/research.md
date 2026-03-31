# Research: Weekly CEO Briefing Generator

**Feature**: 007-ceo-briefing
**Phase**: Phase 0 — Technical Research
**Date**: 2026-02-24
**Status**: Complete

---

## Decision 1: Timezone-Aware Monday Check

**Decision**: Use Python stdlib `zoneinfo.ZoneInfo("Asia/Karachi")` for local-time scheduling.

**Rationale**: `tzdata>=2024.1` is already declared in `pyproject.toml` and installed — no new dependencies needed. `zoneinfo` is stdlib in Python 3.9+ and handles Windows correctly via the `tzdata` package. This avoids adding `pytz` or `arrow`.

**Implementation pattern**:
```python
from datetime import datetime
from zoneinfo import ZoneInfo

def is_briefing_due(day: str, time_str: str, tz_name: str) -> bool:
    """Return True if today (local) matches day and time >= configured time."""
    now_local = datetime.now(ZoneInfo(tz_name))
    configured_day = day.lower()          # e.g. "monday"
    day_names = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    if day_names[now_local.weekday()] != configured_day:
        return False
    h, m = map(int, time_str.split(":"))
    configured_time = now_local.replace(hour=h, minute=m, second=0, microsecond=0)
    return now_local >= configured_time
```

**Alternatives considered**:
- `pytz` — rejected; `zoneinfo` is stdlib and already covered by `tzdata` dep
- `arrow` — rejected; unnecessary new dependency
- UTC-only scheduling — rejected; user explicitly set `Asia/Karachi` and expects local-time Monday triggers

---

## Decision 2: Idempotency Check Pattern

**Decision**: Check for existence of `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md` using the LOCAL date in the configured timezone.

**Rationale**: The briefing filename contains the local date. A simple `Path.exists()` check is sufficient — no lock file or state file needed (unlike the content scheduler which tracks schedule state in JSON).

**Implementation pattern**:
```python
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

def briefing_exists_today(vault_path: Path, tz_name: str) -> bool:
    today_local = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d")
    filename = f"{today_local}_Monday_Briefing.md"
    return (vault_path / "Briefings" / filename).exists()
```

**Alternatives considered**:
- JSON state file (like content_scheduler) — rejected; simpler to check file existence since briefing filename is deterministic
- UTC date — rejected; would create wrong filename when local date differs from UTC

---

## Decision 3: Architecture Pattern — Follow ContentScheduler

**Decision**: Mirror the `ContentScheduler` pattern exactly for `BriefingGenerator`.

**Rationale**: `ContentScheduler` (`backend/scheduler/content_scheduler.py`) already establishes the project's canonical pattern for:
- `run_if_due()` — idempotency + schedule check → generate
- `generate_now()` — force generation ignoring schedule
- `preview()` — return data without writing files
- `status()` — return operational state
- `main()` + argparse CLI entry point
- Orchestrator integration via `await self._check_content_schedule()` in `orchestrator.py`

The CEO briefing adds `--period N` and uses multiple data collectors but is structurally identical. The orchestrator integration follows the exact same `await asyncio.to_thread(...)` pattern.

**Alternatives considered**:
- Separate daemon/scheduler process — rejected; constitution says use orchestrator's existing check loop
- APScheduler or schedule library — rejected; orchestrator startup check is sufficient and keeps the process count at 1

---

## Decision 4: Data Collection — No New Dependencies

**Decision**: All 7 data sources are accessible with existing project utilities. No new packages required.

| Source | Access method | Existing utility |
|--------|--------------|-----------------|
| Odoo | `OdooClient(dev_mode=...)` | `backend/mcp_servers/odoo/odoo_client.py` |
| vault/Done/ | `Path.glob("*.md")` + `parse_frontmatter()` | `backend/utils/frontmatter.py` |
| vault/Needs_Action/ | `Path.glob("*.md")` + `parse_frontmatter()` | `backend/utils/frontmatter.py` |
| vault/Pending_Approval/ | `Path.glob("*.md")` + `parse_frontmatter()` | `backend/utils/frontmatter.py` |
| vault/Logs/actions/ | `read_logs_for_date()` across date range | `backend/utils/logging_utils.py` |
| vault/Business_Goals.md | `extract_frontmatter()` + regex table parsing | `backend/utils/frontmatter.py` + stdlib `re` |
| vault/Content_Strategy.md | Plain text read | stdlib `pathlib` |

**Rationale**: All required tools (YAML, JSON, Path, regex) are already available. `pyyaml` is in dependencies. `OdooClient` is fully implemented in Feature 006.

---

## Decision 5: Done/ File Date Filtering

**Decision**: Filter `vault/Done/` files using `completed_at` frontmatter field (ISO 8601 UTC string). Fall back to file modification time (`Path.stat().st_mtime`) if `completed_at` is absent.

**Observed Done/ frontmatter fields** (from actual vault files):
```yaml
# ODOO_INVOICE_2026-02-22_E2E.md
completed_at: '2026-02-22T00:44:38Z'
type: odoo_invoice
status: done

# LINKEDIN_POST_2026-02-20.md
completed_at: '2026-02-19T22:39:46Z'
type: linkedin_post
status: done
```

**Implementation pattern**:
```python
from backend.utils.frontmatter import extract_frontmatter
from backend.utils.timestamps import parse_iso

def get_file_date(path: Path) -> datetime:
    content = path.read_text(encoding="utf-8")
    fm, _ = extract_frontmatter(content)
    ts = fm.get("completed_at") or fm.get("generated_at") or fm.get("approved_at")
    if ts:
        return parse_iso(str(ts))
    # Fallback: file modification time
    import os
    from datetime import UTC
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
```

---

## Decision 6: Log Scanning — Action Type Categories

**Decision**: Categorize `action_type` values in `vault/Logs/actions/*.json` into Communication Summary buckets.

**Observed action_type values** from vault:
- `twitter_post_published` → social_posts
- `orchestrator_start` / `orchestrator_stop` → system (excluded from communication summary)

**Category mapping** (confirmed from actual `vault/Logs/actions/*.json` files via research agent):

| Confirmed action_type value | Communication bucket |
|----------------------------|---------------------|
| `email_detected`, `email_processed`, `send_email` | emails_processed |
| `whatsapp_processed` | whatsapp_flagged |
| `linkedin_processed` | linkedin_flagged |
| `linkedin_post`, `twitter_post_published`, `facebook_post_published`, `instagram_post_published` | social_posts_published |
| `orchestrator_start`, `orchestrator_stop`, `watcher_stop`, `watcher_crash`, `watcher_restart` | system (excluded) |

**Important**: `received` field in Needs_Action email files uses RFC 2822 format (e.g., `Sat, 11 Oct 2025 03:50:07 +0000`), not ISO 8601. Do NOT call `parse_iso()` on it. Use file `mtime` for Needs_Action item age calculation.

**Implementation**: Scan all JSON files in `vault/Logs/actions/` whose filename (YYYY-MM-DD) falls within the review period, aggregate `action_type` counts per category. Use `startswith` prefix matching for forward-compatibility.

---

## Decision 7: Business Goals Parsing

**Decision**: Parse `vault/Business_Goals.md` using regex for the Revenue Targets markdown table and Key Results table.

**Rationale**: The existing `Business_Goals.md` template uses a consistent Markdown table format. The CEO briefing extracts the target vs. current values from these tables. If the file is empty (placeholder), the collector returns `None` and the briefing notes "Business Goals not yet configured."

**Revenue Targets table format** (from actual file):
```markdown
| Metric | Target | Current | Gap |
|--------|--------|---------|-----|
| Monthly Revenue | $[X] | $[Y] | $[Z] |
```

**Implementation**: Use `re.findall(r'\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|', table_content)` to parse rows.

---

## Decision 8: Dashboard Update Strategy

**Decision**: Append/replace a `## Latest Briefing` section at the top of `vault/Dashboard.md` using a sentinel comment pattern.

**Rationale**: `vault/Dashboard.md` is written by `backend/orchestrator/dashboard.py` using a full-rewrite pattern. The briefing generator must NOT fully rewrite Dashboard.md (would erase orchestrator content). Instead, it prepends or updates only its own section using a sentinel:

```markdown
<!-- BRIEFING_SECTION_START -->
## Latest Briefing
- **File**: vault/Briefings/2026-02-24_Monday_Briefing.md
- **Generated**: 2026-02-24T08:01:23Z
- **Period**: 2026-02-17 to 2026-02-24
- **Summary**: Revenue $1,000 | 3 tasks completed | 0 pending
<!-- BRIEFING_SECTION_END -->
```

If the sentinel is absent (first run), the section is prepended. If present, it is replaced.

---

## Decision 9: Orchestrator Integration Point

**Decision**: Add `await self._check_briefing_schedule()` call in `Orchestrator.run()` immediately after `await self._check_content_schedule()`.

**Rationale**: This follows the exact pattern established by `_check_content_schedule()`. The method:
1. Imports `BriefingGenerator` lazily
2. Calls `generator.run_if_due()` via `asyncio.to_thread()` (sync method in async context)
3. Logs result; never raises (all exceptions caught and logged as WARNING)

This means the Monday check fires once on orchestrator startup — sufficient for the use case since orchestrators typically restart daily or are always running.

---

## Decision 10: No HITL Required

**Decision**: CEO Briefing generation requires NO HITL approval workflow.

**Rationale**: Constitution Principle IV states HITL is required for: payments to new recipients, amounts >$100, bulk sends, account modifications, public social posts, contracts. CEO Briefing is a **local read + local write** operation — it reads vault data and Odoo (read-only calls: `list_invoices`, `get_account_balance`, `list_transactions`) and writes a Markdown file to `vault/Briefings/`. No external actions. This is equivalent to content scheduler draft generation, which also has no HITL.

---

## Decision 11: File Module Structure

**Decision**: 4-file `backend/briefing/` module as specified, with clean separation of concerns.

```
briefing_generator.py  → BriefingGenerator class (orchestrates: config → collect → format → write)
data_collectors.py     → DataCollectors class (7 static collector methods, one per source)
report_formatter.py    → ReportFormatter class (takes BriefingData → returns Markdown string)
scheduler.py           → BriefingScheduler (is_due, has_briefing_today, next_run_str, status_check)
```

**Key insight from ContentScheduler**: Keep all "is this due?" logic in the scheduler module, all "what data?" logic in collectors, all "how does it look?" logic in formatter, and orchestration in generator. This mirrors the `content_scheduler / schedule_manager / post_generator` split.

---

## Alternatives Considered (Rejected)

| Alternative | Reason Rejected |
|-------------|----------------|
| LLM-generated briefing prose via Claude API | Spec explicitly states "deterministic templates + real data", not LLM prose. Adds API cost and latency. |
| APScheduler as standalone cron | Would require a separate always-running process. Constitution says use orchestrator. |
| SQLite for briefing state | Overkill — file existence check is sufficient for idempotency. |
| Separate CLI script (not a module) | Project convention: modules with `__main__.py` or `main()` function, not standalone scripts. |
| `pytz` for timezone | `zoneinfo` + `tzdata` already in deps, no reason to add `pytz`. |
