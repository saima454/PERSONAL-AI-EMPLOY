---
id: "001"
title: Ralph Loop Feature Specification
stage: spec
date: 2026-02-24
surface: agent
model: claude-sonnet-4-6
feature: 001-ralph-loop
branch: 001-ralph-loop
user: PMLS
command: /sp.specify
labels: ["ralph-wiggum","stop-hook","loop","completion-strategy","safety","gold-tier","orchestrator"]
links:
  spec: specs/001-ralph-loop/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/001-ralph-loop/spec.md
  - specs/001-ralph-loop/checklists/requirements.md
tests: []
---

## Prompt

/sp.specify

Ralph Wiggum Loop (Gold Tier) — Implement the Ralph Wiggum stop-hook pattern that keeps Claude Code iterating until a multi-step task is complete. When Claude tries to exit, a stop hook checks if the task is actually complete. If not, it re-injects the prompt and lets Claude see its previous output to continue working. Two completion strategies: promise-based (Claude outputs TASK_COMPLETE) and file-movement (task file detected in /Done). Architecture: backend/ralph_wiggum/ with ralph_loop.py, stop_hook.py, state_manager.py, prompt_injector.py. Skills: skills/ralph-wiggum/SKILL.md. CLI: --completion-promise, --completion-file, --max-iterations, --status. State files in vault with YAML frontmatter tracking iteration count, completion strategy, timestamps. Safety: max iterations (default 10), iteration timeout (default 5 min), total timeout (default 60 min), emergency stop via vault/STOP_RALPH file. Env vars: RALPH_MAX_ITERATIONS, RALPH_ITERATION_TIMEOUT, RALPH_TOTAL_TIMEOUT. Orchestrator can spawn Ralph loops for complex tasks. All iterations logged to vault/Logs/. Respects DEV_MODE and DRY_RUN. SKILL.md first, then implement, then tests.

## Response snapshot

Created branch `001-ralph-loop` and wrote `specs/001-ralph-loop/spec.md` with 5 user stories, 16 functional requirements, 6 success criteria, 7 edge cases, Assumptions section, and Out of Scope section. No NEEDS CLARIFICATION markers. All 16 checklist items pass.

User stories:
- P1: Promise-based loop completion (core pattern — AI outputs TASK_COMPLETE to end loop)
- P2: File-movement completion detection (loop exits when target file appears in vault/Done/)
- P3: Safety limits and emergency stop (max iterations, per-iteration and total timeouts, vault/STOP_RALPH)
- P4: Status monitoring (--status shows all loop states)
- P5: Orchestrator integration (auto-spawn loops for eligible vault tasks)

Key assumptions documented: default completion marker = TASK_COMPLETE, state files live in vault/ralph_wiggum/, DEV_MODE simulates without external calls, orchestrator integration is opt-in via task tagging.

## Outcome

- ✅ Impact: Complete, business-readable spec ready for /sp.plan — covers all 5 user stories from the hackathon PDF description with no ambiguity or clarification questions needed
- 🧪 Tests: No tests at spec stage
- 📁 Files: specs/001-ralph-loop/spec.md (created), specs/001-ralph-loop/checklists/requirements.md (all 16 items pass)
- 🔁 Next prompts: /sp.plan — generate research.md, data-model.md, contracts/, quickstart.md, plan.md
- 🧠 Reflection: The Ralph Wiggum pattern is conceptually a state machine (in_progress → completed|halted). Framing it that way in the spec clarifies safety limits and emergency stop as state transitions, making requirements more testable.

## Evaluation notes (flywheel)

- Failure modes observed: none — feature description was highly detailed; all decisions made from spec without clarification questions
- Graders run and results (PASS/FAIL): requirements.md checklist — 16/16 PASS
- Prompt variant (if applicable): sp.specify standard flow
- Next experiment (smallest change to try): /sp.plan to resolve architecture decisions (how stop hook actually intercepts Claude exit, state machine transitions)
