# SKILL: Twitter Manager

## Metadata

- **Name**: twitter-manager
- **Version**: 1.0.0
- **Tier**: Gold
- **Triggers**:
  - Vault file appears in `vault/Needs_Action/` with `type: twitter`
  - Vault file appears in `vault/Approved/` with `type: twitter_post`
  - Operator runs `--setup` on the watcher for first-time Twitter/X session login
  - Content Scheduler topic line includes `[platform: twitter]` tag
- **Dependencies**:
  - Playwright persistent session at `config/twitter_session/` (separate from Meta session)
  - `DEV_MODE=false` required for real posting; monitoring works in DEV_MODE with synthetic data
- **Permissions Required**:
  - Read: `vault/Needs_Action/`, `vault/Approved/`, `vault/Logs/`
  - Write: `vault/Needs_Action/`, `vault/Done/`, `vault/Rejected/`, `vault/Logs/`
  - External: x.com (only when DEV_MODE=false)
- **Rate Limits**: Max 5 posts/day (per constitution Principle VI)
- **Sensitivity**: HIGH — Twitter/X posts are in the NEVER auto-approve list (constitution Principle IV)

---

## Body

### Purpose

The Twitter Manager skill enables the Personal AI Employee to:
1. **Monitor** Twitter/X notifications and DMs for items matching configured keywords
2. **Surface** actionable items in the Obsidian vault for human review
3. **Publish** human-approved Twitter/X posts (max 280 characters)
4. **Generate** Twitter-optimized draft posts via the Content Scheduler

All publishing actions require explicit human approval through the HITL vault workflow.

---

### Capability 1: Monitor Twitter Notifications

**What it does**: Watches `x.com/notifications` for new items matching `TWITTER_KEYWORDS`. Creates markdown vault files for each keyword match.

**How it triggers**: Runs automatically when the orchestrator starts the `TwitterWatcher` (registered in `backend/orchestrator/orchestrator.py`). Also runnable standalone: `python backend/watchers/twitter_watcher.py --once`.

**DEV_MODE behavior**: Returns one synthetic notification file with `[DEV_MODE]` in the sender field. No real browser opened.

**Output**: `vault/Needs_Action/TWITTER_{sender}_{timestamp}.md` with frontmatter:
```yaml
type: twitter
source: twitter_watcher
item_type: notification
sender: <display name>
priority: high | medium | low
status: pending
matched_keyword: <keyword>
needs_reply: false
```

**Decision tree**:
1. Is `config/twitter_session/` present? → No → log warning, skip cycle
2. Is session expired (URL redirects to `/i/flow/login`)? → Yes → log `"Twitter session expired — re-run --setup"`, skip
3. Item already in `vault/Logs/processed_twitter.json`? → Yes → skip (7-day dedup)
4. Item text matches keyword from `TWITTER_KEYWORDS`? → No → skip
5. All checks pass → create `vault/Needs_Action/TWITTER_*.md`

---

### Capability 2: Monitor Twitter DMs

**What it does**: Watches `x.com/messages` for new DM conversations matching `TWITTER_KEYWORDS`. Creates vault action files with `needs_reply: true`.

**How it triggers**: Same as Capability 1 — runs as part of the `TwitterWatcher.check_for_updates()` call which polls both notifications and messages in one cycle.

**DEV_MODE behavior**: Included in the single synthetic notification returned in DEV_MODE.

**Output**: `vault/Needs_Action/TWITTER_{sender}_{timestamp}.md` with frontmatter:
```yaml
type: twitter
source: twitter_watcher
item_type: direct_message
sender: <display name>
priority: high | medium | low
status: pending
matched_keyword: <keyword>
needs_reply: true
```

**Decision tree**:
1. Session ready? → No → return [] for messages
2. Navigate to `x.com/messages`
3. Try DM selector cascade: `[data-testid="conversationItem"]` → `[data-testid="DMConversationItem"]` → `[data-testid="conversation"]`
4. For each thread: classify priority, check dedup, create action file

---

### Capability 3: Post to Twitter/X

**What it does**: Reads approved `type: twitter_post` files from `vault/Approved/`, navigates to `x.com/home` via Playwright, composes and submits a tweet (max 280 chars), and moves the file to `vault/Done/`.

**How it triggers**:
- Via ActionExecutor polling `vault/Approved/` every `check_interval` seconds
- Or standalone: `python backend/actions/twitter_poster.py --once`

**DEV_MODE behavior**: Logs `"[DEV_MODE] Would post to Twitter: {body[:100]}"`, sets `dev_mode: true` frontmatter, moves file to `vault/Done/`. No browser opened.

**Hard limit enforcement**: Posts exceeding 280 characters are rejected (moved to `vault/Rejected/` with `rejection_reason: exceeds_character_limit`). The poster never truncates — truncation is only an emergency safety net in the content generator.

**Output**: File moved to `vault/Done/{filename}.md` with:
```yaml
status: done
published_at: <ISO 8601 timestamp>
```
Or rejected to `vault/Rejected/{filename}.md` with:
```yaml
status: rejected
rejected_at: <ISO 8601 timestamp>
rejection_reason: exceeds_character_limit | empty_body | publish_failed
```

**Decision tree**:
1. Is `type: twitter_post` and `status: approved`? → No → skip
2. Is body empty? → Yes → reject with `empty_body`
3. Is `len(body) > 280`? → Yes → reject with `exceeds_character_limit`
4. Is `dev_mode` or `dry_run`? → Yes → log and move to Done with `dev_mode: true`
5. Navigate to `x.com/home`, verify session ready, find textarea, type body, click Post
6. Success → `vault/Done/`; failure → `vault/Rejected/` with `publish_failed`

---

### Capability 4: Generate Twitter Drafts via Scheduler

**What it does**: When a topic line in `vault/Content_Strategy.md` includes `[platform: twitter]`, the Content Scheduler generates a `TWITTER_POST_{YYYY-MM-DD}.md` draft in `vault/Pending_Approval/` with body ≤ 280 characters.

**How it triggers**: On orchestrator startup, `_check_content_schedule()` runs `ContentScheduler.run_if_due()`. Can also be triggered manually: `python -m backend.scheduler.content_scheduler --generate-now`.

**DEV_MODE behavior**: Draft is written to `vault/Pending_Approval/` regardless of DEV_MODE (drafts are safe — they require human approval before any posting).

**Output**: `vault/Pending_Approval/TWITTER_POST_{today}.md` with frontmatter:
```yaml
type: twitter_post
platform: twitter
status: pending
topic: <topic title>
template_id: <template_id>
character_count: <N>
generated_at: <ISO 8601>
```

**Idempotency**: If `TWITTER_POST_{today}.md` already exists in `Pending_Approval/` or `Approved/`, no new draft is generated that day.

---

### Session Setup

Run once to authenticate with Twitter/X:

```bash
uv run python backend/watchers/twitter_watcher.py --setup
```

1. Browser opens in headed (non-headless) mode at `x.com/home`
2. Log in manually with your Twitter/X credentials
3. Press Enter in the terminal when logged in
4. Session data is saved to `config/twitter_session/`
5. Future runs reuse the session automatically — no login needed

**Note**: `config/twitter_session/` is excluded from git (see `.gitignore`).

---

### Error Handling

| Error | Detection | Resolution |
|-------|-----------|------------|
| Session expired | URL redirects to `/i/flow/login` | Re-run `--setup` to re-authenticate |
| Account suspended | URL redirects to `/account/suspended` | Resolve with Twitter/X support |
| Textarea not found | All `POST_SELECTORS["text_area"]` fail | Twitter UI updated — check DOM selectors |
| Post button not found | All `POST_SELECTORS["submit_button"]` fail | Twitter UI updated — check DOM selectors |
| Character limit exceeded | `len(body) > 280` | Edit draft and reduce to ≤280 chars |
| Session path missing | `config/twitter_session/` not found | Run `--setup` first |
| Watcher crash (3× restart) | Watchdog marks as FAILED | Check `vault/Logs/errors/` for details |

---

### Resources

| Resource | Path |
|----------|------|
| Watcher | `backend/watchers/twitter_watcher.py` |
| Poster | `backend/actions/twitter_poster.py` |
| Orchestrator registration | `backend/orchestrator/orchestrator.py` — `_twitter_factory()` |
| Action executor handler | `backend/orchestrator/action_executor.py` — `_handle_twitter_post()` |
| Content scheduler templates | `backend/scheduler/post_generator.py` — `TEMPLATES["twitter_tips"]` |
| Schedule idempotency | `backend/scheduler/schedule_manager.py` — `draft_exists_today()` |
| Session storage | `config/twitter_session/` (gitignored) |
| Dedup store | `vault/Logs/processed_twitter.json` |
| Tests | `tests/test_twitter.py` |
| Environment variables | `config/.env` — `TWITTER_CHECK_INTERVAL`, `TWITTER_KEYWORDS`, `TWITTER_SESSION_PATH`, `TWITTER_HEADLESS` |
