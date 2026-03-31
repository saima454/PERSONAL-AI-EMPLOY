---
description: "Task list for Feature 005: Twitter (X) Integration"
---

# Tasks: Twitter (X) Integration

**Input**: Design documents from `/specs/005-twitter-x-integration/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, quickstart.md ✓

**Organization**: Tasks are grouped by user story (US1–US4) enabling independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: User story label (US1–US4)
- All file paths are relative to repo root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Environment configuration required by all user stories before any code is written.

- [X] T001 Add `config/twitter_session/` to .gitignore (below the existing `config/meta_session/` entry)
- [X] T002 Add TWITTER_CHECK_INTERVAL=300, TWITTER_KEYWORDS=urgent,help,project,collab,opportunity,mention, TWITTER_SESSION_PATH=config/twitter_session, TWITTER_HEADLESS=false to config/.env.example (below INSTAGRAM section)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create the two new Python module files with class scaffolding and constants. Both TwitterWatcher (US1+US2) and TwitterPoster (US3) require their file shells before phase-specific methods can be added.

**⚠️ CRITICAL**: No user story implementation can begin until these files exist.

- [X] T003 Create `backend/watchers/twitter_watcher.py` — add module docstring, `from __future__ import annotations` imports (argparse, asyncio, json, logging, os, re, Path, Any, dotenv, and all backend.utils imports + BaseWatcher), constants (DEFAULT_KEYWORDS, HIGH_PRIORITY_KEYWORDS, MEDIUM_PRIORITY_KEYWORDS, PROCESSED_IDS_RETENTION_DAYS=7, MAX_NOTIFICATIONS=20, MAX_MESSAGES=15), and three module-level helper functions: `_slugify(text, max_length=40)`, `_classify_priority(text, keywords)`, `_make_dedup_key(sender, text, timestamp)` — identical signatures and logic to `facebook_watcher.py`

- [X] T004 Create `backend/actions/twitter_poster.py` — add module docstring, imports (argparse, asyncio, contextlib, logging, os, shutil, Path, Any, dotenv, backend.utils), constants (TWITTER_CHAR_LIMIT=280, MAX_POSTS_PER_RUN=5, POST_CHECK_INTERVAL=300), and selector dicts: `POST_SELECTORS = {"text_area": ["div[data-testid='tweetTextarea_0']", "div[role='textbox'][aria-label*='tweet' i]", "div[aria-label='Post text']", "div[contenteditable='true']"], "submit_button": ["button[data-testid='tweetButtonInline']", "button[data-testid='tweetButton']", "div[data-testid='tweetButtonInline']", "button[aria-label='Post']"]}` and `AUTHENTICATED_SELECTORS = ["[data-testid='AppTabBar_Home_Link']", "[data-testid='primaryColumn']", "[data-testid='sidebarColumn']", "a[href='/compose/post']"]`

**Checkpoint**: Both new module files exist — user story implementation can now proceed.

---

## Phase 3: User Story 1 — Twitter Session Setup (Priority: P1) 🎯 MVP

**Goal**: Users can run `--setup` once to authenticate with Twitter/X; subsequent runs reuse the session automatically.

**Independent Test**: Run `uv run python backend/watchers/twitter_watcher.py --setup` → browser opens → after login + Enter → session saved to `config/twitter_session/`. Then run `--once` (DEV_MODE=true) → no login prompt shown, watcher returns synthetic item.

- [X] T005 [US1] Add `TwitterWatcher` class to `backend/watchers/twitter_watcher.py` — `__init__(self, vault_path, session_path="config/twitter_session", check_interval=300, keywords=None, headless=False, dry_run=True, dev_mode=True)` with all instance attributes including `self.processed_ids_path = self.logs_path / "processed_twitter.json"`, `self._processed_ids`, `self._last_cleanup`, `self._consecutive_errors`, `self._context`, `self._page`; call `super().__init__(vault_path, check_interval)`

- [X] T006 [US1] Add browser management methods to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: `_launch_browser()` using `chromium.launch_persistent_context(user_data_dir=str(self.session_path), headless=self.headless, args=["--disable-blink-features=AutomationControlled"])`, `_close_browser()`, `_ensure_browser()` — identical pattern to `facebook_watcher.py`

- [X] T007 [US1] Add navigation helpers to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: `_navigate_and_wait(url, wait_seconds=8.0)` using `goto(url, wait_until="domcontentloaded", timeout=60000)` + `contextlib.suppress(Exception)` for networkidle wait + `asyncio.sleep(wait_seconds)`; `_save_debug_screenshot(label="debug")` writing to `self.logs_path / f"debug_screenshot_tw_{label}.png"`

- [X] T008 [US1] Add session state detection to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: `_check_session_state()` — URL check: `"/i/flow/login"` or `"/login"` → `"login_required"`; `"/account/suspended"` or `"/i/flow/consent"` → `"captcha"`; DOM check cascade: `[data-testid="AppTabBar_Home_Link"]`, `[data-testid="primaryColumn"]`, `[data-testid="sidebarColumn"]` → `"ready"`; broad element count > 20 → `"ready"`; default → `"unknown"`. Also add `_is_authenticated()` using same auth selectors

- [X] T009 [US1] Add `setup_session()` to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: set `self.headless = False`, `_launch_browser()`, navigate to `https://x.com/home`, check session state, if already ready wait 10s and return True; else print setup prompt (boxed instructions using logger.info), `await loop.run_in_executor(None, input)`, verify state again, wait 30s for session persistence, log success; always restore `self.headless` in finally block + `_close_browser()`

- [X] T010 [US1] Add `_parse_args()` and `main()` CLI entry point to `backend/watchers/twitter_watcher.py`: `--setup` flag calls `asyncio.run(watcher.setup_session())`; `--once` flag calls `single_check()` coroutine; default starts continuous `watcher.run()`; load `.env` from `config/.env`; read `VAULT_PATH`, `TWITTER_SESSION_PATH`, `TWITTER_CHECK_INTERVAL`, `TWITTER_HEADLESS`, `TWITTER_KEYWORDS`, `DRY_RUN`, `DEV_MODE` env vars; add `if __name__ == "__main__": main()` guard

**Checkpoint**: `uv run python backend/watchers/twitter_watcher.py --setup` runs without import errors. Session management methods are callable.

---

## Phase 4: User Story 2 — Twitter Notification Monitoring (Priority: P2)

**Goal**: System monitors Twitter notifications and DMs every TWITTER_CHECK_INTERVAL seconds, creates `type: twitter` action files for keyword-matching items, prevents duplicates via 7-day dedup store.

**Independent Test**: With DEV_MODE=true, run `--once` → creates `vault/Needs_Action/TWITTER_[DEV_MODE]_*.md` with `type: twitter`, `sender: "[DEV_MODE]"` — verifies full monitoring pipeline without real browser.

- [X] T011 [US2] Add deduplication methods to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: `_load_processed_ids()` reads `vault/Logs/processed_twitter.json` parsing `{"processed_ids": {...}, "last_cleanup": "..."}` with corrupt-file fallback; `_save_processed_ids()` writes same structure; `_cleanup_old_ids()` removes entries where `is_within_hours(processed_at, 7*24)` is False, updates `self._last_cleanup`, only runs once per 24 hours

- [X] T012 [US2] Add `_scan_notifications()` to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: navigate to `https://x.com/notifications`; check session state → return [] if `login_required` or `captcha`; try selector cascade: `article[data-testid="notification"]`, `[data-testid="notificationItem"]`, `article[data-testid="tweet"]`, `[data-testid="cellInnerDiv"]` (use first that returns 0 < count <= 100); limit to `MAX_NOTIFICATIONS`; for each card: extract `inner_text()`, actor from `[data-testid="User-Name"] span` or `strong`, timestamp from `time[datetime]`; call `_classify_priority()` — skip if no keyword match; check dedup; append dict with `item_type="notification"`, `sender`, `preview` (500 char limit), `time`, `priority`, `matched_keyword`, `dedup_key`, `needs_reply=False`

- [X] T013 [US2] Add `_scan_messages()` to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: navigate to `https://x.com/messages`; check session state → return [] if not ready; try selector cascade: `[data-testid="conversationItem"]`, `[data-testid="DMConversationItem"]`, `[data-testid="conversation"]`; limit to `MAX_MESSAGES`; for each thread: extract full text, sender from `[data-testid="DMConversationEntry-Name"]` or `strong` or first line, preview from `[data-testid="messageContent"]` or `span[dir="ltr"]`; classify priority, skip if no match; check dedup; append dict with `item_type="direct_message"`, `needs_reply=True`

- [X] T014 [US2] Add `check_for_updates()` to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: DEV_MODE short-circuit returns synthetic dict `{"item_type": "notification", "sender": "[DEV_MODE]", "preview": "[DEV_MODE] Synthetic Twitter mention for testing", "time": "just now", "priority": "low", "matched_keyword": "dev", "dedup_key": f"[DEV_MODE]|synthetic|{now_iso()}", "needs_reply": False}`; session path guard (return [] with warning if not exists); `_load_processed_ids()` + `_cleanup_old_ids()`; `_ensure_browser()`; call both `_scan_notifications()` and `_scan_messages()`; increment `self._consecutive_errors` on exception; call `_save_debug_screenshot("scan_error")` on error; log total counts; return combined list

- [X] T015 [US2] Add `create_action_file()` to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: filename = `f"TWITTER_{sender_slug}_{timestamp}.md"` using `_slugify(item["sender"])` and `format_filename_timestamp()`; frontmatter: `type="twitter"`, `id=f"TWITTER_{short_id()}_{timestamp}"`, `source="twitter_watcher"`, `item_type`, `sender`, `preview[:200]`, `received=now_iso()`, `priority`, `status="pending"`, `matched_keyword` (if set), `needs_reply` (if True); body: `## Twitter {item_type.title()}\n\n**From:** ...**Suggested Actions:** checklist`; DRY_RUN: log and return None without writing; real: `create_file_with_frontmatter(file_path, frontmatter, body)`, update `self._processed_ids[item["dedup_key"]] = now_iso()`, `_save_processed_ids()`, `log_action()` with `actor="twitter_watcher"`

- [X] T016 [US2] Add `_log_error()` and `run()` to `TwitterWatcher` in `backend/watchers/twitter_watcher.py`: `_log_error(target, error_msg)` writes to `self.logs_path / "errors"` via `log_action()` with `actor="twitter_watcher"`; `run()` logs startup message, calls `_ensure_browser()` if not dev_mode, enters `while True` polling `check_for_updates()` → `create_action_file()` per item → `asyncio.sleep(self.check_interval)`, `_close_browser()` in finally block

- [X] T017 [US2] Add `_twitter_factory()` to `_build_watcher_configs()` in `backend/orchestrator/orchestrator.py`: lazy-import `TwitterWatcher` from `backend.watchers.twitter_watcher`; read `TWITTER_SESSION_PATH` (default `"config/twitter_session"`), `TWITTER_CHECK_INTERVAL` (default `"300"`), `TWITTER_HEADLESS` (default `"false"`), `TWITTER_KEYWORDS` (split on comma); return `TwitterWatcher(vault_path=..., session_path=..., check_interval=..., keywords=..., headless=..., dry_run=self.config.dry_run, dev_mode=self.config.dev_mode)`; append `("Twitter", _twitter_factory)` to configs list — place after the Instagram factory entry

**Checkpoint**: `uv run python backend/watchers/twitter_watcher.py --once` (DEV_MODE=true) creates `vault/Needs_Action/TWITTER_[DEV_MODE]_*.md` with correct frontmatter.

---

## Phase 5: User Story 3 — Twitter Auto-Post (Priority: P3)

**Goal**: System publishes approved `type: twitter_post` drafts from `vault/Approved/` to Twitter/X; enforces 280-char limit; moves files to `vault/Done/` on success or `vault/Rejected/` on failure; DEV_MODE simulates the full lifecycle without real posting.

**Independent Test**: Place a `TWITTER_POST_*.md` with `type: twitter_post`, `status: approved`, body ≤ 280 chars in `vault/Approved/` → run poster (DEV_MODE=true) → file moves to `vault/Done/` with `status: done`, `dev_mode: true`.

- [X] T018 [US3] Add `TwitterPoster` class to `backend/actions/twitter_poster.py`: `__init__(self, vault_path, session_path="config/twitter_session", headless=False, dry_run=True, dev_mode=True)` — set `self.vault_path`, `self.session_path`, `self.approved_dir = vault_path / "Approved"`, `self.done_dir = vault_path / "Done"`, `self.rejected_dir = vault_path / "Rejected"`, `self.log_dir = vault_path / "Logs" / "actions"`, `self._context = None`, `self._page = None`

- [X] T019 [US3] Add browser management to `TwitterPoster` in `backend/actions/twitter_poster.py`: `_launch_browser()` using `chromium.launch_persistent_context(user_data_dir=str(self.session_path), headless=self.headless, args=["--disable-blink-features=AutomationControlled"])`; `_close_browser()` closes context and stops playwright; `_ensure_browser()` calls `_launch_browser()` if `self._page is None`

- [X] T020 [US3] Add `_check_session_state()` to `TwitterPoster` in `backend/actions/twitter_poster.py`: URL check for `"/i/flow/login"` or `"/login"` → `"login_required"`; URL check for `"/account/suspended"` → `"captcha"`; DOM cascade through `AUTHENTICATED_SELECTORS` (`[data-testid="AppTabBar_Home_Link"]`, `[data-testid="primaryColumn"]`, `[data-testid="sidebarColumn"]`, `a[href="/compose/post"]`) → `"ready"` if any found; default → `"unknown"`

- [X] T021 [US3] Add `_validate_post()` to `TwitterPoster` in `backend/actions/twitter_poster.py`: return `"empty_body"` if `not body.strip()`; return `"exceeds_character_limit"` if `len(body) > TWITTER_CHAR_LIMIT`; return `None` (valid) otherwise — no image_path check (Twitter poster does not support image attachment in this version)

- [X] T022 [US3] Add `_publish_post(body)` to `TwitterPoster` in `backend/actions/twitter_poster.py`: navigate to `https://x.com/home` with `wait_until="domcontentloaded"`; `contextlib.suppress(Exception)` for networkidle wait; `asyncio.sleep(5)`; call `_check_session_state()` — return False if not `"ready"`; find textarea using `POST_SELECTORS["text_area"]` cascade (try each selector, use first that returns non-None element); click textarea + `asyncio.sleep(1)` + `self._page.keyboard.type(body, delay=20)`; find submit button using `POST_SELECTORS["submit_button"]` cascade; click button + `asyncio.sleep(3)`; return True on success; log specific failures at each step; return False if any step fails

- [X] T023 [US3] Add `_move_to_done()` and `_move_to_rejected()` to `TwitterPoster` in `backend/actions/twitter_poster.py`: `_move_to_done(file_path, published_at)` — `self.done_dir.mkdir(parents=True, exist_ok=True)`, call `update_frontmatter(file_path, {"status": "done", "published_at": published_at})`, `shutil.move(str(file_path), str(self.done_dir / file_path.name))`; `_move_to_rejected(file_path, reason)` — same pattern with `{"status": "rejected", "rejected_at": now_iso(), "rejection_reason": reason}`; wrap `update_frontmatter` in try/except to not block file move on frontmatter failure

- [X] T024 [US3] Add `_scan_approved()` to `TwitterPoster` in `backend/actions/twitter_poster.py`: iterate `sorted(self.approved_dir.glob("*.md"))` (return [] if dir missing); for each: `extract_frontmatter(content)`, filter `fm.get("status") == "approved"` and `fm.get("type") == "twitter_post"`; return list of `(file_path, fm, body or "")` tuples

- [X] T025 [US3] Add `process_approved_posts()` to `TwitterPoster` in `backend/actions/twitter_poster.py`: scan approved, return 0 if none; limit to `MAX_POSTS_PER_RUN`; for each post: `_validate_post(body, fm)` — if rejection_reason: `_move_to_rejected()` + `log_action()` + increment count + continue; if `dev_mode or dry_run`: log `"[DEV_MODE] Would post to Twitter: {body[:100]}"`, `_move_to_done(file_path, now_iso())`, add `dev_mode: True` to done frontmatter (call `update_frontmatter` before `_move_to_done`), `log_action(result="dev_mode")`; else: `_ensure_browser()`, `_publish_post(body)` → success: `_move_to_done()` + log; failure: `_move_to_rejected("publish_failed")` + log; return total count

- [X] T026 [US3] Add `_parse_args()` and `main()` to `backend/actions/twitter_poster.py`: `--once` flag calls `asyncio.run(run_once())` which calls `process_approved_posts()` then `_close_browser()` in finally; default starts continuous loop sleeping `POST_CHECK_INTERVAL` between runs; read `VAULT_PATH`, `TWITTER_SESSION_PATH`, `TWITTER_HEADLESS`, `DRY_RUN`, `DEV_MODE` from env; add `if __name__ == "__main__": main()` guard

- [X] T027 [US3] Add `"twitter_post": "_handle_twitter_post"` to `HANDLERS` dict in `backend/orchestrator/action_executor.py` (after `"instagram_post"` entry)

- [X] T028 [US3] Add `_handle_twitter_post(self, file_path, _fm, _cid)` async method to `ActionExecutor` in `backend/orchestrator/action_executor.py`: lazy import `from backend.actions.twitter_poster import TwitterPoster`; instantiate with `vault_path`, `session_path=os.getenv("TWITTER_SESSION_PATH", "config/twitter_session")`, `headless=os.getenv("TWITTER_HEADLESS", "false").lower() == "true"`, `dry_run=self.config.dry_run`, `dev_mode=self.config.dev_mode`; call `await poster.process_approved_posts()` in try block; call `await poster._close_browser()` in finally; raise `RuntimeError` if count == 0 — follows `_handle_facebook_post` pattern exactly

**Checkpoint**: Place approved TWITTER_POST_*.md in vault/Approved/ → run `uv run python backend/actions/twitter_poster.py --once` (DEV_MODE=true) → file moves to vault/Done/ with `status: done`.

---

## Phase 6: User Story 4 — Content Scheduler Integration (Priority: P4)

**Goal**: Adding `[platform: twitter]` to a topic in `vault/Content_Strategy.md` causes the content scheduler to generate a `TWITTER_POST_{today}.md` draft in `vault/Pending_Approval/` with `type: twitter_post` and content ≤ 280 characters.

**Independent Test**: Add topic `"Build in Public [platform: twitter] - Hackathon updates"` to Content_Strategy.md → run `uv run python -m backend.scheduler.content_scheduler --generate-now` → `vault/Pending_Approval/TWITTER_POST_2026-02-21.md` appears with `type: twitter_post`, `character_count` ≤ 280.

- [X] T029 [P] [US4] Add `TWITTER_CHAR_LIMIT = 280` constant to `backend/scheduler/post_generator.py` (after `INSTAGRAM_CHAR_LIMIT = 2_200`); in `generate(platform="linkedin", ...)`: add Twitter validation — if `platform == "twitter"` and `len(body) > TWITTER_CHAR_LIMIT`: truncate with `body = body[:TWITTER_CHAR_LIMIT]` and log warning `"Twitter template exceeded 280 chars, truncated"` (emergency fallback — templates are authored ≤280 chars); add `platform` field to `GeneratedPost.platform` if not already present (already done in Feature 004)

- [X] T030 [P] [US4] Add 5 Twitter-specific `PostTemplate` entries to `TEMPLATES` dict in `backend/scheduler/post_generator.py` — one per topic key, all with `format_type="twitter_short"`, all body strings ≤ 280 characters: (1) `twitter_ai_01` for `ai_automation` — casual take on AI agents/HITL; (2) `twitter_backend_01` for `backend_development` — punchy backend dev insight; (3) `twitter_hackathon_01` for `hackathon_journey` — real-time hackathon update; (4) `twitter_cloud_01` for `cloud_devops` — quick DevOps hot take; (5) `twitter_career_01` for `career_tips` — career observation. Each must include 1-3 hashtags embedded in body. Verify `len(body) <= 280` for each.

- [X] T031 [P] [US4] Add `"TWITTER"` to platforms tuple in `draft_exists_today()` in `backend/scheduler/schedule_manager.py`: change `platforms = ("LINKEDIN", "FACEBOOK", "INSTAGRAM")` to `platforms = ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TWITTER")`

**Checkpoint**: `uv run python -m backend.scheduler.content_scheduler --generate-now` (with twitter topic in Content_Strategy.md) creates `vault/Pending_Approval/TWITTER_POST_*.md` with correct frontmatter and body ≤ 280 chars.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Skill definition, full test suite, linting, E2E validation, and task completion marking.

- [X] T032 Create `skills/twitter-manager/SKILL.md` — Twitter Manager skill definition with: Metadata (name, version, tier=Gold, triggers, dependencies on config/twitter_session/, permissions, rate limits=5 posts/day, sensitivity=HIGH); Body with 4 capabilities: Monitor Twitter Notifications, Monitor Twitter DMs, Post to Twitter, Generate Twitter Drafts via Scheduler; each capability: what it does, how it triggers, DEV_MODE behavior, output format, decision tree; Session Setup section; Error Handling table; Resources section listing all related files

- [X] T033 Write `tests/test_twitter.py` — 7 test classes using pytest + pytest-asyncio + unittest.mock.AsyncMock:
  - `TestTwitterPoster` (~12 tests): `_validate_post()` — empty body, exact 280 chars (valid), 281 chars (rejected), well under limit; `process_approved_posts()` DEV_MODE → file moves to Done with status=done; `process_approved_posts()` exceeds limit → moves to Rejected with rejection_reason=exceeds_character_limit; `_scan_approved()` filters by type=twitter_post and status=approved; no approved files → returns 0
  - `TestTwitterWatcher` (~10 tests): DEV_MODE `check_for_updates()` returns 1 synthetic item without launching browser; session path missing → returns []; `create_action_file()` creates correct frontmatter (type=twitter, source=twitter_watcher); dry_run=True → returns None, no file written; keyword match → action file created, dedup key stored
  - `TestTwitterSessionSetup` (~5 tests): `_check_session_state()` with URL containing `/i/flow/login` → `"login_required"`; URL containing `/account/suspended` → `"captcha"`; mock `[data-testid="AppTabBar_Home_Link"]` found → `"ready"`; mock no auth selectors → `"unknown"`; `setup_session()` when already authenticated → returns True without input prompt
  - `TestContentSchedulerTwitter` (~8 tests): `_parse_topics()` with `[platform: twitter]` tag extracts platform=twitter; TWITTER_POST filename generated; `_save_draft()` sets type=twitter_post frontmatter; `draft_exists_today()` returns True when TWITTER_POST_{today}.md exists; `draft_exists_today()` returns False when no twitter draft; generate() with platform=twitter returns body ≤ 280 chars; template with exactly 280 chars accepted
  - `TestActionExecutorTwitter` (~6 tests): HANDLERS dict contains "twitter_post" key; HANDLERS["twitter_post"] == "_handle_twitter_post"; `_handle_twitter_post()` calls `process_approved_posts()`; `_handle_twitter_post()` calls `_close_browser()` in finally; RuntimeError raised if count == 0
  - `TestTwitterDeduplication` (~8 tests): `_load_processed_ids()` returns {} when file missing; loads valid JSON correctly; handles corrupt JSON without raising; `_save_processed_ids()` creates file if not exists; `_cleanup_old_ids()` removes entries older than 7 days; retains entries within 7 days; skips cleanup if last_cleanup within 24 hours
  - `TestTwitterTemplates` (~6 tests): All 5 twitter templates have `len(body) <= 280`; all have `format_type == "twitter_short"`; all 5 topic keys are covered; each template has ≥ 1 hashtag; `generate(platform="twitter", ...)` returns `GeneratedPost.platform == "twitter"` with char_count ≤ 280

- [X] T034 Run `uv run pytest tests/test_twitter.py -v` — verify all tests pass; fix any failures before proceeding (do not mark T034 complete until 0 failures)

- [X] T035 Run `uv run ruff check backend/watchers/twitter_watcher.py backend/actions/twitter_poster.py` — fix all reported violations (SIM102 nested if → combined, SIM105 try/except/pass → contextlib.suppress, etc.); run `uv run ruff check backend/orchestrator/action_executor.py backend/orchestrator/orchestrator.py backend/scheduler/post_generator.py backend/scheduler/schedule_manager.py` for modified files

- [X] T036 Run `uv run pytest` (full regression) — verify all 410+ existing tests still pass alongside new twitter tests; record final test count

- [X] T037 E2E DEV_MODE validation: (1) add `"AI and Automation [platform: twitter] - Quick Twitter tips"` as a new topic in `vault/Content_Strategy.md`; (2) run `uv run python -m backend.scheduler.content_scheduler --generate-now`; (3) verify `vault/Pending_Approval/TWITTER_POST_2026-02-21.md` created with `type: twitter_post`, `platform: twitter`, `character_count` ≤ 280; (4) copy file to `vault/Approved/` and set `status: approved`; (5) run `uv run python backend/actions/twitter_poster.py --once` (DEV_MODE=true); (6) verify file moved to `vault/Done/` with `status: done`, `dev_mode: true`

- [X] T038 Mark all 38 tasks [X] in `specs/005-twitter-x-integration/tasks.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — creates the two module files that all US phases need
- **US1 Session Setup (Phase 3)**: Depends on T003 (twitter_watcher.py scaffold)
- **US2 Notification Monitoring (Phase 4)**: Depends on all US1 tasks (T005–T010 must be complete — monitoring methods go into same file)
- **US3 Auto-Post (Phase 5)**: Depends on T004 (twitter_poster.py scaffold) — can start in parallel with US1/US2
- **US4 Content Scheduler (Phase 6)**: Depends on Phase 1 only — fully independent (modifies different files: post_generator.py, schedule_manager.py)
- **Polish (Phase 7)**: Depends on all US phases complete

### User Story Dependencies

- **US1 (P1)**: After T003 — builds TwitterWatcher session half
- **US2 (P2)**: After US1 complete — adds monitoring methods to same class in twitter_watcher.py
- **US3 (P3)**: After T004 — builds TwitterPoster (independent of US1/US2, different file)
- **US4 (P4)**: After Phase 1 only — modifies post_generator.py and schedule_manager.py

### Parallel Opportunities

- T003 and T004 [Phase 2]: Can run in parallel (different files)
- US3 (T018–T028) and US1+US2 (T005–T017): Can run in parallel (different files)
- US4 tasks T029, T030, T031: All marked [P] — can run in parallel (different parts of post_generator.py or different files)
- T035 (ruff) sub-checks: All four ruff commands can run in parallel

---

## Parallel Execution Example: Phases 3+5+6

```bash
# After T003 and T004 complete, launch three parallel workstreams:

# Workstream A: US1 + US2 (twitter_watcher.py)
Task: T005 → T006 → T007 → T008 → T009 → T010  (US1 sequential in same file)
Task: T011 → T012 → T013 → T014 → T015 → T016 → T017  (US2 sequential, after US1)

# Workstream B: US3 (twitter_poster.py + action_executor.py)
Task: T018 → T019 → T020 → T021 → T022 → T023 → T024 → T025 → T026 → T027 → T028

# Workstream C: US4 (post_generator.py + schedule_manager.py)
Task: T029, T030, T031 (all [P] — can run in parallel within this workstream)
```

---

## Implementation Strategy

### MVP First (US1 + US2: Watcher Only)

1. Complete Phase 1 (T001–T002) — setup
2. Complete T003 (watcher scaffold)
3. Complete US1 (T005–T010) — session setup works
4. Complete US2 (T011–T017) — monitoring works
5. **STOP and VALIDATE**: `--once` creates vault action files in DEV_MODE
6. US3 and US4 extend the system without breaking the watcher

### Incremental Delivery

1. T001–T004: Infrastructure + scaffolds
2. T005–T017: Full monitoring (watcher + orchestrator)
3. T018–T028: Full posting (poster + action executor)
4. T029–T031: Content scheduler generates Twitter drafts
5. T032–T038: Polish, tests, validation

### TDD Note

Tests (T033) are written after implementation in this project (post-implementation validation pattern matching Feature 004). T034 must pass before T035 (ruff) and T036 (regression).

---

## Notes

- [P] tasks operate on different files — no file conflicts
- Each phase checkpoint is independently verifiable via DEV_MODE
- Follow FacebookWatcher/FacebookPoster patterns exactly — minimize cognitive distance
- `update_frontmatter(file_path, dict)` takes a file path (not string content) — critical lesson from Feature 004 bug
- Twitter home page auto-focuses tweet textarea — no intermediate "click composer trigger" needed (simpler than Facebook)
- 280-char limit: poster rejects (never truncates); generator has emergency truncation as safety net only
- All async test methods require `@pytest.mark.asyncio` decorator
- `create_action_file()` is async — tests must `await` it
- `_classify_priority()` is a module-level function — import directly for tests, not via `watcher._classify_priority`
