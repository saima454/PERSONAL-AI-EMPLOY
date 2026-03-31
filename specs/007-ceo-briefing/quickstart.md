# Quickstart: CEO Briefing Generator

**Feature**: 007-ceo-briefing
**Purpose**: Integration test scenarios for validating all 5 user stories
**Date**: 2026-02-24

---

## Setup

```bash
# Ensure Odoo env vars are set for live testing
# In config/.env:
# ODOO_URL=http://localhost:8069
# ODOO_DATABASE=ai_employee
# ODOO_USERNAME=twahaahmed130@gmail.com
# ODOO_API_KEY=MyOdoopass1996
# CEO_BRIEFING_DAY=monday
# CEO_BRIEFING_TIME=08:00
# CEO_BRIEFING_TIMEZONE=Asia/Karachi
# CEO_BRIEFING_PERIOD_DAYS=7
# DEV_MODE=true   (for safe testing)

# Install deps (already done)
uv sync
```

---

## Scenario 1: On-Demand Generation (US1, DEV_MODE)

**Goal**: Verify briefing is generated with mock data, all 7 sections present, file saved.

```bash
# Run with mock Odoo data
DEV_MODE=true uv run python -m backend.briefing.briefing_generator --generate-now

# Expected output:
# ✅ Briefing generated: vault/Briefings/2026-02-24_Monday_Briefing.md
# Period: 2026-02-17 to 2026-02-24 (7 days)
# Sources: [odoo(mock), vault_done, vault_logs, vault_needs_action, business_goals]
```

**Verify**:
```bash
# Check file exists and has all 7 sections
cat "vault/Briefings/2026-02-24_Monday_Briefing.md"
# Must contain:
# --- frontmatter with type: ceo_briefing ---
# ## Executive Summary
# ## Revenue & Financial Health
# ## Completed Tasks This Week
# ## Pending Items
# ## Communication Summary
# ## Bottlenecks & Delays
# ## Proactive Suggestions
```

**Expected vault changes**:
- `vault/Briefings/2026-02-24_Monday_Briefing.md` — created
- `vault/Dashboard.md` — updated with Latest Briefing block
- `vault/Logs/actions/2026-02-24.json` — new `briefing_generated` entry

---

## Scenario 2: On-Demand Generation (US1, LIVE MODE)

**Goal**: Verify real Odoo financial data appears in briefing.

```bash
# Live Odoo data
DEV_MODE=false uv run python -m backend.briefing.briefing_generator --generate-now --force

# Expected: Revenue & Financial Health shows:
# - Real invoice data (e.g., INV/2026/00001, $1,000)
# - Real bank balance from Odoo account id=13
# - Outstanding invoices count
```

**Verify**:
```bash
grep -A 10 "## Revenue" "vault/Briefings/2026-02-24_Monday_Briefing.md"
# Should show non-zero values from Odoo
```

---

## Scenario 3: Preview Mode (US3)

**Goal**: Verify `--preview` produces console output without creating any files.

```bash
# Capture file list before
BEFORE=$(find vault/Briefings/ -name "*.md" | wc -l)
DASH_BEFORE=$(cat vault/Dashboard.md | md5sum)

DEV_MODE=true uv run python -m backend.briefing.briefing_generator --preview

# Verify no files changed
AFTER=$(find vault/Briefings/ -name "*.md" | wc -l)
DASH_AFTER=$(cat vault/Dashboard.md | md5sum)

echo "Briefings before: $BEFORE, after: $AFTER  (must be equal)"
echo "Dashboard hash before: $DASH_BEFORE"
echo "Dashboard hash after:  $DASH_AFTER  (must match)"
```

**Expected console output** (preview prints all 7 sections):
```
[PREVIEW] CEO Briefing — Period: 2026-02-17 to 2026-02-24
[PREVIEW] ---
# Monday Morning CEO Briefing
## Executive Summary
...
[PREVIEW] --- No files written.
```

---

## Scenario 4: Custom Period (US4)

**Goal**: Verify `--period 30` generates a 30-day briefing with correct date range.

```bash
DEV_MODE=true uv run python -m backend.briefing.briefing_generator --generate-now --period 30
```

**Verify**:
```bash
# Check frontmatter period
python3 -c "
import yaml, re
content = open('vault/Briefings/2026-02-24_Monday_Briefing.md').read()
fm = yaml.safe_load(re.match(r'^---\n(.*?)\n---', content, re.DOTALL).group(1))
print('period_days:', fm['period_days'])  # must be 30
print('period_start:', fm['period_start'])  # must be ~2026-01-25
"
```

---

## Scenario 5: Status Check (US5)

**Goal**: Verify `--status` shows operational info without generating files.

```bash
DEV_MODE=true uv run python -m backend.briefing.briefing_generator --status

# Expected output:
# CEO Briefing Status
# ==========================================
# Last briefing : 2026-02-24_Monday_Briefing.md
# Last generated: 2026-02-24T03:01:00Z
# Next scheduled: Monday 2026-03-02 08:00 PKT
# Due today     : NO
# vault/Briefings/: ✓ exists
# vault/Done/     : ✓ exists
# vault/Logs/     : ✓ exists
# Odoo            : ✓ reachable (or DEV_MODE)
```

---

## Scenario 6: Idempotency (FR-019)

**Goal**: Verify running `--generate-now` twice without `--force` doesn't create a second file.

```bash
DEV_MODE=true uv run python -m backend.briefing.briefing_generator --generate-now
DEV_MODE=true uv run python -m backend.briefing.briefing_generator --generate-now

# Expected second run output:
# ⚠️  Briefing already exists for 2026-02-24. Use --force to overwrite.

# File should exist exactly once:
ls vault/Briefings/ | grep 2026-02-24
# → 2026-02-24_Monday_Briefing.md (only one file)
```

---

## Scenario 7: Odoo Unavailable (FR-022 Graceful Degradation)

**Goal**: Verify briefing is generated even when Odoo is unreachable.

```bash
# Point to non-existent Odoo
ODOO_URL=http://localhost:9999 DEV_MODE=false uv run python -m backend.briefing.briefing_generator --generate-now --force
```

**Expected**: Briefing file is still created. The "Revenue & Financial Health" section contains:
```markdown
## Revenue & Financial Health
> ⚠️ Odoo unavailable — financial data could not be retrieved.
> Error: Connection refused (http://localhost:9999)
> All other sections reflect current vault data.
```

---

## Scenario 8: Orchestrator Monday Check

**Goal**: Verify the orchestrator calls `_check_briefing_schedule()` on startup.

```bash
# Check orchestrator logs for briefing check
DEV_MODE=true uv run python -m backend.orchestrator &
sleep 5
pkill -f "backend.orchestrator"

# Check log output contains:
grep "briefing" vault/Logs/actions/$(date +%Y-%m-%d).json
# → entry with action_type: briefing_checked or briefing_generated or briefing_skipped
```

---

## Scenario 9: DEV_MODE Labeling (FR-020)

**Goal**: Verify DEV_MODE briefing is clearly labeled.

```bash
DEV_MODE=true uv run python -m backend.briefing.briefing_generator --generate-now --force
grep "DEV MODE" vault/Briefings/2026-02-24_Monday_Briefing.md
# → Must find: ⚠️ DEV MODE — Data is simulated
```

---

## Quick Validation Checklist

After running all scenarios, verify:

- [ ] `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md` — created with all 7 sections
- [ ] Frontmatter has `type: ceo_briefing`, `period_start`, `period_end`, `period_days`, `sources`
- [ ] `vault/Dashboard.md` — updated with `<!-- BRIEFING_SECTION_START -->` block
- [ ] `vault/Logs/actions/YYYY-MM-DD.json` — contains `briefing_generated` entry
- [ ] `--preview` produces no file changes
- [ ] `--period 30` produces correct date range in frontmatter
- [ ] `--status` shows last/next run without generating
- [ ] Idempotency: second `--generate-now` warns and skips
- [ ] Odoo unavailable: briefing still saves with warning in financial section
- [ ] DEV_MODE: briefing labeled as simulated
