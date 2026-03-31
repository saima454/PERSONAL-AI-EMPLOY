---
id: 1
title: Orchestrator Scheduling Spec
stage: spec
date: 2026-02-18
surface: agent
model: claude-opus-4-6
feature: 002-orchestrator-scheduling
branch: 002-orchestrator-scheduling
user: PMLS
command: /sp.specify
labels: ["orchestrator", "scheduling", "spec", "silver-tier"]
links:
  spec: specs/002-orchestrator-scheduling/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/002-orchestrator-scheduling/spec.md
  - specs/002-orchestrator-scheduling/checklists/requirements.md
  - history/prompts/002-orchestrator-scheduling/001-orchestrator-scheduling-spec.spec.prompt.md
tests:
  - "Checklist validation: 16/16 items PASS"
---

## Prompt

/sp.specify

## Feature: Orchestrator + Scheduling (Silver Tier - Final)

Create the master Orchestrator that connects all watchers, reasoning, and actions together.

### What This Does
The Orchestrator is the "glue" that makes the AI Employee autonomous. It:
1. Starts all watchers (Gmail, WhatsApp, LinkedIn) as background tasks
2. Monitors vault/Needs_Action/ for new files from watchers
3. Monitors vault/Approved/ for approved actions and executes them
4. Manages process lifecycle (start, stop, restart watchers)
5. Provides a single entry point: python orchestrator.py

### Architecture
backend/orchestrator/
- __init__.py
- orchestrator.py       # Main orchestrator - starts everything
- action_executor.py    # Watches /Approved and executes actions
- watchdog.py           # Health monitor - restarts failed processes

scripts/
- start_all.ps1         # PowerShell script to start everything
- stop_all.ps1          # PowerShell script to stop everything
- setup_scheduler.ps1   # Setup Windows Task Scheduler

### Orchestrator Responsibilities

**Process Management:**
- Start Gmail watcher, WhatsApp watcher, LinkedIn watcher as async tasks
- Monitor each watcher's health (heartbeat check)
- Restart any watcher that crashes
- Graceful shutdown on Ctrl+C

**Needs_Action Processing:**
- Watch vault/Needs_Action/ folder for new .md files
- When new file appears, log it to Dashboard.md
- Update vault/Dashboard.md with current status of all watchers

**Approved Action Execution:**
- Watch vault/Approved/ folder for new files
- Read the file's type field from frontmatter
- Execute corresponding action (email_send, email_reply, linkedin_post)
- After execution, move file to vault/Done/
- Log result to vault/Logs/

**Dashboard Updates:**
- Update vault/Dashboard.md every 5 minutes

### Scheduling (Windows Task Scheduler)
PowerShell scripts for system login start, crash restart, daily briefing at 8:00 AM.

### Acceptance Criteria
- orchestrator.py starts all 3 watchers as async tasks
- Monitors and restarts crashed watchers
- action_executor.py processes approved files automatically
- Dashboard.md updated with live status
- watchdog.py monitors orchestrator health
- PowerShell scripts for Windows Task Scheduler
- Graceful shutdown on Ctrl+C
- All actions logged to vault/Logs/
- Tests for orchestrator logic
- SKILL.md in skills/orchestrator/

## Response snapshot

Created comprehensive feature specification for 002-orchestrator-scheduling with:
- 5 user stories (P1-P5): Single command startup, crash recovery, approved action execution, live dashboard, Windows Task Scheduler
- 16 functional requirements (FR-001 through FR-016)
- 8 measurable success criteria (SC-001 through SC-008)
- 4 key entities: Watcher Task, Action Executor, Dashboard State, Lock File
- 6 edge cases with resolution strategies
- Clear scope boundaries (in/out of scope)
- 7 documented assumptions

Quality checklist: 16/16 items passed. No [NEEDS CLARIFICATION] markers.

Branch created: `002-orchestrator-scheduling`
Spec file: `specs/002-orchestrator-scheduling/spec.md`

## Outcome

- Impact: Complete spec for the Silver Tier capstone feature — the orchestrator that makes the AI Employee autonomous
- Tests: Checklist validation 16/16 PASS, no clarification markers
- Files: 3 files created (spec.md, checklists/requirements.md, PHR)
- Next prompts: /sp.plan to create architecture plan, then /sp.tasks for task breakdown
- Reflection: Spec was straightforward given the detailed user description and existing patterns from feature 001. All requirements mapped cleanly to acceptance scenarios.

## Evaluation notes (flywheel)

- Failure modes observed: create-new-feature.ps1 had a minor argument parsing error with the prompts directory path, but branch creation succeeded
- Graders run and results (PASS/FAIL): Checklist 16/16 PASS
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): Run /sp.plan to validate spec-to-plan transition quality
