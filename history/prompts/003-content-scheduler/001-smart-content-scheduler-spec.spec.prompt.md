---
id: 001
title: Smart Content Scheduler Spec
stage: spec
date: 2026-02-20
surface: agent
model: claude-sonnet-4-6
feature: 003-content-scheduler
branch: 003-content-scheduler
user: Taha
command: /sp.specify
labels: ["content-scheduler","linkedin","spec","gold-tier","scheduling","templates","hitl"]
links:
  spec: specs/003-content-scheduler/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/003-content-scheduler/spec.md
  - specs/003-content-scheduler/checklists/requirements.md
  - history/prompts/003-content-scheduler/001-smart-content-scheduler-spec.spec.prompt.md
tests:
  - null
---

## Prompt

## Feature: Smart Content Scheduler (Gold Tier)

Create a content scheduling system that automatically generates LinkedIn post drafts from predefined topics, schedules them, and posts approved content.

### How It Works (End-to-End Flow)
1. User defines topics ONCE in vault/Content_Strategy.md
2. Scheduler runs daily at a configured time (e.g., 9 AM)
3. Claude reads topics + Company_Handbook.md + Business_Goals.md for context
4. Claude generates a draft LinkedIn post → saves to vault/Pending_Approval/
5. User reviews in Obsidian → moves to vault/Approved/
6. Poster automatically picks up approved posts and publishes to LinkedIn
7. Published post moves to vault/Done/ with timestamp

### Files to Create

**vault/Content_Strategy.md** — User-defined posting strategy (topics: AI & Automation, Backend Dev, Hackathon Journey, Cloud & DevOps, Career Tips). Content rules: <1300 chars, always include engagement question, 1-2 emojis, 3-5 hashtags, rotate topics.

**backend/scheduler/** — content_scheduler.py, post_generator.py (25+ templates), schedule_manager.py

**skills/content-scheduler/SKILL.md** — Agent skill documentation

### Acceptance Criteria (from user)
- vault/Content_Strategy.md template created
- content_scheduler.py reads strategy and generates drafts
- post_generator.py with 5+ templates per topic (25+ total)
- schedule_manager.py tracks posting history and rotation
- Drafts saved to vault/Pending_Approval/ with proper frontmatter
- Integrates with orchestrator (check on startup)
- posted_topics.json tracks history to avoid repetition
- CLI: --generate-now, --status, --preview
- Tests for scheduling logic, topic rotation, template generation
- SKILL.md in skills/content-scheduler/
- Update config/.env.example with new variables

## Response snapshot

Created feature branch `003-content-scheduler` and wrote comprehensive spec at `specs/003-content-scheduler/spec.md`.

**Spec highlights:**
- 5 prioritized user stories: P1 (daily draft generation), P2 (topic rotation), P3 (CLI control), P4 (orchestrator integration), P5 (LinkedIn publishing)
- 20 functional requirements (FR-001–FR-020) covering all acceptance criteria
- 5 key entities: ContentStrategy, PostDraft, PostingHistory, ScheduleState, PostTemplate
- 10 measurable success criteria (SC-001–SC-010) — all technology-agnostic
- Explicit Out of Scope: no LLM API calls, no multi-platform, no image attachments
- All edge cases documented (malformed YAML, character limit overflow, race conditions, weekend skip logic)
- Quality checklist created at `specs/003-content-scheduler/checklists/requirements.md` — all items pass

**Branch:** `003-content-scheduler` (switched)
**Spec file:** `specs/003-content-scheduler/spec.md`
**Checklist:** `specs/003-content-scheduler/checklists/requirements.md` — all items ✅

## Outcome

- ✅ Impact: Spec fully captures the Smart Content Scheduler feature for Gold Tier — covers draft generation, rotation, CLI, orchestrator integration, and LinkedIn publishing via HITL
- 🧪 Tests: No tests written at spec stage; test cases defined in acceptance scenarios and success criteria (FR-019 mandates 25+ templates, SC-003 validates char limits)
- 📁 Files: specs/003-content-scheduler/spec.md, specs/003-content-scheduler/checklists/requirements.md
- 🔁 Next prompts: `/sp.plan` to generate architecture plan | `/sp.clarify` if requirements need refinement | `/sp.tasks` to break down into implementable tasks
- 🧠 Reflection: Template-based generation (not live LLM) was chosen as a reasonable default per user spec — this keeps the scheduler deterministic and avoids API key dependencies at this tier

## Evaluation notes (flywheel)

- Failure modes observed: PowerShell script errored on Join-Path with 3+ args (Windows PS 5.1 limitation); branch and spec file created successfully before error
- Graders run and results (PASS/FAIL): Spec quality checklist — all 12 items PASS
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): Run `/sp.plan` to generate architecture decisions for backend/scheduler/ layout and orchestrator integration point
