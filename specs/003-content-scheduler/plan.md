# Implementation Plan: Smart Content Scheduler

**Branch**: `003-content-scheduler` | **Date**: 2026-02-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/003-content-scheduler/spec.md`

---

## Summary

Build a template-based LinkedIn content scheduling system that generates daily post drafts from user-defined topics, integrates with the existing HITL approval workflow, and completes the LinkedIn posting loop via the ActionExecutor. All AI generation is template-based (no live LLM calls), ensuring deterministic, fast, testable output. The scheduler hooks into the orchestrator startup and respects DEV_MODE, rate limits, and existing vault file conventions.

---

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: `pyyaml>=6.0`, `python-dotenv>=1.0`, `zoneinfo` (stdlib 3.9+), `playwright>=1.40` (LinkedIn posting only — existing dep)
**Storage**: Local file system only — `vault/Logs/posted_topics.json`, `vault/Logs/posting_schedule.json`, `vault/Pending_Approval/LINKEDIN_POST_*.md`
**Testing**: pytest + pytest-asyncio (existing project config); `asyncio_mode = "auto"`
**Target Platform**: Windows 11 / any OS with Python 3.13+
**Project Type**: Backend service module extending existing backend/ package
**Performance Goals**: Draft generation < 5 seconds; `--status` < 1 second
**Constraints**: No external API calls during generation; must not break orchestrator startup on failure; character limit ≤ 1300
**Scale/Scope**: Single user, single LinkedIn account, 1 draft/day max

---

## Constitution Check

*GATE: Must pass before implementation. Re-check after integration.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Local-First & Privacy | ✅ PASS | All data in vault; no credentials used; no external calls for generation |
| II. Separation of Concerns | ✅ PASS | Scheduler = PERCEPTION (creates Pending_Approval files); ActionExecutor = ACTION (executes after approval) |
| III. Agent Skills as First-Class | ✅ PASS | `skills/content-scheduler/SKILL.md` required — must be created |
| IV. HITL Safety | ✅ PASS | Posts go to `vault/Pending_Approval/` first; human must move to `vault/Approved/`; never auto-approved |
| V. DEV_MODE Safety | ✅ PASS | `LinkedInPoster.publish_post()` already guards with `if self.dev_mode`; `ActionExecutor._handle_dev_mode()` handles all types |
| VI. Rate Limits | ✅ PASS | One draft/day idempotency guard; LinkedIn MAX_POSTS_PER_RUN=5 already in poster |
| VII. Comprehensive Logging | ✅ PASS | All scheduler actions logged to `vault/Logs/`; ActionExecutor already logs linkedin_post events |
| VIII. Error Handling | ✅ PASS | Scheduler failure during orchestrator startup logs WARNING, does not crash; parse errors reset to defaults |

**Gate result**: ✅ ALL PASS — no violations.

---

## Project Structure

### Documentation (this feature)

```text
specs/003-content-scheduler/
├── plan.md              # This file
├── research.md          # Phase 0 — integration findings
├── data-model.md        # Phase 1 — entity schemas
├── quickstart.md        # Phase 1 — usage guide
├── contracts/
│   └── scheduler-interfaces.md   # Phase 1 — API contracts
├── checklists/
│   └── requirements.md           # Spec validation (from /sp.specify)
└── tasks.md             # Phase 2 output (/sp.tasks — NOT created here)
```

### Source Code (repository root)

```text
backend/
└── scheduler/
    ├── __init__.py                 # Package init (empty)
    ├── content_scheduler.py        # Main class + CLI entry point
    ├── post_generator.py           # Template engine — 25+ templates
    └── schedule_manager.py         # Schedule state R/W + rotation logic

skills/
└── content-scheduler/
    └── SKILL.md                    # Required by Constitution Principle III

vault/
└── Content_Strategy.md             # User config template (seed file)

config/
└── .env.example                    # Add 4 new CONTENT_* vars

tests/
└── test_content_scheduler.py       # Unit tests for scheduler
```

**Modified files** (existing):

```text
backend/orchestrator/orchestrator.py     # Add _check_content_schedule() + call in run()
backend/orchestrator/action_executor.py  # Replace _handle_linkedin_post() placeholder
```

**Structure Decision**: Single backend module (`backend/scheduler/`) following the existing `backend/watchers/` and `backend/mcp_servers/` package pattern. No new top-level directories. Tests go in existing `tests/` directory.

---

## Architecture Decisions

### AD-1: Template-Based Generation (Not LLM API)

**Decision**: Use in-code Python string templates with named placeholders, not a live LLM API call.

**Rationale**: (1) Fast and deterministic — no API latency or rate limits; (2) Works without API keys; (3) Fully testable with fixed outputs; (4) 25+ hand-crafted templates provide sufficient variety for Gold Tier; (5) Consistent with spec assumption.

**Trade-off rejected**: Live LLM API calls would produce more varied content but add API key dependencies, latency (~2-5s), cost, and non-deterministic test behavior. Can be upgraded in Platinum Tier.

---

### AD-2: `type:` Not `action_type:` in Frontmatter

**Decision**: Generated draft frontmatter uses `type: linkedin_post`, NOT `action_type: linkedin_post`.

**Rationale**: `action_executor.py:81` reads `fm.get("type", "")` and `linkedin_poster.py:262` checks `frontmatter.get("type") == "linkedin_post"`. Using `action_type` would silently break routing. This is a spec correction — the spec incorrectly used `action_type`.

---

### AD-3: Synchronous Scheduler, async-wrapped in Orchestrator

**Decision**: `ContentScheduler.run_if_due()` is synchronous (file I/O only). The orchestrator calls it via `await asyncio.to_thread(scheduler.run_if_due)`.

**Rationale**: File I/O doesn't need async — it's fast and single-operation. Using `asyncio.to_thread()` follows the existing pattern in `action_executor.py:137` (`await asyncio.to_thread(client.authenticate)`), avoids blocking the event loop, and keeps the scheduler easily unit-testable without asyncio.

---

### AD-4: Atomic Write for State Files

**Decision**: Write state to a `.tmp` file then `Path.rename()` to the final path.

**Rationale**: Prevents corrupt state files from partial writes (power loss, process kill). Python's `os.rename()` is atomic on NTFS (Windows). No file locking library needed.

---

### AD-5: Rotation Logic

**Decision**: Round-robin rotation by index. Next index = `(last_index + 1) % num_topics`. If only 1 topic, always return index 0. Never returns the same index as `last_topic_index` (when `num_topics > 1`).

**Rationale**: Simple, predictable, testable. Satisfies FR-003 (no consecutive repeats).

---

### AD-6: Action Executor LinkedIn Handler

**Decision**: Replace `NotImplementedError` placeholder in `_handle_linkedin_post()` with a lazy-imported `LinkedInPoster` instance that calls `process_approved_posts()`.

**Key detail**: `LinkedInPoster.find_approved_posts()` already scans `vault/Approved/` — it will find the file being processed. However, the ActionExecutor also tries to move the file. To avoid double-move, the handler should NOT call `self._move_to_done()` — instead, `LinkedInPoster._move_to_done()` handles the file lifecycle. The ActionExecutor handler should return after `await poster.process_approved_posts()` without the standard `self._move_to_done(file_path)` call.

**Trade-off**: Slight inversion of control (poster owns the file lifecycle, not executor). Acceptable because the poster's lifecycle logic is already complete and tested.

---

## Implementation Steps

### Phase A — New Module: `backend/scheduler/`

**A1. `backend/scheduler/__init__.py`**
- Empty file to make it a package

**A2. `backend/scheduler/schedule_manager.py`**
- `ScheduleState` dataclass
- `PostingHistory` + `PostingHistoryEntry` dataclasses
- `ScheduleManager` class:
  - `load_state()` / `save_state()` with atomic write + JSON parse error reset
  - `load_history()` / `save_history()` with atomic write
  - `is_post_due()` — checks last_run_date, skip_weekends, posts_today
  - `get_next_topic_index()` — round-robin, no consecutive repeat
  - `draft_exists_today()` — checks Pending_Approval and Approved

**A3. `backend/scheduler/post_generator.py`**
- `PostTemplate`, `GeneratedPost`, `PostContext`, `ValidationResult` dataclasses
- `TEMPLATES: dict[str, list[PostTemplate]]` — 25+ templates (5 per topic × 5 formats)
- `PostGenerator` class:
  - `generate()` — random template selection, fill placeholders, validate, retry (max 3)
  - `get_templates_for_topic()` — filter TEMPLATES by topic_key
  - `validate_post()` — character count, hashtag count, question check
- Topic keys: `ai_automation`, `backend_development`, `hackathon_journey`, `cloud_devops`, `career_tips`
- Format types per topic: `tip`, `insight`, `question`, `story`, `announcement`

**A4. `backend/scheduler/content_scheduler.py`**
- `Topic`, `ContentStrategy` dataclasses
- `ContentStrategyError`, `TemplateGenerationError` exceptions
- `RunResult`, `PreviewResult`, `StatusResult` dataclasses
- `ContentScheduler` class:
  - `_load_strategy()` — parse `vault/Content_Strategy.md` (frontmatter + body sections)
  - `_load_context()` — read Company_Handbook.md + Business_Goals.md if available
  - `run_if_due()` — full pipeline: load strategy → check schedule → select topic → generate → save draft
  - `generate_now()` — same as run_if_due but skips idempotency check
  - `preview()` — generate and return without saving
  - `status()` — read state and format StatusResult
  - `_save_draft()` — write LINKEDIN_POST_{date}.md with correct frontmatter + body
- CLI entry point with argparse: `--generate-now`, `--preview`, `--status`, `--vault-path`, `--dry-run`

---

### Phase B — Vault Template

**B1. `vault/Content_Strategy.md`**
- Pre-filled with Taha's topics, content rules, and exclusions
- Matches the exact format expected by `_load_strategy()` parser

---

### Phase C — Skill Definition

**C1. `skills/content-scheduler/SKILL.md`**
- Metadata: name, version, triggers, dependencies, permissions, sensitivity
- Triggers: "generate post", "check content schedule", "preview post", "post to LinkedIn"
- Layer: PERCEPTION (generates Pending_Approval files)
- Permissions: vault read/write only (no external API for generation)
- Dependencies: `skills/linkedin-poster/` (for P5 execution)
- HITL: Required (posts always go through Pending_Approval → Approved)

---

### Phase D — Orchestrator Integration

**D1. `backend/orchestrator/orchestrator.py`**

Add `_check_content_schedule()` async method:
```python
async def _check_content_schedule(self) -> None:
    """One-shot content schedule check on startup."""
    try:
        from backend.scheduler.content_scheduler import ContentScheduler, ContentStrategyError
        scheduler = ContentScheduler(
            vault_path=self.vault_path,
            dev_mode=self.config.dev_mode,
            dry_run=self.config.dry_run,
        )
        result = await asyncio.to_thread(scheduler.run_if_due)
        if result.status == "generated":
            logger.info("Content scheduler: draft generated → %s", result.draft_path)
        else:
            logger.debug("Content scheduler: %s (%s)", result.status, result.reason)
    except ContentStrategyError as exc:
        logger.warning("Content scheduler skipped: %s", exc)
    except Exception:
        logger.warning("Content scheduler failed on startup", exc_info=True)
```

Call it in `run()` after `_log_event("orchestrator_start")`, before `_start_watchers()`.

---

### Phase E — Action Executor Integration

**E1. `backend/orchestrator/action_executor.py`**

Replace `_handle_linkedin_post()` with:
```python
async def _handle_linkedin_post(
    self, file_path: Path, fm: dict[str, Any], _cid: str
) -> None:
    """Post approved LinkedIn content via LinkedInPoster."""
    from backend.actions.linkedin_poster import LinkedInPoster

    poster = LinkedInPoster(
        vault_path=str(self.vault_path),
        session_path=os.getenv("LINKEDIN_SESSION_PATH", "config/linkedin_session"),
        headless=os.getenv("LINKEDIN_HEADLESS", "true").lower() == "true",
        dry_run=self.config.dry_run,
        dev_mode=self.config.dev_mode,
    )
    try:
        count = await poster.process_approved_posts()
        if count == 0:
            raise RuntimeError(
                f"LinkedInPoster processed 0 posts (file may not match type=linkedin_post)"
            )
    finally:
        await poster._close_browser()
```

**Important**: Remove `self._move_to_done(file_path)` from the outer `process_file()` for this handler — `LinkedInPoster._move_to_done()` already handles file lifecycle. This requires a small refactor: have `_handle_linkedin_post` return a special sentinel or the executor checks if the file still exists before calling `self._move_to_done()`.

---

### Phase F — Config Updates

**F1. `config/.env.example`**
Add section after LinkedIn Integration:
```
# ===================
# CONTENT SCHEDULER
# ===================
CONTENT_POST_FREQUENCY=daily
CONTENT_POST_TIME=09:00
CONTENT_TIMEZONE=Asia/Karachi
CONTENT_SKIP_WEEKENDS=false
```

---

### Phase G — Tests

**G1. `tests/test_content_scheduler.py`**

Test classes:
- `TestScheduleManager` — `is_post_due()`, `get_next_topic_index()`, `draft_exists_today()`, state save/load, atomic write
- `TestPostGenerator` — template coverage (25+ templates exist), character limit validation, format variety, retry logic
- `TestContentScheduler` — `run_if_due()` (due / not due / already exists / missing strategy), `preview()`, `status()`, `generate_now()`
- `TestTopicRotation` — 10-run sequence with no consecutive repeats, wrap-around
- `TestDraftFormat` — frontmatter fields presence, character count field accuracy

Minimum: 20 test cases covering all acceptance scenarios from spec.

---

## Non-Functional Requirements

| NFR | Target | Approach |
|-----|--------|----------|
| Draft generation latency | < 5 seconds | Template-based (no network); file I/O only |
| Status command | < 1 second | Read 2 JSON files + format |
| Orchestrator startup overhead | < 2 seconds | `asyncio.to_thread()` + synchronous file reads |
| Character limit | 100% compliance | Validate + retry (max 3 attempts) in `PostGenerator.generate()` |
| Test coverage | ≥ 70% for `backend/scheduler/` | pytest-cov |

---

## Risk Analysis

| Risk | Likelihood | Blast Radius | Mitigation |
|------|-----------|--------------|------------|
| ActionExecutor double-move bug (executor + poster both try to move file) | Medium | File gets moved to Done before posting | `_handle_linkedin_post` must NOT call `self._move_to_done()` — let poster own lifecycle |
| `Content_Strategy.md` YAML parse error on startup | Low | Orchestrator logs warning, continues | ContentStrategyError caught in `_check_content_schedule()` |
| All 5 templates for a topic exceed 1300 chars | Very Low | Draft not generated | Retry loop + truncation fallback; all templates validated in tests |
| `posting_schedule.json` race condition | Very Low (single-user) | Missed rotation | Atomic write prevents corruption; reset on parse error |

---

## Complexity Tracking

No constitution violations — no complexity justification needed.

---

## Follow-Up

- 📋 Architectural decision detected: **Template-based vs LLM-API post generation** — Document rationale for keeping template-based at Gold Tier? Run `/sp.adr content-generation-approach`
- `/sp.tasks` to break this plan into implementable task checklist
- LinkedIn Playwright session must be pre-authenticated for P5 production use (existing setup flow via `linkedin_poster.py --once`)
