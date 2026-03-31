---
id: "002"
title: Ralph Loop Implementation Plan
stage: plan
date: 2026-02-24
surface: agent
model: claude-sonnet-4-6
feature: 001-ralph-loop
branch: 001-ralph-loop
user: PMLS
command: /sp.plan
labels: ["ralph-wiggum","stop-hook","loop-controller","asyncio","claude-code-hooks","subprocess","state-machine","gold-tier"]
links:
  spec: specs/001-ralph-loop/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/001-ralph-loop/plan.md
  - specs/001-ralph-loop/research.md
  - specs/001-ralph-loop/data-model.md
  - specs/001-ralph-loop/quickstart.md
  - specs/001-ralph-loop/contracts/cli.md
tests: []
---

## Prompt

/sp.plan

Execute the implementation planning workflow for feature 001-ralph-loop (Ralph Wiggum Loop). Generate research.md, data-model.md, contracts/, quickstart.md, and plan.md.

## Response snapshot

Ran 3 parallel research agents:
1. Claude Code stop hook API → `onStop` hook in `.claude/settings.json`; returns `{"decision": "block", "reason": "..."}` exit 0 to intercept exit; `claude_project_dir` available in stdin payload
2. Python loop state machine patterns → enum-based states, `asyncio.wait_for` timeout, background sentinel monitor task, YAML frontmatter persistence; mirrors WatcherStatus + BriefingRunResult patterns
3. Claude Code CLI invocation → `claude -p "prompt" --output-format json`; `--resume SESSION_ID` for context continuity; `--max-turns N` for iteration control

**Architecture Decision**: Two-mode execution:
- **Hook mode** (interactive): `onStop` hook → `stop_hook.py` reads state → blocks/allows
- **Subprocess mode** (programmatic): `ralph_loop.py` runs `claude -p` in loop; orchestrator calls `RalphLoop.start()`

Both modes share `state_manager.py` (vault state files in `vault/ralph_wiggum/`) and `prompt_injector.py` (continuation prompt builder).

**Constitution check**: All 8 principles pass. No violations.

**Generated artifacts**:
- research.md: 10 decisions (hook mechanism, subprocess API, two-mode architecture, state machine, timeouts, state file format, completion detection, prompt injection, DEV_MODE simulation, orchestrator integration)
- data-model.md: 9 entities (RalphConfig, CompletionStrategy, LoopStatus, HaltReason, RalphTask, IterationRecord, RalphRunResult, RalphStatusResult, RalphTaskSummary) + state file YAML format + orchestrator task file format
- contracts/cli.md: Full CLI contract for start (promise/file), status, emergency stop, stop hook, orchestrator API
- quickstart.md: 9 scenarios (promise loop, file-movement, max iterations halt, status, emergency stop, dry-run, specific status, orchestrator integration, stop hook interactive)
- plan.md: Full implementation plan with source structure, 5 technology decisions, implementation order (SKILL.md T001), file specs for all 5 backend files

ADR suggested: Two-mode execution (hook-based vs subprocess-based). Run `/sp.adr ralph-loop-execution-modes` to document.

## Outcome

- ✅ Impact: Complete implementation plan ready for /sp.tasks — all architectural unknowns resolved, state machine designed, hook API documented, two-mode architecture planned
- 🧪 Tests: No tests at planning stage (tests designed in plan: 5 classes, ~34 tests)
- 📁 Files: 5 artifacts created (research.md, data-model.md, quickstart.md, contracts/cli.md, plan.md); CLAUDE.md updated by agent context script
- 🔁 Next prompts: /sp.tasks — generate tasks.md with ~25 tasks across 7 phases; then /sp.implement
- 🧠 Reflection: The key insight is that `onStop` hook cannot directly inject prompts — it can only block/allow and provide a reason string that Claude uses to decide what to do next. This makes the hook mode suitable for interactive sessions but not for programmatic control. The two-mode architecture cleanly separates these concerns.

## Evaluation notes (flywheel)

- Failure modes observed: setup-plan.ps1 returned wrong branch (007-ceo-briefing) because repo has no commits so `git rev-parse --abbrev-ref HEAD` fails; fixed by setting `SPECIFY_FEATURE=001-ralph-loop` env var
- Graders run and results (PASS/FAIL): Constitution check — 8/8 principles PASS
- Prompt variant (if applicable): sp.plan standard flow with 3 parallel research agents
- Next experiment (smallest change to try): /sp.tasks to generate task breakdown; ADR for two-mode execution architecture
