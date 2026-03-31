---
id: "003"
title: meta-social-tasks-breakdown
stage: tasks
date: 2026-02-21
surface: agent
model: claude-sonnet-4-6
feature: "004-meta-social-integration"
branch: 004-meta-social-integration
user: Taha
command: /sp.tasks
labels: ["facebook", "instagram", "meta", "task-breakdown", "playwright", "watcher", "poster", "orchestrator", "content-scheduler"]
links:
  spec: specs/004-meta-social-integration/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/004-meta-social-integration/tasks.md (created — 42 tasks across 7 phases)
tests:
  - (no tests at tasks stage)
---

## Prompt

/sp.tasks

## Response snapshot

Generated `tasks.md` for `004-meta-social-integration` with 42 tasks across 7 phases.

**Setup**: `check-prerequisites.ps1 -Json` returned FEATURE_DIR and AVAILABLE_DOCS (research.md, data-model.md, contracts/, quickstart.md).

**Documents loaded**: spec.md (5 user stories P1–P5), plan.md (module design, source structure), research.md (8 decisions), data-model.md (5 entities + 2 dedup stores), contracts/vault-file-contracts.md (11 contracts), quickstart.md (10 scenarios).

**Task organization**:
- Phase 1 (Setup): T001–T003 — env vars, skill definition, gitignore (3 tasks)
- Phase 2 (US1 Foundational): T004–T010 — FacebookWatcher + InstagramWatcher session management, orchestrator registration (7 tasks)
- Phase 3 (US2 FB Monitoring): T011–T017 — dedup store, _scan_notifications, _scan_messages, check_for_updates, create_action_file, run()/main() (7 tasks)
- Phase 4 (US3 FB Auto-Post): T018–T024 — FacebookPoster class, validation, _publish_post, process_approved_posts, action_executor handler (7 tasks)
- Phase 5 (US4 IG Monitoring): T025–T030 — InstagramWatcher dedup + scan + create_action_file + run/main (6 tasks)
- Phase 6 (US5 CS Integration): T031–T037 — PostGenerator platform routing, char limit, Content_Strategy.md update, InstagramPoster, action_executor handler (7 tasks)
- Phase 7 (Polish): T038–T042 — test_meta_social.py, pytest baseline, ruff lint, e2e validation, mark tasks done (5 tasks)

**Dependency graph**:
```
Phase 1 → Phase 2 → [Phase 3 ∥ Phase 4 ∥ Phase 5 ∥ Phase 6] → Phase 7
```

US1 (Meta Session) is foundational — blocks all other stories. US2–US5 can proceed in parallel after US1.

**MVP**: Phase 1 + Phase 2 (10 tasks) → session management works, both watchers start in orchestrator.

**Parallel opportunities**: T008/T009 ∥ T004–T007 in Phase 2; T012/T013 ∥ each other in Phase 3; Phases 3–6 fully parallel across team members; T038/T039/T040 ∥ in Phase 7.

## Outcome

- ✅ Impact: 42-task breakdown ready for /sp.implement. All 5 user stories have independently testable checkpoints. MVP scope = 10 tasks (Phases 1–2).
- 🧪 Tests: No tests at tasks stage; T038 plans ~50 tests in test_meta_social.py
- 📁 Files: 1 file created (tasks.md)
- 🔁 Next prompts: /sp.implement to begin implementation starting with Phase 1; or /sp.adr shared-meta-session to document session architecture decision first
- 🧠 Reflection: US1 (Meta Session Setup) correctly occupies Phase 2 as both a user story and a foundational prerequisite — it blocks all subsequent Meta functionality. The split of FacebookWatcher into session management (Phase 2) and monitoring logic (Phase 3) makes each phase independently validatable without needing real Facebook access until Phase 3.

## Evaluation notes (flywheel)

- Failure modes observed: None — all design documents were available from /sp.plan
- Graders run and results (PASS/FAIL): Format validation PASS (all 42 tasks have checkbox + ID + [USx] label where required + file path); dependency graph validated manually
- Prompt variant (if applicable): sp.tasks with no user input (uses current branch context)
- Next experiment: Run /sp.implement and observe if the Phase 2/US1 split (session separately from monitoring) allows clean checkpoint validation before adding browser scraping complexity
