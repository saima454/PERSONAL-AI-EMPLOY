---
id: 003
title: Smart Content Scheduler Tasks
stage: tasks
date: 2026-02-20
surface: agent
model: claude-sonnet-4-6
feature: 003-content-scheduler
branch: 003-content-scheduler
user: Taha
command: /sp.tasks
labels: ["content-scheduler","linkedin","tasks","tdd","orchestrator","action-executor","templates"]
links:
  spec: specs/003-content-scheduler/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/003-content-scheduler/tasks.md
tests:
  - null
---

## Prompt

/sp.tasks

(No additional arguments — generating tasks for current branch 003-content-scheduler)

## Response snapshot

Generated `specs/003-content-scheduler/tasks.md` with 38 tasks across 8 phases.

**Phase structure:**
- Phase 1 (Setup): T001–T004 — scaffold files, vault template, SKILL.md, env vars
- Phase 2 (Foundational): T005–T007 — shared dataclasses (blocking all stories)
- Phase 3 (US1 P1 MVP): T008–T017 — PostGenerator 25+ templates + ContentScheduler core + ScheduleManager I/O
- Phase 4 (US2): T018–T022 — PostingHistory, topic rotation (get_next_topic_index)
- Phase 5 (US3): T023–T027 — CLI flags (--generate-now, --preview, --status)
- Phase 6 (US4): T028–T030 — Orchestrator._check_content_schedule() + startup hook
- Phase 7 (US5): T031–T033 — Action executor _handle_linkedin_post() real impl + file lifecycle fix
- Phase 8 (Polish): T034–T038 — tests, mypy, ruff, e2e validation

**MVP scope**: T001–T017 (17 tasks — daily draft generation fully operational)

**Key task notes:**
- T010: 25 templates (5 topics × 5 formats) persona-specific to Taha
- T032+T033: Critical — replace NotImplementedError stub AND fix double-move bug
- T029–T030: Orchestrator async startup hook using asyncio.to_thread()
- 7 test tasks covering all acceptance scenarios from spec

## Outcome

- ✅ Impact: Complete, immediately executable task list — 38 tasks, 17 parallel opportunities, clear MVP boundary at Phase 3
- 🧪 Tests: 7 test tasks (T008, T009, T018, T019, T023, T028, T031) covering all spec acceptance criteria
- 📁 Files: specs/003-content-scheduler/tasks.md
- 🔁 Next prompts: `/sp.implement` to execute tasks | `/sp.adr content-generation-approach` to document template decision
- 🧠 Reflection: T033 (file lifecycle fix) is the most risk-prone task — double-move bug between ActionExecutor and LinkedInPoster would silently fail. Flagged prominently in tasks notes.

## Evaluation notes (flywheel)

- Failure modes observed: None during task generation
- Graders run and results (PASS/FAIL): Task format validation — all 38 tasks follow [checkbox][ID][P?][Story?][description+filepath] format
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): Run /sp.implement to start executing T001–T004 (Phase 1 Setup) immediately
