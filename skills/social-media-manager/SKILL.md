# SKILL: Social Media Manager

## Metadata

- **Name**: social-media-manager
- **Version**: 1.0.0
- **Tier**: Gold
- **Triggers**:
  - Vault file appears in `vault/Needs_Action/` with `type: facebook` or `type: instagram`
  - Vault file appears in `vault/Approved/` with `type: facebook_post` or `type: instagram_post`
  - Operator runs `--setup` on a watcher for first-time Meta session login
- **Dependencies**:
  - Playwright persistent session at `config/meta_session/` (both Facebook and Instagram)
  - `DEV_MODE=false` required for real publishing; monitoring works in DEV_MODE with synthetic data
- **Permissions Required**:
  - Read: `vault/Needs_Action/`, `vault/Approved/`, `vault/Logs/`
  - Write: `vault/Needs_Action/`, `vault/Done/`, `vault/Rejected/`, `vault/Logs/`
  - External: facebook.com, instagram.com (only when DEV_MODE=false)
- **Rate Limits**: Max 5 posts/day/platform (per constitution Principle VI)
- **Sensitivity**: HIGH — social media posts are in the NEVER auto-approve list (constitution Principle IV)

---

## Body

### Purpose

The Social Media Manager skill enables the Personal AI Employee to:
1. **Monitor** Facebook and Instagram for notifications, comments, and messages
2. **Surface** actionable items in the Obsidian vault for human review
3. **Publish** human-approved social media posts to Facebook and Instagram

All publishing actions require explicit human approval through the HITL vault workflow.

---

### Capability 1: Monitor Facebook

**What it does**: Watches `facebook.com/notifications/` and `facebook.com/messages/` for new items matching configured keywords. Creates markdown vault files for each match.

**How it triggers**: Runs automatically when the orchestrator starts the `FacebookWatcher` (registered in `backend/orchestrator/orchestrator.py`). Also runnable standalone: `python backend/watchers/facebook_watcher.py --once`.

**DEV_MODE behavior**: Returns one synthetic notification file with `[DEV_MODE]` in the title. No real browser opened.

**Output**: `vault/Needs_Action/FACEBOOK_{sender}_{timestamp}.md` with frontmatter:
```yaml
type: facebook
source: facebook_watcher
item_type: notification | message
sender: <display name>
priority: high | medium | low
status: pending
needs_reply: true  # for Messenger messages only
```

**Decision tree**:
1. Is `config/meta_session/` present? → No → log warning, skip cycle
2. Is session expired (URL redirects to login)? → Yes → log `"Meta session expired — re-run --setup"`, skip
3. Item already in `vault/Logs/processed_facebook.json`? → Yes → skip (dedup)
4. Item matches keyword? → No → skip
5. Create vault file, update dedup store

---

### Capability 2: Monitor Instagram

**What it does**: Watches `instagram.com/activity/` and `instagram.com/direct/inbox/` for notifications and DMs.

**How it triggers**: Orchestrator starts `InstagramWatcher` automatically. Standalone: `python backend/watchers/instagram_watcher.py --once`.

**DEV_MODE behavior**: Returns one synthetic notification with `[DEV_MODE]` prefix. No browser.

**Output**: `vault/Needs_Action/INSTAGRAM_{sender}_{timestamp}.md` with frontmatter:
```yaml
type: instagram
source: instagram_watcher
item_type: notification | direct_message
sender: <handle>
priority: high | medium | low
status: pending
needs_reply: true  # for DMs only
```

---

### Capability 3: Post to Facebook

**What it does**: Publishes approved Facebook post drafts to the authenticated Facebook account.

**How it triggers**: ActionExecutor detects `type: facebook_post` + `status: approved` files in `vault/Approved/`. Runs in the executor polling loop (every 30s by default).

**HITL requirement**: Human MUST change `status: pending_approval` → `status: approved` and move file from `vault/Pending_Approval/` to `vault/Approved/` before this capability activates.

**DEV_MODE behavior**: Logs `"[DEV_MODE] Would post to Facebook: {body[:100]}"`, moves file to `vault/Done/` without real publish.

**Validation** (before any browser interaction):
- Body must be non-empty
- Character count ≤ 63,206
- If `image_path` set, file must exist on disk

**On success**: File moved to `vault/Done/` with `status: done`, `published_at` timestamp.
**On failure**: File moved to `vault/Rejected/` with `rejection_reason`.

---

### Capability 4: Post to Instagram

**What it does**: Publishes approved Instagram post drafts (captions) to the authenticated Instagram account.

**How it triggers**: ActionExecutor detects `type: instagram_post` + `status: approved` in `vault/Approved/`.

**HITL requirement**: Same approval flow as Facebook posting.

**DEV_MODE behavior**: Logs `"[DEV_MODE] Would post to Instagram: {body[:100]}"`, moves file to `vault/Done/`.

**Validation**:
- Body must be non-empty
- Caption ≤ 2,200 characters (Instagram limit)
- If `image_path` set, file must exist

---

### Session Setup (One-Time)

Before monitoring or posting can work with real data, the operator must establish the Meta session:

```bash
# Facebook setup (also saves Instagram cookies if you log into both)
python backend/watchers/facebook_watcher.py --setup

# Or Instagram setup separately
python backend/watchers/instagram_watcher.py --setup
```

Both commands open a headed browser at `config/meta_session/`. Log into Facebook and optionally Instagram, then press Enter. The session is saved and reused on subsequent runs.

---

### Error Handling

| Error | Response |
|-------|---------|
| `config/meta_session/` missing | Log warning, skip all Meta watchers for this cycle |
| Session expired (redirect to login) | Log `"Meta session expired"`, skip cycle, do NOT crash |
| CAPTCHA triggered | Log `"CAPTCHA detected"`, skip cycle, alert operator |
| DOM parse failure (platform UI changed) | Log structured warning with element, skip item, continue |
| Post character limit exceeded | Move to `vault/Rejected/` with `rejection_reason: character_count_exceeded` |
| Image file not found | Move to `vault/Rejected/` with `rejection_reason: image_file_not_found` |
| Publish failure (transient) | Retry once after 5s, then move to `vault/Rejected/` |

---

## Resources

- **Session directory**: `config/meta_session/` (gitignored, never committed)
- **Facebook dedup store**: `vault/Logs/processed_facebook.json` (7-day retention)
- **Instagram dedup store**: `vault/Logs/processed_instagram.json` (7-day retention)
- **Facebook watcher**: `backend/watchers/facebook_watcher.py`
- **Instagram watcher**: `backend/watchers/instagram_watcher.py`
- **Facebook poster**: `backend/actions/facebook_poster.py`
- **Instagram poster**: `backend/actions/instagram_poster.py`
- **Orchestrator registration**: `backend/orchestrator/orchestrator.py` `_build_watcher_configs()`
- **Action routing**: `backend/orchestrator/action_executor.py` `HANDLERS` dict
- **Content scheduler**: `backend/scheduler/post_generator.py` (platform field routing)
