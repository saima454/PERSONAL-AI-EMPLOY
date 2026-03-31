# Data Model: Meta Social Integration (004)

**Date**: 2026-02-21
**Feature**: 004-meta-social-integration
**Derived from**: spec.md + research.md

---

## Overview

This feature introduces 5 entities and 2 supporting stores:

| Entity | Location | Producer | Consumer |
|--------|----------|----------|---------|
| MetaSession | `config/meta_session/` | Operator (manual setup) | FacebookWatcher, InstagramWatcher, FacebookPoster, InstagramPoster |
| FacebookNotification | `vault/Needs_Action/` | FacebookWatcher | Operator (Obsidian) |
| InstagramNotification | `vault/Needs_Action/` | InstagramWatcher | Operator (Obsidian) |
| FacebookPostDraft | `vault/Approved/` | ContentScheduler or Operator | ActionExecutor → FacebookPoster |
| InstagramPostDraft | `vault/Approved/` | ContentScheduler or Operator | ActionExecutor → InstagramPoster |

---

## Entity 1: MetaSession

**Type**: Playwright persistent browser context (directory)
**Location**: `config/meta_session/` (Playwright user data dir)
**Scope**: Shared by all 4 Meta components

### State Machine

```
uninitialized ──[--setup run]──► saved ──[session verified]──► ready
                                   │                              │
                                   └──[cookie expiry/logout]──► expired
                                   └──[CAPTCHA triggered]──► captcha
```

### Validation Rules

- Directory must exist before watchers start; absence → skip with `"Meta session not found — run --setup"` warning
- Session validity checked per-watcher per-cycle via URL-based detection (`/login` or `/checkpoint/challenge` in URL)
- Both facebook.com and instagram.com auth are checked independently by their respective watchers
- `DEV_MODE=true` → skip browser launch entirely; return mock data

### Attributes (Conceptual)

| Attribute | Description |
|-----------|-------------|
| `user_data_dir` | `config/meta_session/` — Playwright stores all cookies/storage here |
| `facebook_domains` | `.facebook.com`, `www.facebook.com` |
| `instagram_domains` | `.instagram.com`, `www.instagram.com` |
| `last_verified` | Not persisted; checked live each polling cycle |

---

## Entity 2: FacebookNotification

**Location**: `vault/Needs_Action/FACEBOOK_{sender_slug}_{timestamp}.md`
**Producer**: FacebookWatcher
**Consumer**: Operator (reviews in Obsidian vault)

### Frontmatter Schema

```yaml
---
type: facebook                          # fixed — identifies source platform
id: FACEBOOK_{short_id}_{timestamp}    # unique per file
source: facebook_watcher
item_type: notification | message       # "notification" = mention/comment; "message" = Messenger
sender: "Jane Smith"                    # display name (redacted in logs)
preview: "First 200 chars of content"
received: "2026-02-21T09:00:00Z"       # ISO 8601 UTC
priority: high | medium | low
status: pending
matched_keyword: "invoice"             # keyword that triggered capture (optional)
needs_reply: true                      # only set for Messenger messages
---
```

### Body Template

```markdown
## Facebook {item_type}

**From:** {sender}
**Type:** {item_type}
**Time:** {platform_timestamp}
**Priority:** {priority} (keyword: {matched_keyword})

## Content

{preview}

## Suggested Actions

- [ ] Review on Facebook
- [ ] Reply if needed
- [ ] Mark as processed
```

### Deduplication

- **Store**: `vault/Logs/processed_facebook.json`
- **Key format**: `"{sender}|{text[:100]}|{platform_timestamp}"`
- **Retention**: 7 days (cleanup runs once per day)
- **Schema**:
  ```json
  {
    "processed_ids": { "key": "2026-02-21T09:00:00Z" },
    "last_cleanup": "2026-02-21T00:00:00Z"
  }
  ```

---

## Entity 3: InstagramNotification

**Location**: `vault/Needs_Action/INSTAGRAM_{sender_slug}_{timestamp}.md`
**Producer**: InstagramWatcher

Identical frontmatter schema to FacebookNotification with:

| Field | Value |
|-------|-------|
| `type` | `instagram` |
| `source` | `instagram_watcher` |
| `id` | `INSTAGRAM_{short_id}_{timestamp}` |
| `item_type` | `notification` \| `direct_message` |

**Deduplication store**: `vault/Logs/processed_instagram.json`

---

## Entity 4: FacebookPostDraft

**Location**: `vault/Pending_Approval/FACEBOOK_POST_{timestamp}.md`  → after approval → `vault/Approved/FACEBOOK_POST_{timestamp}.md`
**Producer**: ContentScheduler (auto) or Operator (manual)
**Consumer**: ActionExecutor → FacebookPoster

### Frontmatter Schema

```yaml
---
type: facebook_post                     # key routing field — ActionExecutor reads this
status: pending_approval | approved    # "approved" triggers ActionExecutor pickup
platform: facebook
topic: "behind-the-scenes"             # source topic slug (optional)
scheduled_for: "2026-02-22"            # target date (optional)
character_count: 1250                  # pre-computed at draft time
image_path: ""                         # optional: path to image file
generated_at: "2026-02-21T09:00:00Z"
---
```

### Validation Rules (enforced by FacebookPoster before publishing)

| Rule | Condition | On failure |
|------|-----------|-----------|
| `character_count ≤ 63,206` | Platform limit | Move to `vault/Rejected/` |
| Body non-empty | After stripping frontmatter | Move to `vault/Rejected/` |
| `image_path` exists on disk | Only if `image_path` is set | Move to `vault/Rejected/` |

### State Transitions

```
pending_approval ──[human approves]──► approved ──[executor picks up]──► publishing
                                                                            │
                                                         success ◄──────────┤
                                                       (→ Done/)            │
                                                                     failure/validation error
                                                                       (→ Rejected/)
```

---

## Entity 5: InstagramPostDraft

**Location**: `vault/Pending_Approval/INSTAGRAM_POST_{timestamp}.md` → `vault/Approved/`
**Producer**: ContentScheduler or Operator
**Consumer**: ActionExecutor → InstagramPoster

Identical to FacebookPostDraft with:

| Field | Value |
|-------|-------|
| `type` | `instagram_post` |
| `platform` | `instagram` |
| `character_count` | ≤ 2,200 (Instagram caption limit) |

---

## Supporting Store: ContentStrategy Extension

**Location**: `vault/Content_Strategy.md` (existing file from feature 003)

New optional `platform` field added to each topic:

```yaml
topics:
  - name: "AI in Business"
    platform: linkedin        # existing topics — no change needed (default)
    template: "thought-leadership"
    frequency: weekly

  - name: "Behind the Scenes"
    platform: facebook        # NEW — routes to type: facebook_post
    template: "casual"
    frequency: weekly

  - name: "Visual Story"
    platform: instagram       # NEW — routes to type: instagram_post
    template: "visual"
    frequency: twice_weekly
```

**Backward compatibility**: Topics without `platform` field default to `"linkedin"`. Feature 003 topics are unaffected.

---

## Entity Relationships

```
Content_Strategy.md
    │ (topic with platform)
    ▼
ContentScheduler.run_if_due()
    │ generates
    ▼
FacebookPostDraft / InstagramPostDraft / LinkedInPostDraft
    │ (in vault/Pending_Approval/)
    │ [human reviews in Obsidian]
    ▼
vault/Approved/  ←──── MetaSession ─────► vault/Done/ or vault/Rejected/
    │                (used by Poster)
    ▼
ActionExecutor._handle_facebook_post()
    │ delegates to
    ▼
FacebookPoster.process_approved_posts()
    │ publishes via Playwright using
    └── MetaSession (config/meta_session/)

FacebookWatcher.check_for_updates()
    │ reads live data from Facebook using MetaSession
    │ creates
    ▼
FacebookNotification (vault/Needs_Action/)
    │ dedup tracked in
    └── processed_facebook.json (vault/Logs/)
```
