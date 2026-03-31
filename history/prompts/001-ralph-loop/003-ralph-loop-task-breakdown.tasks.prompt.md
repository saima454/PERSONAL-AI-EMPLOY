---
id: "003"
title: Ralph Loop Task Breakdown
stage: tasks
date: 2026-02-24
surface: agent
model: claude-sonnet-4-6
feature: 001-ralph-loop
branch: 001-ralph-loop
user: PMLS
command: /sp.tasks
labels: ["ralph-wiggum","tasks","tdd","asyncio","state-machine","stop-hook","orchestrator","gold-tier"]
links:
  spec: specs/001-ralph-loop/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/001-ralph-loop/tasks.md
tests: []
---

## Prompt

/sp.tasks

Execute task generation workflow for feature 001-ralph-loop (Ralph Wiggum Loop). Generate tasks.md organized by user story from plan.md, spec.md, data-model.md, contracts/cli.md, quickstart.md, and research.md.

## Response snapshot

Ran check-prerequisites.ps1 with SPECIFY_FEATURE=001-ralph-loop (workaround for no-commits repo); confirmed FEATURE_DIR = specs/001-ralph-loop/ and all 6 design docs available.

Loaded all design docs from previous context (plan.md T001 order, spec.md 5 user stories with priorities, data-model.md 9 entities, contracts/cli.md 3 commands, quickstart.md 9 scenarios, research.md 10 decisions).

Spec explicitly requested tests ("Tests for loop logic, completion detection, timeout handling") — test tasks included BEFORE each story's implementation tasks.

**Generated tasks.md**: 33 tasks across 8 phases organized by user story:

| Phase | Task IDs | Count | US |
|-------|----------|-------|----|
| Setup | T001–T004 | 4 | — |
| Foundational | T005–T006 | 2 | — |
| US1 — Promise Loop | T007–T013 | 7 | P1 |
| US2 — File-Movement | T014–T016 | 3 | P2 |
| US3 — Safety Limits | T017–T020 | 4 | P3 |
| US4 — Status | T021–T023 | 3 | P4 |
| US5 — Stop Hook + Orchestrator | T024–T029 | 6 | P5 |
| Polish | T030–T033 | 4 | — |
| **TOTAL** | **T001–T033** | **33** | |

**~37 test cases** across 6 test classes: TestRalphConfig (4), TestStateManager (8), TestPromptInjector (4), TestFileMovement (4), TestSafetyLimits (8), TestStatus (6), TestStopHook (6), TestOrchestratorIntegration (5).

**Parallel opportunities**: T003/T004 (config files), T005/T006 (state_manager + prompt_injector), T007/T008/T009 (independent test classes), T030-T033 (validation scenarios).

**MVP scope**: Phases 1-3 (T001–T013) deliver fully working promise-based loop with state persistence and CLI.

**Implementation order enforced**: T001 = SKILL.md (Constitution Principle III mandatory); T002 = __init__.py dataclasses before state_manager imports; T005/T006 foundational before any loop logic; tests before each story's implementation.

## Outcome

- ✅ Impact: 33-task breakdown ready for /sp.implement — all tasks are independently executable, TDD-ordered (tests before implementation), organized by user story for incremental delivery
- 🧪 Tests: No tests run at tasks stage — ~37 test cases designed across 6 classes and recorded in tasks.md
- 📁 Files: 1 artifact created (specs/001-ralph-loop/tasks.md)
- 🔁 Next prompts: /sp.implement — execute T001–T033 in order; run MVP validation after T013 before continuing to US2
- 🧠 Reflection: SPECIFY_FEATURE=001-ralph-loop env var workaround is required for all scripts on this repo until the first git commit is made (git rev-parse --abbrev-ref HEAD fails with no commits; scripts fall back to highest-numbered spec dir which is 007, not 001). Document this in MEMORY.md.

## Evaluation notes (flywheel)

- Failure modes observed: check-prerequisites.ps1 requires SPECIFY_FEATURE env var workaround on repos with no commits (same issue as setup-plan.ps1 in PHR 002)
- Graders run and results (PASS/FAIL): Format validation — all 33 tasks follow `- [ ] T0xx [P?] [US?] Description with file path` checklist format PASS; dependency graph covers all phases PASS; parallel markers [P] on correct tasks PASS
- Prompt variant (if applicable): sp.tasks standard flow with all 6 design docs pre-loaded
- Next experiment (smallest change to try): /sp.implement — start with T001 (SKILL.md) then T002 (__init__.py); validate US1 MVP after T013
