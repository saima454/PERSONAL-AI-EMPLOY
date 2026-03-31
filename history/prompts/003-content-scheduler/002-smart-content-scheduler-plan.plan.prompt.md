---
id: 002
title: Smart Content Scheduler Plan
stage: plan
date: 2026-02-20
surface: agent
model: claude-sonnet-4-6
feature: 003-content-scheduler
branch: 003-content-scheduler
user: Taha
command: /sp.plan
labels: ["content-scheduler","linkedin","plan","architecture","templates","orchestrator","action-executor"]
links:
  spec: specs/003-content-scheduler/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/003-content-scheduler/plan.md
  - specs/003-content-scheduler/research.md
  - specs/003-content-scheduler/data-model.md
  - specs/003-content-scheduler/quickstart.md
  - specs/003-content-scheduler/contracts/scheduler-interfaces.md
tests:
  - null
---

## Prompt

/sp.plan

(No additional arguments — planning for current branch 003-content-scheduler)

## Response snapshot

Generated full architecture plan for Smart Content Scheduler feature (003-content-scheduler).

**Phase 0 — Research (research.md):**
- RQ-1: Confirmed frontmatter field is `type:` NOT `action_type:` (spec correction)
- RQ-2: `_handle_linkedin_post()` is a NotImplementedError placeholder — need real LinkedInPoster integration
- RQ-3: Orchestrator startup integration via `asyncio.to_thread()` in new `_check_content_schedule()` method
- RQ-4: Templates as Python dataclasses in post_generator.py (not external YAML)
- RQ-5: Atomic rename for state file writes (no file locking library needed)
- RQ-6: `zoneinfo` stdlib for timezone (Python 3.13+ available)
- RQ-7: Draft body needs `# Post Content` heading (LinkedInPoster strips it)
- RQ-8: Character count on post text only (not frontmatter/heading)

**Phase 1 — Design artifacts:**
- `data-model.md`: 5 entities (ContentStrategy, PostDraft, PostingHistory, ScheduleState, PostTemplate) with full schemas
- `contracts/scheduler-interfaces.md`: Full Python interface contracts for ContentScheduler, ScheduleManager, PostGenerator + CLI contract + orchestrator integration contract
- `quickstart.md`: Step-by-step guide from strategy definition to published post

**plan.md highlights:**
- 6 implementation phases: A (new scheduler module), B (vault template), C (skill SKILL.md), D (orchestrator integration), E (action executor integration), F (config updates), G (tests)
- 6 architectural decisions documented (AD-1 through AD-6)
- Constitution check: all 8 principles pass
- Risk table: double-move bug (Medium) identified and mitigated
- CLAUDE.md updated via update-agent-context.ps1

**Files created:**
- specs/003-content-scheduler/plan.md
- specs/003-content-scheduler/research.md
- specs/003-content-scheduler/data-model.md
- specs/003-content-scheduler/quickstart.md
- specs/003-content-scheduler/contracts/scheduler-interfaces.md

## Outcome

- ✅ Impact: Complete architecture plan for content scheduler — all integration points resolved, data model defined, contracts specified. Ready for /sp.tasks.
- 🧪 Tests: No tests written at plan stage; test classes specified in Phase G (20+ test cases required)
- 📁 Files: 5 artifacts created in specs/003-content-scheduler/
- 🔁 Next prompts: `/sp.tasks` to generate implementable task list | `/sp.adr content-generation-approach` to document template-vs-LLM decision
- 🧠 Reflection: Key spec correction — `action_type:` → `type:` in frontmatter (existing code uses `type`). Existing LinkedInPoster and ActionExecutor are further along than expected — only need to wire the placeholder handler and add orchestrator startup hook.

## Evaluation notes (flywheel)

- Failure modes observed: None — plan generated cleanly from codebase inspection
- Graders run and results (PASS/FAIL): Constitution check — 8/8 principles PASS
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): Run `/sp.tasks` to get implementable task breakdown with test cases
