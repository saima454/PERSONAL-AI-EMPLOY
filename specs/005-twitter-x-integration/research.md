# Research: Twitter (X) Integration

**Feature**: 005-twitter-x-integration
**Phase**: 0 — Pre-implementation research
**Date**: 2026-02-21

---

## Decision 1: Twitter/X URL Namespace

**Decision**: Use `x.com` as the primary domain for all URLs; treat `twitter.com` as a redirect alias.

**Rationale**: Twitter was rebranded to X in 2023. `twitter.com` now redirects to `x.com`. All Playwright navigation should target `x.com` to avoid redirect overhead and ensure consistent URL-based session checks.

**Impact on implementation**:
- Login detection URL check: `"/i/flow/login"` in `page.url` (works on both domains)
- All `goto()` calls use `https://x.com/...`
- Session state checks look for `x.com/` in current URL

**Alternatives considered**:
- `twitter.com` — still works but incurs redirect; session state URL checks must handle both domains

---

## Decision 2: Playwright Persistent Context (Session Pattern)

**Decision**: Use `chromium.launch_persistent_context(user_data_dir=TWITTER_SESSION_PATH, headless=TWITTER_HEADLESS)` — identical pattern to FacebookWatcher and InstagramWatcher.

**Rationale**: This is the established project pattern (Feature 004). Persistent context stores cookies, localStorage, and IndexedDB in a local directory, allowing session reuse across process restarts. No credential storage required.

**Key parameters**:
```python
args=["--disable-blink-features=AutomationControlled"]  # Reduces bot detection
user_data_dir=str(session_path)                          # config/twitter_session/
headless=headless                                        # from TWITTER_HEADLESS env
```

**Session path**: `config/twitter_session/` (separate from `config/meta_session/`)

**Alternatives considered**:
- Shared session with Meta — rejected because X and Meta are separate auth domains
- API token-based (OAuth2/OAuth1) — rejected per spec (session-based only, no developer account required)

---

## Decision 3: Twitter/X DOM Selectors Strategy

**Decision**: Use `data-testid` attribute selectors as the primary probe strategy (Twitter's React UI exposes these consistently), with URL-based checks as fast-path fallbacks.

**Rationale**: Twitter/X's React front-end uses `data-testid` attributes that are more stable than class names. This is the same approach used by well-known automation tooling (Playwright Test's Twitter examples, community Playwright scripts).

### 3a: Login / Session State Detection

| Check | Method |
|-------|--------|
| Not logged in (URL) | `"/i/flow/login"` in `page.url` |
| Not logged in (URL) | `"/login"` in `page.url` |
| CAPTCHA / suspension | `"/account/suspended"` or `"/i/flow/consent"` in `page.url` |
| Logged in (fast check) | `[data-testid="AppTabBar_Home_Link"]` present |
| Logged in (fallback) | `[data-testid="primaryColumn"]` present |
| Logged in (broad) | `[data-testid="SideNav_NewTweet_Button"]` present |

**Detection sequence** (mirrors FacebookWatcher pattern):
1. URL check for `/i/flow/login` or `/login` → `"login_required"`
2. URL check for `/account/suspended` or `/i/flow/consent` → `"captcha"`
3. DOM check for `[data-testid="AppTabBar_Home_Link"]` → `"ready"`
4. DOM broad check (element count) → `"ready"` if > 20
5. Default → `"unknown"`

### 3b: Tweet Composer Selectors

**Home page composer** (preferred — navigate to `https://x.com/home`):

| Action | Selector |
|--------|---------|
| Textarea (auto-focused) | `div[data-testid="tweetTextarea_0"]` |
| Textarea (fallback) | `div[role="textbox"][aria-label*="tweet" i]` |
| Textarea (broad) | `div[contenteditable="true"]` |
| Post button | `button[data-testid="tweetButtonInline"]` |
| Post button (fallback) | `button[data-testid="tweetButton"]` |
| Post button (broad) | `div[data-testid="tweetButtonInline"]` |

**Compose flow**: Navigate to home → wait for load → click textarea → type text → click Post button.
Note: Twitter auto-focuses the textarea on the home page; no intermediate "click composer trigger" step needed unlike Facebook.

### 3c: Notifications Page Selectors

**URL**: `https://x.com/notifications`

| Action | Selector | Priority |
|--------|---------|---------|
| Individual notification | `article[data-testid="notification"]` | Primary |
| Individual notification (fallback) | `[data-testid="notificationItem"]` | Secondary |
| Individual notification (broad) | `article[data-testid="tweet"]` | Tertiary |
| Notification container | `[data-testid="cellInnerDiv"]` | Broad fallback |
| Actor/user name | `[data-testid="User-Name"] span` | Content extraction |
| Notification text | `[data-testid="tweetText"]` or `div[lang]` | Content extraction |
| Timestamp | `time[datetime]` | Content extraction |

**Research note**: Web research confirms `article[data-testid="notification"]` is the primary selector for notification items on `x.com/notifications`. The broad `article[data-testid="tweet"]` is a fallback in case Twitter renames the test ID.

**Scan limit**: MAX_NOTIFICATIONS = 20 (first 20 items from query result, matching Facebook pattern)

### 3d: DM/Messages Selectors

**URL**: `https://x.com/messages`

| Action | Selector | Priority |
|--------|---------|---------|
| Conversation list item | `[data-testid="conversationItem"]` | Primary |
| Conversation list item (fallback) | `[data-testid="DMConversationItem"]` | Secondary |
| Conversation list item (broad) | `[data-testid="conversation"]` | Tertiary |
| Sender name in DM | `[data-testid="DMConversationEntry-Name"]` | Content extraction |
| Message preview | `[data-testid="messageContent"]` or `span[dir="ltr"]` | Content extraction |
| Timestamp | `time[datetime]` | Content extraction |

**Scan limit**: MAX_MESSAGES = 15 (matching Facebook pattern)

---

## Decision 4: DEV_MODE Behavior

**Decision**: Return a single synthetic item dict from `check_for_updates()` when `dev_mode=True`, identical to FacebookWatcher/InstagramWatcher pattern. No browser launched.

**Rationale**: Consistency with existing watcher pattern; DEV_MODE is the default and must work without credentials. Poster DEV_MODE moves file to `vault/Done/` with `dev_mode: true` flag without opening browser.

```python
# Watcher DEV_MODE return
return [{
    "item_type": "notification",
    "sender": "[DEV_MODE]",
    "preview": "[DEV_MODE] Synthetic Twitter mention for testing",
    "time": "just now",
    "priority": "low",
    "matched_keyword": "dev",
    "dedup_key": f"[DEV_MODE]|synthetic|{now_iso()}",
    "needs_reply": False,
}]
```

---

## Decision 5: 280-Character Limit Enforcement

**Decision**: Enforce 280-char limit in TWO places:
1. **Post Generator** (`post_generator.py`): Twitter templates authored to ≤280 chars. Unlike Instagram (which truncates), Twitter content that exceeds must fail at template design time — templates are authored short by construction.
2. **Twitter Poster** (`twitter_poster.py`): Hard validation before any browser interaction. If `len(body) > 280`, move to `vault/Rejected/` with `rejection_reason: exceeds_character_limit`. Never truncate silently.

**Rationale**: Silent truncation on Twitter would change the meaning of approved content. The user approved specific content — truncating it would post something different than what was reviewed.

**Template format type**: Add `"twitter"` as a new format type alongside tip/insight/question/story/announcement. Twitter templates must be casual, punchy, ≤280 chars, hashtag-focused.

**TWITTER_CHAR_LIMIT constant**: `TWITTER_CHAR_LIMIT = 280`

---

## Decision 6: Twitter Templates Design

**Decision**: Add 5 Twitter-specific templates per topic (one per topic = 5 total, format_type="twitter_short"). Templates are casual, punchy, ≤280 chars.

**Template constraints**:
- Max 280 characters including hashtags
- 1-3 hashtags max (leave room for content)
- Casual tone ("Hot take:", "Real talk:", emoji-forward)
- End with a hook or question (drives engagement)
- No long multi-paragraph text

**Example template** (ai_automation topic):
```
Hot take: The best AI agent is one that asks permission before acting. 🤖

I build every AI action with a human approval step. Slower? Yes. Trustworthy? Absolutely.

What's your HITL strategy?

#AIAgents #BuildInPublic
```
(247 chars — within limit)

**Template count per topic**: 1 Twitter template per topic for MVP (5 total across 5 topics). Expand in future iterations.

---

## Decision 7: Deduplication Key Strategy

**Decision**: Use `_make_dedup_key(sender, text, timestamp)` — identical function signature to FacebookWatcher. Store in `vault/Logs/processed_twitter.json` with 7-day retention.

**Rationale**: Consistent dedup pattern across all social watchers. Twitter-specific file prevents cross-contamination with Facebook/Instagram dedup stores.

**File**: `vault/Logs/processed_twitter.json`

---

## Decision 8: Orchestrator Integration

**Decision**: Add `_twitter_factory()` to `_build_watcher_configs()` following the exact same pattern as `_facebook_factory`. Use lazy import pattern to allow graceful skip if module unavailable.

```python
def _twitter_factory():
    from backend.watchers.twitter_watcher import TwitterWatcher
    keywords_env = os.getenv("TWITTER_KEYWORDS", "")
    keywords = [k.strip() for k in keywords_env.split(",") if k.strip()] or None
    return TwitterWatcher(
        vault_path=str(self.vault_path),
        session_path=os.getenv("TWITTER_SESSION_PATH", "config/twitter_session"),
        check_interval=int(os.getenv("TWITTER_CHECK_INTERVAL", "300")),
        keywords=keywords,
        headless=os.getenv("TWITTER_HEADLESS", "false").lower() == "true",
        dry_run=self.config.dry_run,
        dev_mode=self.config.dev_mode,
    )

configs.append(("Twitter", _twitter_factory))
```

**ActionExecutor**: Add `"twitter_post": "_handle_twitter_post"` to `HANDLERS` dict. Handler follows `_handle_facebook_post` pattern exactly.

---

## Decision 9: Content Scheduler Twitter Platform Tag

**Decision**: The existing `[platform: twitter]` tag parsing in `content_scheduler.py._parse_topics()` and `_save_draft()` already handles arbitrary platform names — we only need to:
1. Add Twitter templates to `post_generator.py` TEMPLATES dict
2. Add Twitter platform logic to `generate()`: pass `platform="twitter"`, validate ≤280 chars, add `TWITTER_CHAR_LIMIT` constant
3. Update `schedule_manager.draft_exists_today()` to include `"TWITTER"` prefix
4. Update `.env.example` with `TWITTER_*` env vars

**No new ContentScheduler parsing logic needed** — the platform routing is already generic from Feature 004.

---

## Decision 10: Environment Variables

**New env vars** (to add to `config/.env.example`):

```bash
# TWITTER INTEGRATION
TWITTER_CHECK_INTERVAL=300
TWITTER_KEYWORDS=urgent,help,project,collab,opportunity,mention
TWITTER_SESSION_PATH=config/twitter_session
TWITTER_HEADLESS=false
```

**Session path gitignore**: Add `config/twitter_session/` to `.gitignore`.

---

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Twitter DOM changes breaking selectors | High | Use broad fallback selector cascade (3+ selectors per action); log failed probes |
| Rate limiting / bot detection | Medium | `--disable-blink-features=AutomationControlled`; 300s check interval is conservative |
| Composite content edge cases in notifications | Medium | Limit scan to MAX_NOTIFICATIONS=20; dedup prevents duplicate processing |
| 280-char limit counting differs for URLs/CJK | Low | Count `len(body)` as raw character count (conservative); Twitter's own counter may differ slightly |

---

## Files to Create / Modify

| File | Action | Notes |
|------|--------|-------|
| `backend/watchers/twitter_watcher.py` | CREATE | Mirror FacebookWatcher pattern; x.com selectors |
| `backend/actions/twitter_poster.py` | CREATE | Mirror FacebookPoster; 280-char limit |
| `backend/orchestrator/orchestrator.py` | MODIFY | Add `_twitter_factory()` to `_build_watcher_configs()` |
| `backend/orchestrator/action_executor.py` | MODIFY | Add `"twitter_post"` to HANDLERS; add `_handle_twitter_post()` |
| `backend/scheduler/post_generator.py` | MODIFY | Add TWITTER_CHAR_LIMIT, Twitter templates, Twitter platform validation |
| `backend/scheduler/schedule_manager.py` | MODIFY | Add `"TWITTER"` to `draft_exists_today()` prefix list |
| `config/.env.example` | MODIFY | Add TWITTER_* env vars |
| `.gitignore` | MODIFY | Add `config/twitter_session/` |
| `skills/twitter-manager/SKILL.md` | CREATE | Skill definition |
| `tests/test_twitter.py` | CREATE | Full test suite |
| `specs/005-twitter-x-integration/tasks.md` | CREATE | Task breakdown (via /sp.tasks) |
