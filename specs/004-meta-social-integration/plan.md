# Implementation Plan: Meta Social Integration (Facebook & Instagram)

**Branch**: `004-meta-social-integration` | **Date**: 2026-02-21 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-meta-social-integration/spec.md`

---

## Summary

Extend the Personal AI Employee with Facebook and Instagram perception (watchers) and action (posters) layers, following the established LinkedIn pattern. Both platforms share a single Meta browser session (`config/meta_session/`). New watchers capture notifications/messages as vault files; new posters publish human-approved drafts. The Content Scheduler is extended to generate Facebook and Instagram drafts alongside LinkedIn posts. All new components integrate into the existing orchestrator and action executor via the established factory and handler patterns.

---

## Technical Context

**Language/Version**: Python 3.13+ (per constitution)
**Package Manager**: uv (per constitution; NOT pip)
**Primary Dependencies**:
- `playwright` (already installed — used by LinkedIn watcher + poster)
- `python-frontmatter` / `backend.utils.frontmatter` (existing utility)
- `pytest`, `pytest-asyncio` (existing test infrastructure)
- `tzdata>=2024.1` (added in feature 003)

**New Dependencies**: None — all required packages already present

**Storage**:
- `config/meta_session/` — Playwright persistent browser context (both platforms)
- `vault/Logs/processed_facebook.json` — dedup store
- `vault/Logs/processed_instagram.json` — dedup store
- `vault/Needs_Action/*.md` — notification vault files
- `vault/Approved/*.md`, `vault/Done/*.md`, `vault/Rejected/*.md` — post lifecycle

**Testing**: pytest + pytest-asyncio (existing); `unittest.mock` for Playwright mocking
**Target Platform**: Windows 11 (primary development) + Linux (CI-compatible)
**Performance Goals**: Watcher cycle completes in < 30s (same timeout as constitution default)
**Constraints**: Max 5 posts/day/platform (constitution rate limit); polling intervals ≥ 60s (Instagram), ≥ 120s (Facebook)
**Scale/Scope**: Single-user personal system; 1-2 Facebook/Instagram accounts

---

## Constitution Check

*GATE: Must pass before implementation begins.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Local-First & Privacy | ✅ PASS | All scraping is local; no data sent externally; session stored in `config/` (gitignored) |
| II. Separation of Concerns | ✅ PASS | Watchers only write to `Needs_Action/`; posters only execute from `Approved/`; no cross-layer calls |
| III. Agent Skills | ✅ PASS | New `skills/social-media-manager/SKILL.md` will be created |
| IV. HITL Safety | ✅ PASS | Social media posts are in the "NEVER auto-approve" list; full vault workflow enforced |
| V. DEV_MODE Safety | ✅ PASS | All new components accept `dev_mode` and `dry_run` flags; default `DEV_MODE=true` |
| VI. Rate Limits | ✅ PASS | Max 5 posts/day/platform; polling intervals configurable with safe defaults |
| VII. Logging | ✅ PASS | All actions logged to `vault/Logs/actions/`; errors to `vault/Logs/errors/` |
| VIII. Error Handling | ✅ PASS | Session expiry detected gracefully; scraping errors skipped with structured log |

**Complexity Check**: No violations to justify. This is a pure extension of the existing architecture.

---

## Project Structure

### Documentation (this feature)

```text
specs/004-meta-social-integration/
├── spec.md              ✓ (created by /sp.specify)
├── research.md          ✓ (created by /sp.plan — Phase 0)
├── data-model.md        ✓ (created by /sp.plan — Phase 1)
├── quickstart.md        ✓ (created by /sp.plan — Phase 1)
├── contracts/
│   └── vault-file-contracts.md  ✓ (created by /sp.plan — Phase 1)
├── checklists/
│   └── requirements.md  ✓ (created by /sp.specify)
└── tasks.md             (created by /sp.tasks — NOT by /sp.plan)
```

### Source Code (repository root)

```text
backend/
├── watchers/
│   ├── base_watcher.py            (existing — no change)
│   ├── linkedin_watcher.py        (existing — no change)
│   ├── facebook_watcher.py        (NEW — US-2 Facebook Monitoring)
│   └── instagram_watcher.py       (NEW — US-4 Instagram Monitoring)
│
├── actions/
│   ├── linkedin_poster.py         (existing — no change)
│   ├── facebook_poster.py         (NEW — US-3 Facebook Auto-Post)
│   └── instagram_poster.py        (NEW — US-5 Instagram Auto-Post)
│
├── scheduler/
│   ├── content_scheduler.py       (existing — no change)
│   ├── post_generator.py          (MODIFIED — platform routing)
│   └── schedule_manager.py        (existing — no change)
│
└── orchestrator/
    ├── orchestrator.py            (MODIFIED — add FB/IG watcher factories)
    └── action_executor.py         (MODIFIED — add FB/IG post handlers)

skills/
└── social-media-manager/
    └── SKILL.md                   (NEW — US-1 through US-5 skill definition)

config/
├── .env.example                   (MODIFIED — add FB/IG env vars)
└── meta_session/                  (created at runtime by --setup)

vault/
└── Content_Strategy.md            (MODIFIED — platform field documented)

tests/
└── test_meta_social.py            (NEW — ~50 tests across 7 test classes)
```

**Structure Decision**: Single-project layout. New files follow the exact same module patterns as their LinkedIn counterparts. No new top-level directories needed.

---

## Phase 0: Research

**Status**: ✅ Complete — see [research.md](research.md)

Key decisions from research:

1. **Shared Meta session** at `config/meta_session/` — single Playwright context covers both facebook.com and instagram.com cookies
2. **Playwright broad selectors** — same resilient strategy as LinkedIn watcher; URL-based session detection first
3. **ActionExecutor HANDLERS extension** — add `facebook_post` and `instagram_post` to existing dispatch dict
4. **ContentScheduler**: optional `platform` field per topic; default `linkedin` (backward-compatible)
5. **Dedup stores**: `processed_facebook.json` and `processed_instagram.json` — independent per watcher
6. **Image attachments**: optional `image_path` frontmatter; validate before publish or reject

---

## Phase 1: Design

**Status**: ✅ Complete

### Data Model

See [data-model.md](data-model.md) for full entity definitions.

**Key entities**:
| Entity | File Pattern | Type Field |
|--------|-------------|-----------|
| FacebookNotification | `Needs_Action/FACEBOOK_*.md` | `type: facebook` |
| InstagramNotification | `Needs_Action/INSTAGRAM_*.md` | `type: instagram` |
| FacebookPostDraft | `Approved/FACEBOOK_POST_*.md` | `type: facebook_post` |
| InstagramPostDraft | `Approved/INSTAGRAM_POST_*.md` | `type: instagram_post` |

### Contracts

See [contracts/vault-file-contracts.md](contracts/vault-file-contracts.md) for:
- Vault file frontmatter schemas (Contracts 1–5)
- Python module interfaces (Contracts 6–9)
- ActionExecutor HANDLERS extension (Contract 10)
- PostGenerator platform extension (Contract 11)

### Quickstart Scenarios

See [quickstart.md](quickstart.md) for 10 end-to-end integration scenarios.

---

## Implementation Strategy

### Module Implementations

#### `backend/watchers/facebook_watcher.py` (new)

Clone of `linkedin_watcher.py` adapted for Facebook:

```python
class FacebookWatcher(BaseWatcher):
    """
    Key differences from LinkedInWatcher:
    - session_path defaults to "config/meta_session" (shared)
    - Monitors facebook.com/notifications/ and facebook.com/messages/
    - URL session detection: "/login?next=" or "www.facebook.com/login/"
    - DEV_MODE: return [{"item_type": "notification", "sender": "[DEV_MODE]", ...}]
    - Dedup store: vault/Logs/processed_facebook.json
    - Vault file prefix: "FACEBOOK_"
    """
```

Session detection pattern (Facebook-specific):
```python
# URL-based (most reliable)
if "/login" in current_url or "checkpoint" in current_url:
    return "login_required"
# DOM-based
if await self._page.query_selector('input[name="email"]'):
    return "login_required"
```

#### `backend/watchers/instagram_watcher.py` (new)

Clone adapted for Instagram:
```python
class InstagramWatcher(BaseWatcher):
    """
    - session_path defaults to "config/meta_session" (shared)
    - Monitors instagram.com/direct/inbox/ and instagram.com/activity/
    - URL session detection: "/accounts/login/" in URL
    - DEV_MODE: return synthetic item
    - Dedup store: vault/Logs/processed_instagram.json
    - Vault file prefix: "INSTAGRAM_"
    """
```

#### `backend/actions/facebook_poster.py` (new)

Clone of `linkedin_poster.py` adapted for Facebook:
```python
class FacebookPoster:
    """
    Key differences:
    - Reads type: "facebook_post" files from vault/Approved/
    - Validates character_count ≤ 63,206
    - Navigates to facebook.com/composer/... or uses "What's on your mind?" flow
    - Optional image upload via image_path frontmatter
    - DEV_MODE: log "[DEV_MODE] Would post to Facebook: ..." and move to Done
    """
```

#### `backend/actions/instagram_poster.py` (new)

```python
class InstagramPoster:
    """
    Key differences:
    - Reads type: "instagram_post" files from vault/Approved/
    - Validates character_count ≤ 2,200
    - Navigates to instagram.com, uses "Create post" flow
    - Image is optional (captions-only posts supported)
    - DEV_MODE: log and move to Done
    """
```

#### `backend/orchestrator/orchestrator.py` (modified)

Add two factory functions to `_build_watcher_configs()`:

```python
def _facebook_factory():
    from backend.watchers.facebook_watcher import FacebookWatcher
    return FacebookWatcher(
        vault_path=str(self.vault_path),
        session_path=os.getenv("FACEBOOK_SESSION_PATH", "config/meta_session"),
        check_interval=int(os.getenv("FACEBOOK_CHECK_INTERVAL", "120")),
        keywords=_parse_keywords(os.getenv("FACEBOOK_KEYWORDS", "")),
        headless=os.getenv("FACEBOOK_HEADLESS", "true").lower() == "true",
        dry_run=self.config.dry_run,
        dev_mode=self.config.dev_mode,
    )

def _instagram_factory():
    from backend.watchers.instagram_watcher import InstagramWatcher
    return InstagramWatcher(
        vault_path=str(self.vault_path),
        session_path=os.getenv("INSTAGRAM_SESSION_PATH", "config/meta_session"),
        check_interval=int(os.getenv("INSTAGRAM_CHECK_INTERVAL", "60")),
        keywords=_parse_keywords(os.getenv("INSTAGRAM_KEYWORDS", "")),
        headless=os.getenv("INSTAGRAM_HEADLESS", "true").lower() == "true",
        dry_run=self.config.dry_run,
        dev_mode=self.config.dev_mode,
    )
```

#### `backend/orchestrator/action_executor.py` (modified)

```python
HANDLERS: dict[str, str] = {
    "email_send": "_handle_email_send",
    "email_reply": "_handle_email_reply",
    "linkedin_post": "_handle_linkedin_post",
    "facebook_post": "_handle_facebook_post",   # NEW
    "instagram_post": "_handle_instagram_post",  # NEW
}

async def _handle_facebook_post(self, file_path, _fm, _cid):
    from backend.actions.facebook_poster import FacebookPoster
    poster = FacebookPoster(
        vault_path=str(self.vault_path),
        session_path=os.getenv("FACEBOOK_SESSION_PATH", "config/meta_session"),
        headless=os.getenv("FACEBOOK_HEADLESS", "true").lower() == "true",
        dry_run=self.config.dry_run,
        dev_mode=self.config.dev_mode,
    )
    try:
        count = await poster.process_approved_posts()
    finally:
        await poster._close_browser()
    if count == 0:
        raise RuntimeError(f"FacebookPoster processed 0 posts for {file_path.name}")

# Same pattern for _handle_instagram_post
```

#### `backend/scheduler/post_generator.py` (modified)

```python
def generate(self, topic: dict, ...) -> GeneratedPost:
    platform = topic.get("platform", "linkedin")
    post_type = f"{platform}_post"   # "linkedin_post", "facebook_post", "instagram_post"
    # ... existing generation logic ...
    frontmatter["type"] = post_type
    frontmatter["platform"] = platform
```

#### `config/.env.example` (modified)

Add new section:
```ini
# ===================
# FACEBOOK INTEGRATION
# ===================
FACEBOOK_CHECK_INTERVAL=120
FACEBOOK_KEYWORDS=urgent,invoice,meeting,proposal,partnership
FACEBOOK_SESSION_PATH=config/meta_session
FACEBOOK_HEADLESS=false

# ===================
# INSTAGRAM INTEGRATION
# ===================
INSTAGRAM_CHECK_INTERVAL=60
INSTAGRAM_KEYWORDS=urgent,collab,invoice,project
INSTAGRAM_SESSION_PATH=config/meta_session
INSTAGRAM_HEADLESS=false
```

#### `skills/social-media-manager/SKILL.md` (new)

Covers all 4 Meta operations: monitor FB, monitor IG, post to FB, post to IG.

---

## Testing Strategy

**Test file**: `tests/test_meta_social.py`

| Test Class | Count | Coverage |
|-----------|-------|---------|
| `TestMetaSessionSetup` | 6 | Session detection, expiry, DEV_MODE |
| `TestFacebookWatcher` | 10 | Notification capture, dedup, keyword filtering, DEV_MODE |
| `TestInstagramWatcher` | 10 | Same as Facebook watcher |
| `TestFacebookPoster` | 8 | Publishing, validation, image path, lifecycle |
| `TestInstagramPoster` | 6 | Publishing, character limit, lifecycle |
| `TestContentSchedulerPlatform` | 6 | Platform routing in PostGenerator |
| `TestActionExecutorMeta` | 4 | facebook_post and instagram_post dispatch |
| **Total** | **~50** | Full coverage of all US-1 through US-5 acceptance criteria |

**All tests use mocks** — no real browser launched during test runs.

**Mocking strategy**:
- `async_playwright` → `AsyncMock` (same as existing action_executor tests)
- Vault files written to `tmp_path` (pytest fixture)
- `LinkedInPoster` pattern applied to `FacebookPoster` and `InstagramPoster`

---

## Environment Variables Reference

| Variable | Default | Description |
|---------|---------|-------------|
| `FACEBOOK_CHECK_INTERVAL` | `120` | Polling interval (seconds) |
| `FACEBOOK_KEYWORDS` | (empty=all) | Comma-separated trigger keywords |
| `FACEBOOK_SESSION_PATH` | `config/meta_session` | Playwright session directory |
| `FACEBOOK_HEADLESS` | `true` | `false` for --setup |
| `INSTAGRAM_CHECK_INTERVAL` | `60` | Polling interval (seconds) |
| `INSTAGRAM_KEYWORDS` | (empty=all) | Comma-separated trigger keywords |
| `INSTAGRAM_SESSION_PATH` | `config/meta_session` | Same as Facebook (shared) |
| `INSTAGRAM_HEADLESS` | `true` | `false` for --setup |

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Facebook/Instagram change their DOM structure | High (6-month horizon) | Broad selector strategy + debug screenshots on failure; watchers degrade gracefully (return []) |
| Meta detects automation and triggers CAPTCHA | Medium | Headless mode only after session established; conservative polling intervals; detection logged as `captcha` state |
| Shared session conflicts (FB cookie clobbers IG) | Low | Playwright persistent context stores cookies per-domain; no cross-domain cookie conflicts possible |

---

## ADR Candidates

📋 **Architectural decision detected**: Shared Meta session directory (`config/meta_session/`) for both Facebook and Instagram watchers and posters — Document the rationale for single vs. dual session directories? Run `/sp.adr shared-meta-session`

📋 **Architectural decision detected**: Playwright browser automation for Facebook/Instagram (vs. official Meta Graph API) — Document the API-vs-automation tradeoff? Run `/sp.adr meta-playwright-vs-api`
