---
id: "004"
title: "Twitter X Integration Tasks"
stage: tasks
date: "2026-02-21"
surface: agent
model: claude-sonnet-4-6
feature: 005-twitter-x-integration
branch: 005-twitter-x-integration
user: PMLS
command: /sp.tasks
labels: ["twitter", "tasks", "playwright", "watcher", "poster", "content-scheduler", "test-plan"]
links:
  spec: specs/005-twitter-x-integration/spec.md
  ticket: "null"
  adr: "null"
  pr: "null"
files:
  - specs/005-twitter-x-integration/tasks.md
tests:
  - "null"
---

## Prompt

/sp.tasks

## Response snapshot

Ran `check-prerequisites.ps1` → FEATURE_DIR=specs/005-twitter-x-integration, AVAILABLE_DOCS=[research.md, data-model.md, quickstart.md].

Generated `specs/005-twitter-x-integration/tasks.md` with 38 tasks across 7 phases:

**Phase 1: Setup (T001–T002)** — .gitignore + .env.example
**Phase 2: Foundational (T003–T004)** — Create twitter_watcher.py + twitter_poster.py module shells
**Phase 3: US1 Session Setup (T005–T010)** — TwitterWatcher class, browser management, session state, setup_session(), CLI
**Phase 4: US2 Notification Monitoring (T011–T017)** — Dedup methods, _scan_notifications(), _scan_messages(), check_for_updates(), create_action_file(), run(), orchestrator registration
**Phase 5: US3 Auto-Post (T018–T028)** — TwitterPoster class, browser methods, validate_post(), _publish_post(), move_to_done/rejected, scan_approved, process_approved_posts(), main(), HANDLERS + _handle_twitter_post()
**Phase 6: US4 Content Scheduler (T029–T031)** — TWITTER_CHAR_LIMIT + Twitter platform validation, 5 Twitter templates (≤280 chars each), schedule_manager "TWITTER" prefix
**Phase 7: Polish (T032–T038)** — SKILL.md, test_twitter.py (7 classes, ~59 tests), pytest run, ruff check, full regression, E2E DEV_MODE validation, mark all [X]

Key design notes embedded in tasks:
- `update_frontmatter(file_path, dict)` takes file path not string content (critical Feature 004 lesson)
- Twitter home page auto-focuses textarea — no intermediate click needed
- 280-char: poster hard-rejects, generator emergency-truncates as safety net only
- US3 (poster) can be built in parallel with US1+US2 (watcher) — different files

## Outcome

- ✅ Impact: 38-task breakdown is ready for `/sp.implement`. Each task has exact file paths, precise implementation instructions referencing existing FacebookWatcher patterns, and embedded gotchas from Feature 004 debugging.
- 🧪 Tests: T033 specifies 7 test classes (~59 tests), T034 verifies all pass, T036 verifies full regression (410+ tests).
- 📁 Files: 1 file created — specs/005-twitter-x-integration/tasks.md
- 🔁 Next prompts: `/sp.implement` to execute all 38 tasks
- 🧠 Reflection: US1 and US2 are sequentially dependent (same file: twitter_watcher.py), but US3 (twitter_poster.py) is fully parallel with US1+US2. US4 (post_generator.py + schedule_manager.py) is independent of all watcher/poster tasks and can run concurrently.

## Evaluation notes (flywheel)

- Failure modes observed: None — tasks.md generation was clean
- Graders run and results (PASS/FAIL): Format validation PASS (all 38 tasks have checkbox + ID + story label + file path); dependency graph PASS
- Prompt variant (if applicable): standard /sp.tasks flow
- Next experiment (smallest change to try): Run /sp.implement → verify T001+T002 (gitignore + .env.example) complete cleanly before starting T003
