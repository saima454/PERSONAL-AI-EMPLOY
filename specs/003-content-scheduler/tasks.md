# Tasks: Smart Content Scheduler

**Input**: Design documents from `specs/003-content-scheduler/`
**Branch**: `003-content-scheduler` | **Date**: 2026-02-20
**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Tests**: Included — explicitly required by spec.md acceptance criteria ("Tests for scheduling logic, topic rotation, template generation").

**Organization**: 8 phases — Setup → Foundational → US1 (MVP) → US2 → US3 → US4 → US5 → Polish

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story this task belongs to (US1–US5)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create all new files and config entries before any implementation begins.

- [X] T001 Create `backend/scheduler/__init__.py` as empty package init
- [X] T002 [P] Create `vault/Content_Strategy.md` with Taha's full profile (5 topics, content rules, Do NOT post list, YAML frontmatter with post_frequency/preferred_time/tone/max_hashtags)
- [X] T003 [P] Create `skills/content-scheduler/SKILL.md` with metadata (name, version, triggers, permissions, HITL requirement, layer=PERCEPTION, dependencies on skills/linkedin-poster)
- [X] T004 [P] Add `CONTENT_POST_FREQUENCY`, `CONTENT_POST_TIME`, `CONTENT_TIMEZONE`, `CONTENT_SKIP_WEEKENDS` variables with comments to `config/.env.example`

**Checkpoint**: All scaffold files exist — implementation can begin

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core shared dataclasses and type definitions used by every user story. Must be complete before any story work begins.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Create shared exception classes `ContentStrategyError` and `TemplateGenerationError` plus result dataclasses `RunResult`, `PreviewResult`, `StatusResult` at top of `backend/scheduler/content_scheduler.py`
- [X] T006 [P] Create `ScheduleState` and `PostingHistory` / `PostingHistoryEntry` dataclasses with all fields from data-model.md in `backend/scheduler/schedule_manager.py`
- [X] T007 [P] Create `PostTemplate` and `GeneratedPost` and `PostContext` and `ValidationResult` dataclasses in `backend/scheduler/post_generator.py`

**Checkpoint**: Shared types ready — all user story phases can proceed

---

## Phase 3: User Story 1 — Core Draft Generation (Priority: P1) 🎯 MVP

**Goal**: Running `uv run python -m backend.scheduler.content_scheduler` generates a ready-to-review LinkedIn draft in `vault/Pending_Approval/LINKEDIN_POST_{date}.md`.

**Independent Test**: `uv run python -m backend.scheduler.content_scheduler` with `vault/Content_Strategy.md` present → file appears in `vault/Pending_Approval/` with correct frontmatter (`type: linkedin_post`, `status: pending_approval`, `character_count` ≤ 1300).

### Tests for User Story 1

- [X] T008 [P] [US1] Write `TestPostGenerator` class in `tests/test_content_scheduler.py`: verify 25+ templates exist (5 per topic × 5 topics), all templates produce posts ≤ 1300 chars, `validate_post()` catches overlimit content
- [X] T009 [P] [US1] Write `TestContentScheduler` class in `tests/test_content_scheduler.py`: `run_if_due()` with valid strategy creates draft file; `run_if_due()` with missing strategy raises `ContentStrategyError`; draft has required frontmatter fields (`type`, `status`, `topic`, `generated_at`, `character_count`)

### Implementation for User Story 1

- [X] T010 [P] [US1] Implement `TEMPLATES: dict[str, list[PostTemplate]]` in `backend/scheduler/post_generator.py` — 25 templates total: 5 topics (`ai_automation`, `backend_development`, `hackathon_journey`, `cloud_devops`, `career_tips`) × 5 format types (`tip`, `insight`, `question`, `story`, `announcement`) — each persona-specific to "Taha — Agentic AI & Senior Backend Engineer"
- [X] T011 [US1] Implement `PostGenerator.generate()`, `get_templates_for_topic()`, and `validate_post()` in `backend/scheduler/post_generator.py` — random template selection, placeholder filling, 1300-char validation, retry up to 3 times with different template on overflow (depends on T010)
- [X] T012 [P] [US1] Implement `ScheduleManager.__init__()`, `load_state()`, and `save_state()` (atomic write via `.tmp` + rename) in `backend/scheduler/schedule_manager.py` — creates default `ScheduleState` if `vault/Logs/posting_schedule.json` missing; resets to default on JSON parse error
- [X] T013 [P] [US1] Implement `ScheduleManager.is_post_due()` and `draft_exists_today()` in `backend/scheduler/schedule_manager.py` — checks `skip_weekends`, `post_frequency`, `last_run_date == today`, scans `vault/Pending_Approval/` and `vault/Approved/` for `LINKEDIN_POST_{date}.md`
- [X] T014 [US1] Implement `ContentScheduler.__init__()` and `_load_strategy()` in `backend/scheduler/content_scheduler.py` — parse `vault/Content_Strategy.md` YAML frontmatter + body sections (`## Topics`, `## Content Rules`, `## Do NOT Post About`) into `ContentStrategy` + `Topic` dataclasses; raise `ContentStrategyError` on missing file or empty topics list (depends on T005)
- [X] T015 [US1] Implement `ContentScheduler._load_context()` in `backend/scheduler/content_scheduler.py` — read `vault/Company_Handbook.md` and `vault/Business_Goals.md` into `PostContext`; return `PostContext(None, None)` gracefully if files are absent (depends on T014)
- [X] T016 [US1] Implement `ContentScheduler._save_draft()` in `backend/scheduler/content_scheduler.py` — write `vault/Pending_Approval/LINKEDIN_POST_{YYYY-MM-DD}.md` using `backend.utils.frontmatter.create_file_with_frontmatter()` with fields: `type: linkedin_post`, `status: pending_approval`, `topic`, `topic_index`, `template_id`, `generated_at`, `scheduled_date`, `character_count`; body = `# Post Content\n\n{post_text}` (depends on T015)
- [X] T017 [US1] Implement `ContentScheduler.run_if_due()` in `backend/scheduler/content_scheduler.py` — full pipeline: load strategy → is_post_due check → select topic (first topic for now, rotation added in US2) → load context → generate post → save draft → update ScheduleState → return `RunResult` (depends on T011, T013, T016)

**Checkpoint**: `uv run python -m backend.scheduler.content_scheduler` produces a draft. Run T008/T009 tests — they should pass.

---

## Phase 4: User Story 2 — Topic Rotation Without Repetition (Priority: P2)

**Goal**: Running the scheduler 6 days in a row with 5 topics selects a different topic each day; same topic never appears on consecutive days.

**Independent Test**: Run `uv run python -m backend.scheduler.content_scheduler --generate-now` 6 times with different mock dates in `vault/Logs/posted_topics.json` — verify `topic_index` rotates without consecutive repeats.

### Tests for User Story 2

- [X] T018 [P] [US2] Write `TestTopicRotation` class in `tests/test_content_scheduler.py`: simulate 10 scheduler runs, assert no consecutive topic repeats, assert full 5-topic cycle completes before restart, assert wrap-around works correctly
- [X] T019 [P] [US2] Write `TestScheduleManager` class in `tests/test_content_scheduler.py`: `get_next_topic_index()` returns different index from last; `load_history()` creates empty history when file missing; `save_history()` + `load_history()` round-trips correctly; atomic write leaves no `.tmp` files on success

### Implementation for User Story 2

- [X] T020 [US2] Implement `ScheduleManager.load_history()` and `save_history()` (atomic write) and `PostingHistory.was_posted_today()` / `add_entry()` in `backend/scheduler/schedule_manager.py` (depends on T006)
- [X] T021 [US2] Implement `ScheduleManager.get_next_topic_index()` in `backend/scheduler/schedule_manager.py` — round-robin: `(last_index + 1) % num_topics`; guarantees result ≠ `last_topic_index` when `num_topics > 1`; returns 0 when `num_topics == 1` (depends on T020)
- [X] T022 [US2] Update `ContentScheduler.run_if_due()` in `backend/scheduler/content_scheduler.py` to use `get_next_topic_index()` for topic selection and record `PostingHistoryEntry` via `save_history()` after successful draft save (depends on T017, T021)

**Checkpoint**: `TestTopicRotation` passes. Rotation confirmed across 10 runs with no consecutive repeats.

---

## Phase 5: User Story 3 — CLI Control: Generate Now, Preview, Status (Priority: P3)

**Goal**: `--generate-now` forces a draft; `--preview` prints content to stdout without saving; `--status` shows schedule state in < 1 second.

**Independent Test**: Run each CLI flag and verify: `--generate-now` overwrites existing draft; `--preview` produces no new files in `vault/`; `--status` returns within 1 second and shows last/next topic.

### Tests for User Story 3

- [X] T023 [P] [US3] Write `TestCLIFlags` class in `tests/test_content_scheduler.py`: `generate_now()` writes draft regardless of existing file; `preview()` returns `PreviewResult` with non-empty `post_text` and writes NO files; `status()` returns `StatusResult` with correct `is_due_today` and `next_topic`

### Implementation for User Story 3

- [X] T024 [US3] Implement `ContentScheduler.generate_now()` in `backend/scheduler/content_scheduler.py` — same as `run_if_due()` but skips idempotency guard (always generates); records history entry (depends on T022)
- [X] T025 [US3] Implement `ContentScheduler.preview()` in `backend/scheduler/content_scheduler.py` — run full generation pipeline, return `PreviewResult`, write NO files (no `_save_draft()` call, no state updates) (depends on T024)
- [X] T026 [US3] Implement `ContentScheduler.status()` in `backend/scheduler/content_scheduler.py` — load strategy, load state, load history, compute `is_due_today`, build `StatusResult` with `last_post_date`, `last_topic`, `next_topic`, `posts_today`, `next_run_time` from strategy `preferred_time` (depends on T022)
- [X] T027 [US3] Implement CLI `__main__` entry point in `backend/scheduler/content_scheduler.py` — argparse with `--generate-now`, `--preview`, `--status`, `--vault-path PATH`, `--dry-run` flags; load `.env`, construct `ContentScheduler`, dispatch to correct method; print output to stdout; exit codes 0/1/2/3 per contracts (depends on T026)

**Checkpoint**: All three CLI flags work. `TestCLIFlags` passes. `--status` returns in < 1s.

---

## Phase 6: User Story 4 — Orchestrator Integration on Startup (Priority: P4)

**Goal**: Starting the orchestrator with a due post automatically creates a draft without manual CLI invocation.

**Independent Test**: Start orchestrator, assert `vault/Pending_Approval/LINKEDIN_POST_{today}.md` exists after startup. Start orchestrator again (draft already exists) — assert no duplicate file created and no crash.

### Tests for User Story 4

- [X] T028 [US4] Write `TestOrchestratorSchedulerHook` in `tests/test_content_scheduler.py`: mock `ContentScheduler.run_if_due()` to return `RunResult(status="generated", ...)` — verify `_check_content_schedule()` logs at INFO level; mock to raise `ContentStrategyError` — verify orchestrator does NOT raise and logs WARNING

### Implementation for User Story 4

- [X] T029 [US4] Add `_check_content_schedule()` async method to `Orchestrator` in `backend/orchestrator/orchestrator.py` — lazy import `ContentScheduler`; call via `await asyncio.to_thread(scheduler.run_if_due)`; catch `ContentStrategyError` → log WARNING; catch all other exceptions → log WARNING; log INFO on `status=="generated"` (depends on T017 being importable)
- [X] T030 [US4] Add `await self._check_content_schedule()` call inside `Orchestrator.run()` in `backend/orchestrator/orchestrator.py` — insert after `self._log_event("orchestrator_start", ...)` and before `self._start_watchers()` (depends on T029)

**Checkpoint**: `TestOrchestratorSchedulerHook` passes. Orchestrator startup produces a draft when due; does not crash when strategy is missing.

---

## Phase 7: User Story 5 — Approved Draft Auto-Published to LinkedIn (Priority: P5)

**Goal**: Moving a draft from `vault/Pending_Approval/` to `vault/Approved/` triggers automatic LinkedIn posting on the next action executor poll cycle.

**Independent Test**: Place `LINKEDIN_POST_{today}.md` with `type: linkedin_post`, `status: approved` in `vault/Approved/` with `DEV_MODE=true` → action executor logs DEV_MODE message and moves file to `vault/Done/` within one poll cycle.

### Tests for User Story 5

- [X] T031 [US5] Write `TestLinkedInPostHandler` in `tests/test_content_scheduler.py` — or extend existing `tests/test_action_executor.py`: mock `LinkedInPoster.process_approved_posts()` to return 1; verify `_handle_linkedin_post()` completes without error and does NOT call `self._move_to_done()`; mock to return 0 — verify `RuntimeError` is raised so executor logs failure

### Implementation for User Story 5

- [X] T032 [US5] Replace `_handle_linkedin_post()` stub in `backend/orchestrator/action_executor.py` (lines 167–170) with real `LinkedInPoster` integration — lazy import `LinkedInPoster`; construct with `vault_path`, `session_path`, `headless`, `dry_run`, `dev_mode` from `self.config` and env vars; `await poster.process_approved_posts()`; `await poster._close_browser()` in finally block; raise `RuntimeError` if count == 0
- [X] T033 [US5] Fix file lifecycle collision in `ActionExecutor.process_file()` in `backend/orchestrator/action_executor.py` — add a check after `handler()` returns: if `file_path` no longer exists (moved by `LinkedInPoster._move_to_done()`), skip `self._move_to_done(file_path)`; add log at DEBUG level "File already moved by handler — skipping executor move" (depends on T032)

**Checkpoint**: `TestLinkedInPostHandler` passes. DEV_MODE end-to-end: draft → approve → done in one poll cycle with zero browser calls.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Validation, linting, type checking, and end-to-end verification.

- [X] T034 [P] Run full test suite: `uv run pytest tests/test_content_scheduler.py -v` — all tests must pass
- [X] T035 [P] Run type checking: `uv run mypy backend/scheduler/ backend/orchestrator/orchestrator.py backend/orchestrator/action_executor.py` — zero type errors
- [X] T036 [P] Run linting: `uv run ruff check backend/scheduler/ && uv run ruff format --check backend/scheduler/` — zero lint errors
- [X] T037 End-to-end validation: follow all steps in `specs/003-content-scheduler/quickstart.md` — verify `--status`, `--preview`, `--generate-now` all work; verify draft file format matches data-model.md schema
- [X] T038 [P] Add `vault/Logs/decisions` and `vault/Logs/audit` to `VAULT_SUBDIRS` list in `backend/orchestrator/orchestrator.py` if not already present (per constitution Principle VII log structure)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 completion — **BLOCKS all user stories**
- **Phase 3 (US1)**: Depends on Phase 2 — MVP delivery point 🎯
- **Phase 4 (US2)**: Depends on Phase 2 — can start after Phase 2 (independently testable from US1)
- **Phase 5 (US3)**: Depends on Phase 3 US1 + Phase 4 US2 (needs `run_if_due()` and rotation)
- **Phase 6 (US4)**: Depends on Phase 3 US1 (needs `ContentScheduler.run_if_due()`)
- **Phase 7 (US5)**: Depends on Phase 3 US1 (needs draft format established)
- **Phase 8 (Polish)**: Depends on all desired phases complete

### User Story Dependencies

- **US1 (P1)**: Depends on Foundational only — no story dependencies
- **US2 (P2)**: Depends on Foundational only — independent from US1 (rotation is additive on top)
- **US3 (P3)**: Depends on US1 + US2 — CLI wraps `run_if_due()` (needs rotation to be meaningful)
- **US4 (P4)**: Depends on US1 — only needs `run_if_due()`
- **US5 (P5)**: Depends on US1 — only needs draft file format established

### Within Each Story

- Tests → Dataclasses/Models → Services → Integration (in each phase)
- Tests can be written before, during, or after implementation (spec does not mandate TDD)
- Marked [P] tasks within a story have no interdependencies and can be done simultaneously

### Parallel Opportunities

- **Phase 1**: T001, T002, T003, T004 all parallel
- **Phase 2**: T005 first; then T006 and T007 parallel
- **Phase 3 (US1)**: T008/T009 (tests) parallel; T010/T012/T013 parallel; T011 after T010; T014→T015→T016→T017 sequential
- **Phase 4 (US2)**: T018/T019 parallel; T020→T021→T022 sequential
- **Phase 5 (US3)**: T023 parallel; T024→T025→T026→T027 sequential
- **Phase 8**: T034/T035/T036/T038 all parallel; T037 after T034

---

## Parallel Example: User Story 1

```bash
# Sprint 1: Write tests + scaffold models simultaneously
Task T008: Write TestPostGenerator in tests/test_content_scheduler.py
Task T009: Write TestContentScheduler in tests/test_content_scheduler.py
Task T010: Implement TEMPLATES dict in backend/scheduler/post_generator.py
Task T012: Implement ScheduleManager.load_state/save_state in backend/scheduler/schedule_manager.py
Task T013: Implement ScheduleManager.is_post_due/draft_exists_today in backend/scheduler/schedule_manager.py

# Sprint 2: Complete generators and strategy loader (after Sprint 1)
Task T011: Implement PostGenerator.generate() in backend/scheduler/post_generator.py
Task T014: Implement ContentScheduler._load_strategy() in backend/scheduler/content_scheduler.py

# Sprint 3: Complete and wire up (sequential — each depends on previous)
Task T015: _load_context()
Task T016: _save_draft()
Task T017: run_if_due() — wires everything together
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T004)
2. Complete Phase 2: Foundational (T005–T007) — **CRITICAL prerequisite**
3. Complete Phase 3: User Story 1 (T008–T017)
4. **STOP and VALIDATE**: `uv run python -m backend.scheduler.content_scheduler` → draft appears in vault
5. **MVP is live** — daily draft generation works end-to-end

### Incremental Delivery

1. Phases 1–3 → **MVP: Daily draft generation**
2. Add Phase 4 → **Rotation: No consecutive topic repeats**
3. Add Phase 5 → **CLI control: --generate-now, --preview, --status**
4. Add Phase 6 → **Automation: Orchestrator checks on startup**
5. Add Phase 7 → **Full loop: Approved drafts auto-posted to LinkedIn**
6. Phase 8 → **Production ready: All tests pass, types clean**

### Parallel Team Strategy

After Phase 2 completes:
- **Dev A**: US1 (Phase 3) — core draft generation
- **Dev B**: US2 (Phase 4) — rotation logic
- **Dev C**: US5 (Phase 7) — action executor wiring

After all three complete, merge and add US3 (CLI) + US4 (orchestrator integration).

---

## Task Count Summary

| Phase | Story | Tasks | Parallel Tasks |
|-------|-------|-------|---------------|
| Phase 1: Setup | — | 4 | 3 |
| Phase 2: Foundational | — | 3 | 2 |
| Phase 3: US1 (P1 MVP) | US1 | 10 | 5 |
| Phase 4: US2 | US2 | 5 | 2 |
| Phase 5: US3 | US3 | 5 | 1 |
| Phase 6: US4 | US4 | 3 | 0 |
| Phase 7: US5 | US5 | 3 | 0 |
| Phase 8: Polish | — | 5 | 4 |
| **TOTAL** | | **38** | **17** |

**MVP scope**: T001–T017 (17 tasks, Phases 1–3)
**Test tasks**: T008, T009, T018, T019, T023, T028, T031 (7 tasks across stories)

---

## Notes

- `type: linkedin_post` NOT `action_type:` — existing `action_executor.py:81` reads `fm.get("type")` (spec correction from research.md RQ-1)
- T033 (file lifecycle fix) is critical — without it, `action_executor` and `LinkedInPoster` both try to `shutil.move()` the same file
- All templates must reference Taha's persona ("Agentic AI & Senior Backend Engineer") — see T010
- `vault/Content_Strategy.md` body section headings must exactly match: `## Topics I Want to Post About`, `## Content Rules`, `## Do NOT Post About` — these are the parsing anchors in `_load_strategy()`
- Commit after each phase checkpoint for clean rollback points
