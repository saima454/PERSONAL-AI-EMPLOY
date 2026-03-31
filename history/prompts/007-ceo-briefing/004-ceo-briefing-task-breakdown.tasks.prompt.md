---
id: "004"
title: "CEO Briefing Task Breakdown"
stage: tasks
date: 2026-02-24
surface: agent
model: claude-sonnet-4-6
feature: 007-ceo-briefing
branch: 007-ceo-briefing
user: PMLS
command: /sp.tasks
labels: ["ceo-briefing", "tasks", "gold-tier", "task-breakdown", "implementation-plan", "user-stories"]
links:
  spec: specs/007-ceo-briefing/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/007-ceo-briefing/tasks.md
tests:
  - null
---

## Prompt

/sp.tasks (Feature 007 — Weekly CEO Briefing Generator)

## Response snapshot

Generated `specs/007-ceo-briefing/tasks.md` with 32 tasks across 9 phases for Feature 007 (CEO Briefing Generator — Gold Tier).

**Prerequisites loaded**: plan.md, spec.md, research.md, data-model.md, quickstart.md — all complete.

**Phase structure** (9 phases, 32 tasks total):

- **Phase 1 — Setup** (T001–T004, 4 tasks): SKILL.md first (mandatory per spec), `backend/briefing/__init__.py` with all 10 dataclasses, `config/.env` + `.env.example` CEO_BRIEFING_* vars
- **Phase 2 — Foundational** (T005, 1 task): `BriefingScheduler` in `backend/briefing/scheduler.py` with zoneinfo/Asia/Karachi scheduling — required by US2 and US5
- **Phase 3 — US1 On-Demand** (T006–T015, 10 tasks): Full data collection pipeline (5 collectors + bottlenecks + suggestions), `ReportFormatter` (all 8 section methods), `BriefingGenerator` core + `generate_now` + `run_if_due` + CLI `--generate-now/--force` 🎯 MVP
- **Phase 4 — US2 Scheduled** (T016–T017, 2 tasks): `_check_briefing_schedule()` async hook + call in `Orchestrator.run()` after `_check_content_schedule()`
- **Phase 5 — US3 Preview** (T018–T019, 2 tasks): `preview()` method + `--preview` CLI flag
- **Phase 6 — US4 Custom Period** (T020–T021, 2 tasks): `period_days` propagation through full pipeline + `--period N` flag
- **Phase 7 — US5 Status** (T022–T023, 2 tasks): `status()` method + `--status` CLI flag
- **Phase 8 — Tests** (T024–T028, 5 tasks): 5 test classes (~50 tests): `TestBriefingScheduler` (8), `TestDataCollectors` (15), `TestReportFormatter` (12), `TestBriefingGenerator` (10), `TestOrchestratorIntegration` (5)
- **Phase 9 — Polish** (T029–T032, 4 tasks): quickstart.md Scenario 6 (idempotency), Scenario 7 (Odoo unavailable), Scenario 9 (DEV_MODE labeling), full pytest run

**Key parallel opportunities identified**:
- T003, T004 (config files): parallel
- T012 (report_formatter.py) parallel with T006–T011 (data_collectors.py) — different files
- T024, T025, T026 (test classes): parallel
- T029, T030, T031 (quickstart scenarios): parallel

**Critical research decisions encoded in task descriptions**:
- T008: `received` frontmatter is RFC 2822, use file `mtime` for age_days (not `parse_iso`)
- T009: confirmed action_type values — `email_detected`, `whatsapp_processed`, `linkedin_processed`, `twitter_post_published`
- T013: Dashboard update uses sentinel pattern `<!-- BRIEFING_SECTION_START -->` / `<!-- BRIEFING_SECTION_END -->`
- T016: lazy import BriefingGenerator inside `_check_briefing_schedule()` method

## Outcome

- ✅ Impact: Feature 007 task breakdown complete. 32 tasks across 9 phases, organized by user story priority (P1→P5). Each US independently testable. MVP = Phase 1+2+3 only (T001–T015). All critical research decisions from research.md encoded directly in task descriptions so implementer needs no additional context.
- 🧪 Tests: No implementation tests yet (tasks phase). Test strategy defined: 5 test classes, ~50 tests, `tmp_path` + `patch.object()` pattern; tests in Phase 8 (after implementation per spec.md order).
- 📁 Files: 1 new — specs/007-ceo-briefing/tasks.md (32 tasks, 9 phases)
- 🔁 Next prompts: `/sp.implement` to execute tasks in order (SKILL.md → backend/briefing/ → tests/ → orchestrator integration → .env updates)
- 🧠 Reflection: Encoding the RFC 2822 `received` field warning and exact action_type values directly in T008 and T009 descriptions is critical — without this, the implementer would need to re-read research.md. Task descriptions should be self-contained execution specs, not just labels.

## Evaluation notes (flywheel)

- Failure modes observed: check-prerequisites.ps1 with -RequireTasks flag fails because tasks.md doesn't exist yet — used -Json only (without -RequireTasks) to get FEATURE_DIR. This is expected behavior.
- Graders run and results (PASS/FAIL): Format validation — all 32 tasks follow checklist format (checkbox, T-ID, optional [P], optional [US], description with file path). All phases have checkpoint statements.
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): Run `uv run python -m backend.briefing.briefing_generator --status` immediately after implementing T005 (scheduler.py) to validate timezone logic before building full generator.
