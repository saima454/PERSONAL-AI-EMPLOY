---
id: "004"
title: Ralph Loop Implementation
stage: green
date: 2026-02-24
surface: agent
model: claude-sonnet-4-6
feature: 001-ralph-loop
branch: 001-ralph-loop
user: PMLS
command: /sp.implement
labels: ["ralph-wiggum","asyncio","stop-hook","state-machine","tdd","orchestrator","45-tests","green","gold-tier"]
links:
  spec: specs/001-ralph-loop/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - skills/ralph-wiggum/SKILL.md
  - backend/ralph_wiggum/__init__.py
  - backend/ralph_wiggum/__main__.py
  - backend/ralph_wiggum/ralph_loop.py
  - backend/ralph_wiggum/state_manager.py
  - backend/ralph_wiggum/prompt_injector.py
  - backend/ralph_wiggum/stop_hook.py
  - .claude/settings.json
  - config/.env
  - config/.env.example
  - backend/orchestrator/orchestrator.py
  - tests/test_ralph_loop.py
  - specs/001-ralph-loop/tasks.md
tests:
  - tests/test_ralph_loop.py::TestRalphConfig (4 tests)
  - tests/test_ralph_loop.py::TestStateManager (8 tests)
  - tests/test_ralph_loop.py::TestPromptInjector (4 tests)
  - tests/test_ralph_loop.py::TestFileMovement (4 tests)
  - tests/test_ralph_loop.py::TestSafetyLimits (8 tests)
  - tests/test_ralph_loop.py::TestStatus (6 tests)
  - tests/test_ralph_loop.py::TestStopHook (6 tests)
  - tests/test_ralph_loop.py::TestOrchestratorInteg (5 tests)
---

## Prompt

/sp.implement

Execute implementation plan for feature 001-ralph-loop (Ralph Wiggum Loop). Run all 33 tasks from specs/001-ralph-loop/tasks.md across 8 phases.

## Response snapshot

Ran check-prerequisites.ps1 with SPECIFY_FEATURE=001-ralph-loop. Checklists: requirements.md 16/16 PASS. Loaded all design docs from context.

**Phase 1 (T001-T004)**: SKILL.md → __init__.py → config files (T003+T004 parallel)
**Phase 2 (T005-T006)**: state_manager.py + prompt_injector.py (parallel)
**Phase 3 (T007-T013)**: test classes (T007+T008+T009 parallel) → RalphLoop.__init__ + start() → _LoopController.run() + _call_claude() → _simulate_iteration() + _check_completion() → main() CLI → __main__.py (added for python -m support)
**Phase 4 (T014-T016)**: file-movement _check_completion (already in ralph_loop.py) + argparse wiring
**Phase 5 (T017-T020)**: asyncio.wait_for per-iteration + total timeout check + STOP_RALPH sentinel monitor
**Phase 6 (T021-T023)**: RalphLoop.status() + --status CLI
**Phase 7 (T024-T029)**: stop_hook.py + .claude/settings.json + orchestrator._check_ralph_loops() + call in run()
**Phase 8 (T030-T033)**: 45/45 tests pass + 3 quickstart validations

**2 bugs fixed during implementation**:
1. DEV_MODE simulation auto-output `task.completion_promise` regardless of value — tests using `__NEVER__` falsely completed. Fixed: only auto-output when `completion_promise == "TASK_COMPLETE"`.
2. TestStopHook tests used `StateManager(tmp_path)` but hook resolves `vault_path = claude_project_dir/vault` = `tmp_path/vault` — path mismatch. Fixed: tests now create tasks in `StateManager(tmp_path / "vault")`.

**Quickstart validations**:
- Scenario 1: `DEV_MODE=true ... --completion-promise "TASK_COMPLETE" --max-iterations 5` → ✅ Loop completed (iter 3)
- Scenario 3: `... --completion-promise "__NEVER_OUTPUT_THIS__" --max-iterations 3` → ⚠️ Loop halted: max_iterations_reached, exit 1
- Scenario 4: `--status` → Ralph Loop Status with 1 completed + 1 halted loop

## Outcome

- ✅ Impact: Feature 001-ralph-loop fully implemented — all 5 user stories delivered. Ralph Wiggum stop-hook pattern operational with DEV_MODE simulation, state persistence, CLI, orchestrator integration, and stop hook.
- 🧪 Tests: 45/45 passing (0 failures). 8 test classes covering all components: config, state CRUD, prompt injection, file-movement, safety limits, status, stop hook, orchestrator integration.
- 📁 Files: 12 files created/modified (SKILL.md, __init__.py, __main__.py, ralph_loop.py, state_manager.py, prompt_injector.py, stop_hook.py, settings.json, .env, .env.example, orchestrator.py, test_ralph_loop.py); all 33 tasks in tasks.md marked [x]
- 🔁 Next prompts: /sp.git.commit_pr — commit all feature files and create PR; or /sp.implement for next feature
- 🧠 Reflection: DEV_MODE simulation must use a sentinel promise ("TASK_COMPLETE") rather than the task's actual promise, or it creates false completions in tests that use non-standard promises to test the halt path. Stop hook vault path: hook resolves `claude_project_dir/vault`, tests must match.

## Evaluation notes (flywheel)

- Failure modes observed: (1) DEV_MODE simulation auto-completes using task.completion_promise regardless of value — non-standard promises like __NEVER__ trigger false completion; (2) Stop hook tests used wrong vault path (tmp_path vs tmp_path/vault)
- Graders run and results (PASS/FAIL): 45/45 PASS; 3 quickstart scenarios validated manually
- Prompt variant (if applicable): sp.implement standard flow, 33 tasks, 8 phases
- Next experiment (smallest change to try): Run full test suite (uv run pytest tests/ -v) to verify no regressions in existing tests
