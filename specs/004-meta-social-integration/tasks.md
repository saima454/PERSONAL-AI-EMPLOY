# Tasks: Meta Social Integration (Facebook & Instagram)

**Input**: Design documents from `/specs/004-meta-social-integration/`
**Prerequisites**: spec.md ✓ | plan.md ✓ | research.md ✓ | data-model.md ✓ | contracts/ ✓ | quickstart.md ✓
**Branch**: `004-meta-social-integration`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no shared dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration and skill definition — no source code changes yet

- [X] T001 Add `FACEBOOK_CHECK_INTERVAL`, `FACEBOOK_KEYWORDS`, `FACEBOOK_SESSION_PATH`, `FACEBOOK_HEADLESS`, `INSTAGRAM_CHECK_INTERVAL`, `INSTAGRAM_KEYWORDS`, `INSTAGRAM_SESSION_PATH`, `INSTAGRAM_HEADLESS` env vars with comments to `config/.env.example`
- [X] T002 [P] Create `skills/social-media-manager/SKILL.md` defining the Social Media Manager skill (metadata: name, version, triggers; body: monitor Facebook, monitor Instagram, post to Facebook, post to Instagram; permissions: requires Meta session; DEV_MODE behavior; rate limits)
- [X] T003 [P] Verify `config/meta_session/` and `config/meta_session/**` are listed in `.gitignore` (add if missing — session cookies must never be committed)

**Checkpoint**: Infrastructure ready — no source files changed yet

---

## Phase 2: User Story 1 — Meta Session Setup (Priority: P1) 🎯 MVP

**Goal**: Establish a shared Playwright persistent context at `config/meta_session/` that serves both Facebook and Instagram watchers and posters. Session expiry detected gracefully.

**Independent Test**: Run `python backend/watchers/facebook_watcher.py --setup` → browser opens → log in → Press Enter → verify `config/meta_session/` contains Chromium profile data. Re-run → verify session is reused without login prompt.

**⚠️ FOUNDATIONAL**: User Stories 2–5 all depend on this phase being complete. Session management code lives in the watcher classes but blocks all Meta functionality.

- [X] T004 [US1] Create `backend/watchers/facebook_watcher.py` with `FacebookWatcher(BaseWatcher)` class: `__init__(vault_path, session_path="config/meta_session", check_interval=120, keywords=None, headless=True, dry_run=True, dev_mode=True)`, `_launch_browser()` using `async_playwright().launch_persistent_context(user_data_dir=session_path, headless=headless)`, `_close_browser()`, `_ensure_browser()`, `_navigate_and_wait(url, wait_seconds)` — adapted from `backend/watchers/linkedin_watcher.py`
- [X] T005 [US1] Add `_check_session_state() -> str` to `backend/watchers/facebook_watcher.py`: returns `"ready"` / `"login_required"` / `"captcha"` / `"unknown"` — URL-based first (`"/login"` or `"checkpoint"` in `self._page.url`), then DOM probe (`input[name="email"]`), then broad element count heuristic (>40 elements = logged in)
- [X] T006 [US1] Add `setup_session() -> bool` to `backend/watchers/facebook_watcher.py`: open headed browser at `facebook.com/`, show terminal prompt instructing user to log in to Facebook then navigate to `instagram.com` and log in, wait for Enter, re-check session state, wait 30s for Playwright to persist cookies to `config/meta_session/`, return True on success
- [X] T007 [US1] Add `DEV_MODE` short-circuit to `FacebookWatcher.check_for_updates()` in `backend/watchers/facebook_watcher.py`: if `self.dev_mode` is True, skip browser launch, log `"[DEV_MODE] FacebookWatcher: returning synthetic item"`, return one synthetic dict with `sender: "[DEV_MODE]"`, `item_type: "notification"`, `priority: "low"`, `matched_keyword: "dev"`
- [X] T008 [P] [US1] Create `backend/watchers/instagram_watcher.py` with `InstagramWatcher(BaseWatcher)` class mirroring FacebookWatcher structure: same `__init__` signature (same `session_path` default `"config/meta_session"`), same browser management methods, `_check_session_state()` adapted for instagram.com URL patterns (`"/accounts/login/"` in URL), same DEV_MODE guard in `check_for_updates()`
- [X] T009 [P] [US1] Add `setup_session() -> bool` to `backend/watchers/instagram_watcher.py`: open headed browser at `instagram.com/`, prompt user to log in (note: can use "Continue with Facebook" if already in same browser context), wait for Enter, verify session, wait 30s, return True — reuses same `config/meta_session/` directory
- [X] T010 [US1] Register `FacebookWatcher` and `InstagramWatcher` factory functions in `backend/orchestrator/orchestrator.py` `_build_watcher_configs()` method: add `_facebook_factory()` (reads `FACEBOOK_CHECK_INTERVAL`, `FACEBOOK_KEYWORDS`, `FACEBOOK_SESSION_PATH`, `FACEBOOK_HEADLESS`) and `_instagram_factory()` (reads `INSTAGRAM_CHECK_INTERVAL`, `INSTAGRAM_KEYWORDS`, `INSTAGRAM_SESSION_PATH`, `INSTAGRAM_HEADLESS`) following the exact pattern of `_linkedin_factory()`

**Checkpoint**: Meta session can be established manually. Orchestrator starts both watchers (they return empty results if session missing). DEV_MODE returns synthetic data.

---

## Phase 3: User Story 2 — Facebook Monitoring (Priority: P2)

**Goal**: FacebookWatcher polls `facebook.com/notifications/` and `facebook.com/messages/` on a configurable interval, creates vault files in `vault/Needs_Action/` for keyword-matching items, deduplicates by notification key.

**Independent Test**: `DEV_MODE=true python backend/watchers/facebook_watcher.py --once` → logs `[DEV_MODE]` synthetic item. With real session + `DEV_MODE=false`, trigger a Facebook notification → verify `vault/Needs_Action/FACEBOOK_*.md` appears with correct frontmatter.

- [X] T011 [US2] Add `_load_processed_ids()`, `_save_processed_ids()`, `_cleanup_old_ids()` to `backend/watchers/facebook_watcher.py` using `vault/Logs/processed_facebook.json` — same schema as `processed_linkedin.json` (`{"processed_ids": {key: iso_ts}, "last_cleanup": iso_ts}`), 7-day retention, cleanup runs once per 24h
- [X] T012 [US2] Add `_scan_notifications() -> list[dict]` to `backend/watchers/facebook_watcher.py`: navigate to `https://www.facebook.com/notifications/`, check session state (return `[]` if `login_required`/`captcha`), use broad selector cascade (`div[role="feed"] > div`, `main li`, `main article`) to find up to 20 notification elements, extract text/actor/time via `inner_text()`, apply keyword filter via `_classify_priority()`, deduplicate against `self._processed_ids`
- [X] T013 [US2] Add `_scan_messages() -> list[dict]` to `backend/watchers/facebook_watcher.py`: navigate to `https://www.facebook.com/messages/`, extract conversation thread list using broad selectors (`[role="list"] li`, `[aria-label*="conversation"]`), cap at 15, set `item_type: "message"` and `needs_reply: true` for keyword-matching threads
- [X] T014 [US2] Implement `check_for_updates() -> list[dict]` in `backend/watchers/facebook_watcher.py`: call `_load_processed_ids()` + `_cleanup_old_ids()`, call `_ensure_browser()`, call `_scan_notifications()` + `_scan_messages()`, reset `_consecutive_errors` on success, return combined list — wrap in `try/except` catching all exceptions (log + return `[]`)
- [X] T015 [US2] Implement `create_action_file(item) -> Path | None` in `backend/watchers/facebook_watcher.py`: build filename `FACEBOOK_{sender_slug}_{timestamp}.md`, construct frontmatter per Contract 2 schema (`type: facebook`, `source: facebook_watcher`, `item_type`, `sender`, `preview[:200]`, `received`, `priority`, `status: pending`, optional `matched_keyword`, optional `needs_reply`), use `create_file_with_frontmatter()`, update `_processed_ids`, call `_save_processed_ids()`, log to `vault/Logs/actions/`; return `None` on dry_run
- [X] T016 [US2] Override `run()` in `backend/watchers/facebook_watcher.py` to call `_ensure_browser()` on startup then enter polling loop; add `_log_error()` for structured error logging to `vault/Logs/errors/`; add CLI `main()` with `argparse` supporting `--once` and `--setup` flags + env var loading from `config/.env`; add `if __name__ == "__main__": main()` guard
- [X] T017 [US2] Add `_save_debug_screenshot(label)` to `backend/watchers/facebook_watcher.py`: saves PNG to `vault/Logs/debug_screenshot_{label}.png` on any scraping failure — mirror of existing LinkedIn watcher method

**Checkpoint**: `DEV_MODE=true python backend/watchers/facebook_watcher.py --once` completes without error. Dedup prevents duplicate files across consecutive calls.

---

## Phase 4: User Story 3 — Facebook Auto-Post (Priority: P3)

**Goal**: `FacebookPoster` scans `vault/Approved/` for `type: facebook_post` files, validates character count ≤ 63,206, publishes to Facebook via Playwright, moves file to `vault/Done/` or `vault/Rejected/`. ActionExecutor routes `facebook_post` type to this poster.

**Independent Test**: Place `FACEBOOK_POST_test.md` with `type: facebook_post`, `status: approved`, body ≤ 63,206 chars in `vault/Approved/`. `DEV_MODE=true` → verify file moves to `vault/Done/` with `status: done`. `DEV_MODE=false` → verify post appears on Facebook (manual check).

- [X] T018 [US3] Create `backend/actions/facebook_poster.py` with `FacebookPoster` class: `__init__(vault_path, session_path="config/meta_session", headless=True, dry_run=True, dev_mode=True)`, `_launch_browser()` / `_close_browser()` using same Playwright persistent context pattern as `backend/actions/linkedin_poster.py`
- [X] T019 [US3] Add `_check_session_state()` to `backend/actions/facebook_poster.py`: URL-based detection for Facebook login page, same pattern as FacebookWatcher — needed before attempting to publish
- [X] T020 [US3] Add `_validate_post(body, fm) -> str | None` to `backend/actions/facebook_poster.py`: return `None` if valid, or `rejection_reason` string (`"empty_body"` if body stripped of whitespace is empty, `"character_count_exceeded"` if `len(body) > 63206`, `"image_file_not_found"` if `fm.get("image_path")` is set but `Path(image_path).exists()` is False)
- [X] T021 [US3] Add `_publish_post(body, image_path=None) -> bool` to `backend/actions/facebook_poster.py`: navigate to `https://www.facebook.com/`, find "What's on your mind?" composer using broad selectors (`[aria-label*="post" i]`, `[placeholder*="mind"]`, `div[role="button"]`), click to open editor, type post text via `keyboard.type()`, optionally upload image via file input, click Post/Submit button, return True on success
- [X] T022 [US3] Implement `process_approved_posts() -> int` in `backend/actions/facebook_poster.py`: scan `vault/Approved/*.md` for `status: approved` AND `type: facebook_post`, extract body (content after frontmatter), validate, DEV_MODE → log `"[DEV_MODE] Would post to Facebook: {body[:100]}"` + move to Done; real mode → call `_publish_post()`, move to Done on success or Rejected with `rejection_reason` on failure; update frontmatter (`status: done/rejected`, `published_at`/`rejected_at`, `rejection_reason`); respect `MAX_POSTS_PER_RUN = 5`; return count of processed posts
- [X] T023 [US3] Add `_handle_facebook_post(file_path, _fm, _cid) -> None` to `backend/orchestrator/action_executor.py` and add `"facebook_post": "_handle_facebook_post"` to `HANDLERS` dict — follows exact pattern of `_handle_linkedin_post()`: lazy-import `FacebookPoster`, call `process_approved_posts()`, close browser in `finally`, raise `RuntimeError` if count == 0
- [X] T024 [US3] Add CLI `main()` to `backend/actions/facebook_poster.py` with `--once` flag, env var loading from `config/.env`, `argparse` description; add `if __name__ == "__main__": main()` guard

**Checkpoint**: Place approved `facebook_post` file in `vault/Approved/` → run orchestrator in DEV_MODE → verify file in `vault/Done/` with `status: done`.

---

## Phase 5: User Story 4 — Instagram Monitoring (Priority: P4)

**Goal**: `InstagramWatcher` polls `instagram.com/activity/` and `instagram.com/direct/inbox/` on a configurable interval, creates vault files in `vault/Needs_Action/` for keyword-matching items, deduplicates using `processed_instagram.json`.

**Independent Test**: `DEV_MODE=true python backend/watchers/instagram_watcher.py --once` → synthetic vault file logged. With real session, trigger Instagram DM → verify `vault/Needs_Action/INSTAGRAM_*.md` appears.

- [X] T025 [US4] Add `_load_processed_ids()`, `_save_processed_ids()`, `_cleanup_old_ids()` to `backend/watchers/instagram_watcher.py` using `vault/Logs/processed_instagram.json` — same schema and 7-day retention as `processed_facebook.json`
- [X] T026 [US4] Add `_scan_notifications() -> list[dict]` to `backend/watchers/instagram_watcher.py`: navigate to `https://www.instagram.com/activity/`, check session state (return `[]` on `login_required`), use broad selectors (`main li`, `[role="list"] li`, `article`) to find up to 20 notification elements, extract text/actor/time via `inner_text()`, apply keyword filter, dedup against `self._processed_ids`
- [X] T027 [US4] Add `_scan_direct_messages() -> list[dict]` to `backend/watchers/instagram_watcher.py`: navigate to `https://www.instagram.com/direct/inbox/`, extract conversation threads using broad selectors (`[role="listbox"] > div`, `div[class*="thread"]`, `main div`), cap at 15, set `item_type: "direct_message"` and `needs_reply: true` for keyword-matching conversations
- [X] T028 [US4] Implement `check_for_updates() -> list[dict]` in `backend/watchers/instagram_watcher.py`: load/cleanup dedup IDs, ensure browser, scan notifications + DMs, return combined list — same error handling pattern as `FacebookWatcher.check_for_updates()` (catch all exceptions, return `[]`)
- [X] T029 [US4] Implement `create_action_file(item) -> Path | None` in `backend/watchers/instagram_watcher.py`: build filename `INSTAGRAM_{sender_slug}_{timestamp}.md`, construct frontmatter per Contract 3 schema (`type: instagram`, `source: instagram_watcher`, `item_type` as `"notification"` or `"direct_message"`, `sender`, `preview[:200]`, `received`, `priority`, `status: pending`, optional `matched_keyword`, optional `needs_reply`), create file, update dedup store, log action; return `None` on dry_run
- [X] T030 [US4] Override `run()` in `backend/watchers/instagram_watcher.py` + add `_log_error()` + `_save_debug_screenshot()` + CLI `main()` with `--once` and `--setup` flags — mirrors `facebook_watcher.py:main()` exactly with Instagram-specific defaults

**Checkpoint**: Both `facebook_watcher.py --once` and `instagram_watcher.py --once` work in DEV_MODE. Dedup confirmed across 2 consecutive calls.

---

## Phase 6: User Story 5 — Content Scheduler Integration (Priority: P5)

**Goal**: `PostGenerator.generate()` reads optional `platform` field from topic dict and sets `type: {platform}_post` in draft frontmatter. Instagram drafts validated to ≤ 2,200 chars. `InstagramPoster` added as a full poster. `action_executor.py` routes `instagram_post` type.

**Independent Test**: Add `platform: facebook` topic to `vault/Content_Strategy.md` → run `python -m backend.scheduler.content_scheduler --generate-now` → verify `vault/Pending_Approval/FACEBOOK_POST_*.md` with `type: facebook_post`. Repeat for `platform: instagram` → verify `INSTAGRAM_POST_*.md` with `type: instagram_post` and `character_count ≤ 2200`.

- [X] T031 [US5] Modify `generate()` in `backend/scheduler/post_generator.py`: add `platform = topic.get("platform", "linkedin")` at top of method; set `frontmatter["type"] = f"{platform}_post"` (was hardcoded `"linkedin_post"`); set `frontmatter["platform"] = platform` — this change is backward-compatible (topics without `platform` default to `"linkedin"`)
- [X] T032 [US5] Add Instagram character count validation in `backend/scheduler/post_generator.py`: after generating post body, if `platform == "instagram"` and `len(body) > 2200`, log warning `"Instagram draft exceeds 2200 chars ({len(body)}), truncating"` and truncate body to 2200 with `"...\n[truncated to fit Instagram limit]"` appended
- [X] T033 [US5] Update `vault/Content_Strategy.md` to document the optional `platform` field: add a section explaining `platform: linkedin | facebook | instagram` (default: `linkedin`) with one example topic per platform — no YAML format change, just adds new example entries and a comment explaining the field
- [X] T034 [US5] Add `_handle_instagram_post(file_path, _fm, _cid) -> None` to `backend/orchestrator/action_executor.py` and register `"instagram_post": "_handle_instagram_post"` in `HANDLERS` dict — same pattern as `_handle_facebook_post()` but uses `InstagramPoster`
- [X] T035 [US5] Create `backend/actions/instagram_poster.py` with `InstagramPoster` class: `__init__(vault_path, session_path="config/meta_session", headless=True, dry_run=True, dev_mode=True)`, same `_launch_browser()` / `_close_browser()` pattern, `_check_session_state()` adapted for instagram.com login URL detection
- [X] T036 [US5] Add `_validate_post(body, fm) -> str | None` and `_publish_post(body, image_path=None) -> bool` to `backend/actions/instagram_poster.py`: validate `len(body) ≤ 2200` (rejection_reason: `"character_count_exceeded"`), navigate to `instagram.com`, find Create/+ button, open caption editor, type caption, optionally attach image, submit
- [X] T037 [US5] Implement `process_approved_posts() -> int` in `backend/actions/instagram_poster.py` + CLI `main()` with `--once` flag: same structure as `FacebookPoster.process_approved_posts()` but scans for `type: instagram_post`, validates ≤ 2200 chars, moves to Done/Rejected, respects DEV_MODE

**Checkpoint**: `python -m backend.scheduler.content_scheduler --generate-now` with a `platform: instagram` topic produces `INSTAGRAM_POST_*.md` with `type: instagram_post` and `character_count ≤ 2200`.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Tests, lint, end-to-end validation

- [X] T038 [P] Write `tests/test_meta_social.py` with ~50 tests across 7 classes: `TestMetaSessionSetup` (session detection, expiry, DEV_MODE guard), `TestFacebookWatcher` (notifications, dedup, keyword filter, dry_run, DEV_MODE), `TestInstagramWatcher` (mirror of Facebook), `TestFacebookPoster` (validation rules, DEV_MODE publish, lifecycle: Done/Rejected), `TestInstagramPoster` (2200-char limit, DEV_MODE, lifecycle), `TestContentSchedulerPlatform` (platform routing in PostGenerator, backward-compat with no-platform topic), `TestActionExecutorMeta` (facebook_post and instagram_post dispatch via HANDLERS) — all using mocked Playwright (`AsyncMock`) and `tmp_path` vault fixture
- [X] T039 [P] Run `uv run pytest tests/ -v` to confirm all new tests pass AND existing 351-test baseline shows zero regressions; capture total count in tasks.md
- [X] T040 [P] Run `uv run ruff check backend/watchers/facebook_watcher.py backend/watchers/instagram_watcher.py backend/actions/facebook_poster.py backend/actions/instagram_poster.py backend/orchestrator/action_executor.py backend/scheduler/post_generator.py` and fix any lint errors (noqa annotations for ARG002 on `_fm`/`_cid` handler params, I001 import ordering, etc.)
- [X] T041 Validate end-to-end in DEV_MODE: add a `platform: facebook` topic to `vault/Content_Strategy.md`, run `uv run python -m backend.scheduler.content_scheduler --generate-now`, verify `vault/Pending_Approval/FACEBOOK_POST_*.md` exists with `type: facebook_post`, `status: pending_approval`; repeat for `platform: instagram` to verify `INSTAGRAM_POST_*.md` with `character_count ≤ 2200`
- [X] T042 Mark all completed tasks [X] in this `specs/004-meta-social-integration/tasks.md` file

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
    └─► Phase 2 (US1: Meta Session — FOUNDATIONAL)
            └─► Phase 3 (US2: FB Monitoring)    ─┐
            └─► Phase 4 (US3: FB Auto-Post)      ├─► Phase 7 (Polish)
            └─► Phase 5 (US4: IG Monitoring)     ├─►
            └─► Phase 6 (US5: CS Integration)   ─┘
```

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (US1 — Foundational)**: Depends on Phase 1
- **Phases 3–6 (US2–US5)**: All depend on Phase 2 completion; can run in parallel with each other
- **Phase 7 (Polish)**: Depends on Phases 3–6 completion

### User Story Dependencies

| Story | Depends On | Can Parallel With |
|-------|-----------|-------------------|
| US1 (Meta Session) | Phase 1 (Setup) | — (must complete first) |
| US2 (FB Monitoring) | US1 | US3, US4, US5 |
| US3 (FB Auto-Post) | US1 | US2, US4, US5 |
| US4 (IG Monitoring) | US1 | US2, US3, US5 |
| US5 (CS Integration) | US1 | US2, US3, US4 |

### Within Each User Story

- Browser management methods before session detection (T004 → T005)
- Session setup before monitoring (T006 → T011)
- Scan methods before check_for_updates (T012, T013 → T014)
- check_for_updates before create_action_file (T014 → T015)
- Validation before publishing (T020 → T021 → T022)

---

## Parallel Examples

### Phase 1: All 3 tasks can run in parallel

```bash
Task: T001 — Add env vars to config/.env.example
Task: T002 — Create skills/social-media-manager/SKILL.md
Task: T003 — Verify config/meta_session/ in .gitignore
```

### Phase 2: T008/T009 can run in parallel with T004–T007

```bash
# While building FacebookWatcher (T004–T007):
Task: T008 — Create backend/watchers/instagram_watcher.py skeleton
Task: T009 — Add setup_session() to instagram_watcher.py
```

### Phases 3–6: All four user stories can proceed in parallel after Phase 2

```bash
Task: Phase 3 (US2: FB Monitoring)    — developer A
Task: Phase 4 (US3: FB Auto-Post)     — developer B
Task: Phase 5 (US4: IG Monitoring)    — developer C
Task: Phase 6 (US5: CS Integration)   — developer D
```

### Phase 7: T038/T039/T040 can run in parallel

```bash
Task: T038 — Write test_meta_social.py
Task: T039 — Run pytest baseline check
Task: T040 — Run ruff lint check
```

---

## Implementation Strategy

### MVP: User Story 1 Only (Phase 1 + Phase 2)

1. Complete Phase 1 (Setup) — T001–T003
2. Complete Phase 2 (US1: Meta Session) — T004–T010
3. **STOP and VALIDATE**: Run `python backend/watchers/facebook_watcher.py --setup` manually, verify `config/meta_session/` saves. Run orchestrator — both watchers start without crashing.
4. Demo: Orchestrator starts with Facebook + Instagram watchers visible in logs.

### Incremental Delivery

1. **MVP**: Phase 1 + Phase 2 → Meta session management works
2. **+US2**: Phase 3 → Facebook notifications captured in vault (safe, read-only)
3. **+US3**: Phase 4 → Facebook posts published from vault (HITL required first)
4. **+US4**: Phase 5 → Instagram notifications captured (mirrors US2)
5. **+US5**: Phase 6 → Content Scheduler generates FB/IG drafts
6. **Polish**: Phase 7 → Tests + lint + end-to-end validation

---

## Task Count Summary

| Phase | User Story | Tasks | Parallel Opportunities |
|-------|-----------|-------|----------------------|
| Phase 1: Setup | — | T001–T003 (3) | All 3 |
| Phase 2: Foundational | US1 (P1) | T004–T010 (7) | T008/T009 ∥ T004–T007 |
| Phase 3 | US2 (P2) | T011–T017 (7) | T012/T013 ∥ each other |
| Phase 4 | US3 (P3) | T018–T024 (7) | T018/T019 ∥ each other |
| Phase 5 | US4 (P4) | T025–T030 (6) | T026/T027 ∥ each other |
| Phase 6 | US5 (P5) | T031–T037 (7) | T031/T032 ∥ each other |
| Phase 7: Polish | — | T038–T042 (5) | T038/T039/T040 ∥ all 3 |
| **Total** | | **42 tasks** | |
