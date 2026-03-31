# Tasks: Weekly CEO Briefing Generator

**Feature**: 007-ceo-briefing
**Input**: Design documents from `/specs/007-ceo-briefing/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, quickstart.md ✅

**Implementation Order** (from spec.md — MUST follow):
1. `skills/ceo-briefing/SKILL.md` — complete skill documentation first
2. `backend/briefing/` module — all four source files
3. `tests/test_ceo_briefing.py` — tests for data collection, formatting, and scheduling

**Organization**: Tasks grouped by user story to enable independent delivery and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no intra-task file conflicts)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths included in all task descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: SKILL.md first (mandatory per spec), package skeleton, and env configuration.

- [x] T001 Create `skills/ceo-briefing/SKILL.md` with complete skill documentation — trigger phrases ("generate briefing", "CEO briefing", "weekly report"), inputs (vault path, period, timezone), outputs (`vault/Briefings/YYYY-MM-DD_Monday_Briefing.md`, `vault/Dashboard.md`), CLI commands (`--generate-now`, `--preview`, `--period N`, `--status`, `--force`), DEV_MODE behavior, data sources (7 sources), orchestrator integration note, and example usage
- [x] T002 Create `backend/briefing/__init__.py` defining all 10 dataclasses: `BriefingConfig`, `BriefingData`, `FinancialSnapshot`, `CompletedTask`, `PendingItem`, `CommunicationSummary`, `BottleneckEntry`, `BusinessGoals`, `BriefingRunResult`, `BriefingStatusResult` — include all fields from `specs/007-ceo-briefing/data-model.md`; use `@dataclass` with `field(default_factory=...)` for lists; export `BriefingGenerator` (lazy import or forward ref)
- [x] T003 [P] Add `CEO_BRIEFING_DAY=monday`, `CEO_BRIEFING_TIME=08:00`, `CEO_BRIEFING_TIMEZONE=Asia/Karachi`, `CEO_BRIEFING_PERIOD_DAYS=7` to `config/.env`
- [x] T004 [P] Add documented `CEO_BRIEFING_DAY`, `CEO_BRIEFING_TIME`, `CEO_BRIEFING_TIMEZONE`, `CEO_BRIEFING_PERIOD_DAYS` entries with descriptions and defaults to `config/.env.example`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: `BriefingScheduler` — required by both the orchestrator hook (US2) and `--status` (US5). Must be complete before US2 or US5 implementation begins.

**⚠️ CRITICAL**: US2 (`_check_briefing_schedule`) and US5 (`--status`) cannot proceed until T005 is complete.

- [x] T005 Implement `BriefingScheduler` class in `backend/briefing/scheduler.py` — methods: `is_briefing_due() -> bool` (today_local matches configured day AND now_local >= configured_time AND `briefing_exists_today()` is False), `briefing_exists_today() -> bool` (check `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md` using local-timezone date), `most_recent_briefing() -> Path | None` (newest .md in vault/Briefings/), `next_run_str() -> str` (returns e.g. "Monday 2026-03-02 08:00 PKT"), `local_now() -> datetime` (datetime.now(ZoneInfo(tz_name))); use `from zoneinfo import ZoneInfo` — falls back to UTC with WARNING on invalid timezone name

**Checkpoint**: Scheduler module complete — US2 and US5 can now proceed independently.

---

## Phase 3: User Story 1 — On-Demand Briefing Generation (Priority: P1) 🎯 MVP

**Goal**: `--generate-now` produces a complete `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md` with all 7 sections, correct YAML frontmatter, and `vault/Dashboard.md` updated via sentinel pattern. Idempotent: second run warns and skips without `--force`.

**Independent Test**: `DEV_MODE=true uv run python -m backend.briefing.briefing_generator --generate-now` → file created in `vault/Briefings/` with `type: ceo_briefing` frontmatter, all 7 sections present, Dashboard.md updated with `<!-- BRIEFING_SECTION_START -->` block.

### Implementation for User Story 1

- [x] T006 [US1] Implement `DataCollectors.collect_financial()` in `backend/briefing/data_collectors.py` — instantiate `OdooClient(url, db, username, api_key, dev_mode=dev_mode)` from env vars; call `odoo.authenticate()`, `odoo.list_invoices(limit=100, status="posted")`, `odoo.get_account_balance(account_id)`, `odoo.list_transactions(date_from, date_to)`; filter invoices by `invoice_date` in period; sum `amount_total` for `weekly_revenue`; calculate `mtd_revenue` from month start; populate `FinancialSnapshot` with trend logic (Ahead ≥100%, On track 75–99%, Behind <75%); return `(FinancialSnapshot, None)` on success or `(None, error_str)` on any exception; DEV_MODE returns a realistic mock `FinancialSnapshot` without calling Odoo
- [x] T007 [US1] Implement `DataCollectors.collect_completed_tasks()` in `backend/briefing/data_collectors.py` — glob `vault/Done/*.md` (skip dotfiles); for each file read text, call `extract_frontmatter(content)` from `backend.utils.frontmatter`; get timestamp from `completed_at` frontmatter (call `parse_iso()` from `backend.utils.timestamps`) OR fall back to `datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)`; filter `period_start <= completed_at.date() <= period_end`; extract H1 heading from body (`re.search(r'^# (.+)', body, re.MULTILINE)`) or use `path.stem`; populate `CompletedTask`; return sorted by `completed_at`
- [x] T008 [US1] Implement `DataCollectors.collect_pending_items()` in `backend/briefing/data_collectors.py` — glob both `vault/Needs_Action/*.md` and `vault/Pending_Approval/*.md` (skip dotfiles); for each file read frontmatter; use `Path.stat().st_mtime` for `created_at` (do NOT use `received` frontmatter — it is RFC 2822 format, not ISO 8601); calculate `age_days = (today_date - mtime_date).days`; read `priority` frontmatter (default `"medium"`); read `subject` frontmatter or H1 or filename as `title`; read `type` frontmatter; set `vault_folder` from parent dir name
- [x] T009 [US1] Implement `DataCollectors.collect_communication_summary()` in `backend/briefing/data_collectors.py` — iterate each date from `period_start` to `period_end`; call `read_logs_for_date(log_dir, date.isoformat())` from `backend.utils.logging_utils`; for each entry call `_categorize_action(action_type)` with prefix-matching: `email_detected`/`email_processed`/`send_email` → `"emails_processed"`; `whatsapp_processed` → `"whatsapp_flagged"`; `linkedin_processed` → `"linkedin_flagged"`; `twitter_post_published`/`linkedin_post`/`facebook_post_published`/`instagram_post_published` → `"social_posts_published"`; system types (`orchestrator_start`, `orchestrator_stop`, `watcher_*`, `briefing_*`) → `None` (excluded); unknown types → `None`; aggregate counts and return `CommunicationSummary`
- [x] T010 [US1] Implement `DataCollectors.collect_business_goals()` in `backend/briefing/data_collectors.py` — read `vault/Business_Goals.md`; return `None` if file absent; parse YAML frontmatter; parse Revenue Targets markdown table via `re.findall(r'\|([^|]+)\|([^|]+)\|([^|]+)\|([^|]+)\|', content)` to extract metric/target/current/gap rows; skip rows where target contains `[` or `$[` (placeholder); parse `monthly_revenue_target` and `new_clients_target` as numeric; return `BusinessGoals` with `raw_text=content[:1000]`; return `None` if all targets are placeholders
- [x] T011 [US1] Implement `DataCollectors.detect_bottlenecks()` and `DataCollectors.generate_suggestions()` in `backend/briefing/data_collectors.py` — bottleneck rules: (1) any `PendingItem` with `age_days >= 2` → `BottleneckEntry(bottleneck_type="age")`; (2) any `action_type` prefix appearing 3+ times without corresponding completion → `BottleneckEntry(bottleneck_type="frequency")`; (3) zero completed tasks this period despite any pending items → `BottleneckEntry(bottleneck_type="pattern")`; suggestions: always at least one string based on data (e.g. pending item count, financial trend, social activity gaps, upcoming deadlines from business goals)
- [x] T012 [P] [US1] Implement `ReportFormatter` in `backend/briefing/report_formatter.py` — static `format(data: BriefingData) -> str` assembles: (a) YAML frontmatter block with `generated`, `period`, `period_start`, `period_end`, `period_days`, `type: ceo_briefing`, `sources`, `dev_mode`; (b) `# Monday Morning CEO Briefing` header (prepend `⚠️ DEV MODE — Data is simulated\n\n` if `data.dev_mode`); (c) all 7 sections using private static methods; financial section shows `> ⚠️ Odoo unavailable...` block if `data.financial is None`; completed tasks uses `- [x] Title — YYYY-MM-DD` format; pending items uses `- [ ] Title — waiting X days`; bottlenecks uses markdown table `| Task | Reason | Age |`; all sections present even with zero data (zero-state messages: "No tasks completed in this period", etc.); footer `*Generated by AI Employee v1.0*`
- [x] T013 [US1] Implement `BriefingGenerator.__init__()`, `_generate_briefing()`, `_write_briefing()`, `_update_dashboard()`, `_log_run()` in `backend/briefing/briefing_generator.py` — `__init__` loads `BriefingConfig` from env; `_generate_briefing(period_days)` calls all `DataCollectors` methods, assembles `BriefingData`, calls `ReportFormatter.format(data)`; `_write_briefing(content, path)` creates `vault/Briefings/` if missing, writes file; `_update_dashboard(data, briefing_path)` reads `vault/Dashboard.md`, applies sentinel replacement (`<!-- BRIEFING_SECTION_START -->` / `<!-- BRIEFING_SECTION_END -->`) using `re.sub(re.DOTALL)`, prepends if sentinel absent; `_log_run(result)` calls `log_action(action_type="briefing_generated", ...)` from `backend.utils.logging_utils`
- [x] T014 [US1] Implement `BriefingGenerator.generate_now()` and `BriefingGenerator.run_if_due()` in `backend/briefing/briefing_generator.py` — `generate_now(period_days=None, force=False)`: if not force and briefing file exists → return `BriefingRunResult(status="skipped", reason="already exists")`; otherwise create `vault/Briefings/` dir, call `_generate_briefing()`, `_write_briefing()`, `_update_dashboard()`, `_log_run()`; return `BriefingRunResult(status="generated", briefing_path=path, ...)`; `run_if_due()`: call `BriefingScheduler.is_briefing_due()`; if not due → return `BriefingRunResult(status="skipped", reason="not due")`; otherwise call `generate_now()`; all exceptions caught → return `BriefingRunResult(status="error", reason=str(exc))`
- [x] T015 [US1] Implement `main()` CLI entry point with `--generate-now` and `--force` flags in `backend/briefing/briefing_generator.py` — load `.env` via `python_dotenv.load_dotenv("config/.env")`; `argparse.ArgumentParser` with mutually exclusive group for `--generate-now`, `--preview`, `--status`; `--period N` (int); `--force` (store_true); `if __name__ == "__main__": main()`; module docstring enables `python -m backend.briefing.briefing_generator`

**Checkpoint**: US1 MVP complete — `DEV_MODE=true uv run python -m backend.briefing.briefing_generator --generate-now` produces a valid briefing with all 7 sections.

---

## Phase 4: User Story 2 — Automated Monday Schedule (Priority: P2)

**Goal**: Orchestrator detects Monday ≥ 08:00 PKT on startup, auto-generates briefing if none exists today. Idempotent — second orchestrator start on same Monday skips silently.

**Independent Test**: Start orchestrator on a test Monday date (mocked); verify `briefing_checked` or `briefing_generated` entry appears in `vault/Logs/actions/YYYY-MM-DD.json` without any manual CLI command.

### Implementation for User Story 2

- [x] T016 [US2] Add `_check_briefing_schedule()` async method to `Orchestrator` class in `backend/orchestrator/orchestrator.py` — lazy import `from backend.briefing.briefing_generator import BriefingGenerator` inside method; instantiate generator with `vault_path=self.vault_path`, `dev_mode=self.config.dev_mode`, `dry_run=self.config.dry_run`; call `result = await asyncio.to_thread(generator.run_if_due)`; log `INFO` if `result.status == "generated"`; log `DEBUG` otherwise; wrap entire body in `try/except Exception as exc` → log `WARNING` with exc message; method never raises
- [x] T017 [US2] Add `await self._check_briefing_schedule()` call in `Orchestrator.run()` in `backend/orchestrator/orchestrator.py` — place immediately after the existing `await self._check_content_schedule()` call; no other changes to `run()`

**Checkpoint**: US2 complete — orchestrator integration working; Monday check fires on every startup.

---

## Phase 5: User Story 3 — Preview Mode (Priority: P3)

**Goal**: `--preview` prints complete briefing Markdown to stdout with `[PREVIEW]` prefix. No files written. No `vault/Dashboard.md` modification. Works with optional `--period N`.

**Independent Test**: Record `vault/Briefings/` file count and `vault/Dashboard.md` mtime before `--preview`; both unchanged after. Console output contains all 7 section headers.

### Implementation for User Story 3

- [x] T018 [US3] Implement `BriefingGenerator.preview()` method in `backend/briefing/briefing_generator.py` — call `_generate_briefing(period_days)` to collect data and format; print `[PREVIEW] CEO Briefing — Period: {start} to {end}` header; print `[PREVIEW] ---`; print the formatted markdown; print `[PREVIEW] --- No files written.` footer; do NOT call `_write_briefing()`, `_update_dashboard()`, or `_log_run()`
- [x] T019 [US3] Wire `--preview` CLI flag to `BriefingGenerator.preview()` in `main()` of `backend/briefing/briefing_generator.py` — in the argparse mutual-exclusion group; accepts combined `--preview --period N`; exits 0 after printing

**Checkpoint**: US3 complete — `--preview` flag safe for zero-side-effect testing of data collection and formatting.

---

## Phase 6: User Story 4 — Custom Period Analysis (Priority: P4)

**Goal**: `--period N` overrides the 7-day default for ALL data collection. Frontmatter shows correct `period_start`, `period_end`, `period_days`. Invalid values (≤ 0) default to 7 with a log warning.

**Independent Test**: `--generate-now --period 30` produces a briefing with `period_days: 30` in frontmatter and `period_start` date 30 days before today.

### Implementation for User Story 4

- [x] T020 [US4] Propagate `period_days` parameter from `BriefingConfig` through the full pipeline in `backend/briefing/briefing_generator.py` and `backend/briefing/data_collectors.py` — `BriefingConfig.period_days` loaded from `CEO_BRIEFING_PERIOD_DAYS` env var (validate > 0; default 7 with WARNING if ≤ 0); `generate_now(period_days=None)` uses arg if provided, else `self.config.period_days`; `_generate_briefing(period_days)` computes `period_end = local_date_today`, `period_start = period_end - timedelta(days=period_days-1)`; passes `period_start` and `period_end` to all collector methods (`collect_completed_tasks`, `collect_communication_summary`, `collect_financial`)
- [x] T021 [US4] Wire `--period N` CLI flag to `period_days` parameter in `main()` of `backend/briefing/briefing_generator.py` — `parser.add_argument("--period", type=int, default=None, metavar="N")`; pass to `generate_now(period_days=args.period)` or `preview(period_days=args.period)`

**Checkpoint**: US4 complete — custom period date range appears correctly in generated briefing frontmatter and section headers.

---

## Phase 7: User Story 5 — System Status Check (Priority: P5)

**Goal**: `--status` outputs a structured health report: last briefing path, generation timestamp, next scheduled run, vault directory presence, Odoo connectivity. No files created or modified.

**Independent Test**: Run `--status`; verify stdout shows "No briefings yet" (or last path), next Monday run time, and vault directory checkmarks; confirm no file changes in vault.

### Implementation for User Story 5

- [x] T022 [US5] Implement `BriefingGenerator.status()` method in `backend/briefing/briefing_generator.py` — use `BriefingScheduler` to get `most_recent_briefing()`, `next_run_str()`, `is_briefing_due()`; check existence of `vault/Done/`, `vault/Briefings/`, `vault/Logs/actions/`; attempt lightweight Odoo `authenticate()` ping (skip in DEV_MODE — set `odoo_reachable=None`); return `BriefingStatusResult` with all fields populated
- [x] T023 [US5] Wire `--status` CLI flag to `BriefingGenerator.status()` in `main()` of `backend/briefing/briefing_generator.py` — format `BriefingStatusResult` as a human-readable block: `CEO Briefing Status`, last briefing path (or "No briefings generated yet"), next scheduled time, `Due today: YES/NO`, vault dir ✓/✗ indicators, Odoo reachable ✓/✗ or "DEV_MODE"; exit 0

**Checkpoint**: US5 complete — all 4 CLI flags (`--generate-now`, `--preview`, `--period`, `--status`) fully functional. Full feature delivered.

---

## Phase 8: Tests

**Purpose**: Test suite covering data collection, formatting, and scheduling per spec.md implementation order (tests after implementation).

- [x] T024 [P] Write `TestBriefingScheduler` (8 tests) in `tests/test_ceo_briefing.py` — (1) `is_briefing_due()` returns True on correct day + time; (2) returns False on wrong weekday; (3) returns False before configured time; (4) returns False if briefing already exists (`briefing_exists_today()` mock); (5) `briefing_exists_today()` True when file present in tmp_path; (6) False when absent; (7) `next_run_str()` format includes weekday name + date + time + tz abbreviation; (8) `local_now()` returns tz-aware datetime in configured zone
- [x] T025 [P] Write `TestDataCollectors` (15 tests) in `tests/test_ceo_briefing.py` — use `tmp_path` for all vault I/O; (1-3) `collect_completed_tasks`: files in period included, files outside excluded, mtime fallback when no completed_at; (4-5) `collect_pending_items`: age_days uses mtime not received field, both Needs_Action and Pending_Approval included; (6-8) `collect_communication_summary`: prefix match for email_detected, whatsapp_processed excluded from total, system types excluded; (9-10) `collect_financial`: DEV_MODE returns FinancialSnapshot without Odoo call, exception returns (None, error_str); (11-12) `collect_business_goals`: placeholder value returns None, valid table returns BusinessGoals with numeric targets; (13-14) `detect_bottlenecks`: age>=2 triggers age bottleneck, zero completed tasks triggers pattern bottleneck; (15) `generate_suggestions`: always returns at least one suggestion
- [x] T026 [P] Write `TestReportFormatter` (12 tests) in `tests/test_ceo_briefing.py` — use minimal `BriefingData` instances; (1) DEV_MODE banner present in output; (2) No DEV_MODE banner when dev_mode=False; (3) All 7 section headers present; (4) YAML frontmatter has all required fields (generated, period, type, period_days, sources); (5) Financial unavailable block present when financial=None; (6) "No tasks completed" message when completed_tasks=[]; (7) "No pending items" message when pending_items=[]; (8) Completed tasks formatted as `- [x] Title — date`; (9) Pending items formatted as `- [ ] Title — waiting N days`; (10) Bottlenecks table has header row; (11) Proactive suggestions section not empty; (12) Footer `*Generated by AI Employee v1.0*` present
- [x] T027 Write `TestBriefingGenerator` (10 tests) in `tests/test_ceo_briefing.py` — use `tmp_path` as vault; (1) `generate_now()` creates file in vault/Briefings/; (2) second `generate_now()` without force returns status="skipped"; (3) `generate_now(force=True)` overwrites existing file; (4) `preview()` returns None, no file created; (5) `run_if_due()` returns status="skipped" when not Monday (mock BriefingScheduler); (6) `run_if_due()` calls generate_now() when due; (7) Dashboard.md updated with sentinel block after generate_now; (8) Dashboard sentinel replaced (not appended) on second generate; (9) log_action called with action_type="briefing_generated"; (10) `generate_now()` returns status="error" on DataCollector exception without crashing
- [x] T028 Write `TestOrchestratorIntegration` (5 tests) in `tests/test_ceo_briefing.py` — (1) `_check_briefing_schedule()` returns None and does not raise on success; (2) logs INFO when briefing generated; (3) logs DEBUG when briefing skipped; (4) catches any exception and logs WARNING without raising; (5) calls `asyncio.to_thread` with `generator.run_if_due`

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Quickstart validation scenarios and final edge case verification.

- [x] T029 [P] Validate quickstart.md Scenario 6 (idempotency): run `--generate-now` twice without `--force`; verify second run exits with warning message "Briefing already exists" and exactly one file in `vault/Briefings/` matching today's date
- [x] T030 [P] Validate quickstart.md Scenario 7 (Odoo unavailable): set `ODOO_URL=http://localhost:9999`, run `--generate-now --force`; verify briefing file still created and "Revenue & Financial Health" section contains `⚠️ Odoo unavailable` block
- [x] T031 [P] Validate quickstart.md Scenario 9 (DEV_MODE labeling): run `DEV_MODE=true --generate-now --force`; verify generated file contains `⚠️ DEV MODE — Data is simulated` text
- [x] T032 Run full test suite `uv run pytest tests/test_ceo_briefing.py -v` and confirm all 50 tests pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on T002 (dataclasses in `__init__.py` must exist before scheduler uses them)
- **US1 (Phase 3)**: Depends on Phase 2 complete; T006–T011 sequential (same file); T012 [P] with T006–T011 (different file); T013 depends on T011 AND T012; T014 depends on T013; T015 depends on T014
- **US2 (Phase 4)**: Depends on Phase 3 complete (generator must exist); T005 (scheduler) must be done
- **US3 (Phase 5)**: Depends on T013–T014 (core pipeline); `preview()` extends existing generator
- **US4 (Phase 6)**: Depends on Phase 3 complete (period_days propagated through existing pipeline)
- **US5 (Phase 7)**: Depends on T005 (scheduler) and T013 (generator `__init__`)
- **Tests (Phase 8)**: Depends on all implementation phases complete (T001–T023)
- **Polish (Phase 9)**: Depends on Tests (Phase 8) — T032 specifically requires T024–T028

### Within Phase 3 (US1) — Sequential Within Same File

```
data_collectors.py: T006 → T007 → T008 → T009 → T010 → T011
report_formatter.py: T012  [P with T006–T011 — different file]
briefing_generator.py: T013 (needs T011 + T012 done) → T014 → T015
```

### Parallel Opportunities

| Tasks | Parallel? | Reason |
|-------|-----------|--------|
| T003, T004 | ✅ Yes | Different config files |
| T005 vs T006–T012 | ✅ Partial | scheduler.py vs data_collectors.py+report_formatter.py |
| T012 vs T006–T011 | ✅ Yes | report_formatter.py vs data_collectors.py |
| T016 vs T018 | ✅ Yes | Different: orchestrator.py vs briefing_generator.py |
| T024, T025, T026 | ✅ Yes | Different test classes, same file (write independently, merge) |
| T029, T030, T031 | ✅ Yes | Independent validation scenarios |

---

## Parallel Execution Example: Phase 3

```bash
# Agent A — data_collectors.py (sequential within file):
T006 collect_financial → T007 collect_completed_tasks → T008 collect_pending_items
→ T009 collect_communication_summary → T010 collect_business_goals
→ T011 detect_bottlenecks + generate_suggestions

# Agent B — simultaneously (different file):
T012 report_formatter.py — all 8 section formatters

# After both agents complete:
T013 briefing_generator.py core pipeline → T014 generate_now/run_if_due → T015 main() CLI
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Phase 1: Setup (T001–T004)
2. Phase 2: Foundational — scheduler.py (T005)
3. Phase 3: US1 full pipeline (T006–T015)
4. **STOP and VALIDATE**: `DEV_MODE=true uv run python -m backend.briefing.briefing_generator --generate-now`
5. Confirm file at `vault/Briefings/YYYY-MM-DD_Monday_Briefing.md` with all 7 sections

### Full Delivery Order

| Phase | Delivers | Validate With |
|-------|----------|---------------|
| 1 + 2 | SKILL.md, dataclasses, scheduler | `python -m backend.briefing.briefing_generator --status` |
| 3 (US1) | `--generate-now` + `--force` | `DEV_MODE=true --generate-now` → file in vault/Briefings/ |
| 4 (US2) | Orchestrator Monday hook | Start orchestrator → check vault/Logs/actions/ for briefing entry |
| 5 (US3) | `--preview` | `--preview` → console output, no files |
| 6 (US4) | `--period N` | `--period 30` → frontmatter shows period_days: 30 |
| 7 (US5) | `--status` | `--status` → structured health output |
| 8 | Test suite (50 tests) | `uv run pytest tests/test_ceo_briefing.py -v` |
| 9 | Quickstart validation | All quickstart.md scenarios pass |

---

## Task Summary

| Phase | Task IDs | Count | US |
|-------|----------|-------|----|
| Setup | T001–T004 | 4 | — |
| Foundational | T005 | 1 | — |
| US1 — On-Demand | T006–T015 | 10 | P1 |
| US2 — Scheduled | T016–T017 | 2 | P2 |
| US3 — Preview | T018–T019 | 2 | P3 |
| US4 — Custom Period | T020–T021 | 2 | P4 |
| US5 — Status | T022–T023 | 2 | P5 |
| Tests | T024–T028 | 5 | — |
| Polish | T029–T032 | 4 | — |
| **TOTAL** | **T001–T032** | **32** | |

**~50 test cases** distributed across 5 test classes (T024–T028).

---

## Notes

- **SKILL.md must be T001** — spec.md explicitly requires skill documentation before any code
- **data_collectors.py tasks are sequential** (same file, single agent) despite being independent logically
- **`received` frontmatter in Needs_Action/**: RFC 2822 format (not ISO 8601) — use `mtime` for age_days (research.md Decision 6, confirmed from vault)
- **action_type prefix matching** (research.md Decision 6): confirmed actual values are `email_detected`, `email_processed`, `send_email`, `whatsapp_processed`, `linkedin_processed`, `twitter_post_published`
- **Dashboard.md**: never fully rewritten — sentinel pattern preserves orchestrator content across Dashboard rewrites
- **Tests use `tmp_path`** pytest fixture for isolated vault I/O; `patch.object()` for OdooClient mocking (not `monkeypatch`)
- **No new dependencies**: all packages already in `pyproject.toml` (`pyyaml`, `tzdata`, `python-dotenv`, `zoneinfo` stdlib)
- **Commit points**: T001 (SKILL.md), T005 (scheduler), T015 (US1 complete), T017 (US2 complete), T023 (all CLIs), T028 (tests pass), T032 (quickstart validation)
