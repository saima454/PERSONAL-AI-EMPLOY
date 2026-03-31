# Data Model: Twitter (X) Integration

**Feature**: 005-twitter-x-integration
**Phase**: 1 — Design
**Date**: 2026-02-21

---

## Entities

### 1. TwitterSession

**Represents**: The persisted browser authentication state for x.com

| Field | Type | Description |
|-------|------|-------------|
| `path` | `Path` | Local directory storing browser session data (`config/twitter_session/`) |
| `headless` | `bool` | Whether browser runs in headless mode (`TWITTER_HEADLESS` env var, default: False) |
| `is_valid` | `bool` (runtime) | Whether the stored session is recognized as authenticated on startup |
| `last_checked` | `str` (ISO 8601) | Timestamp of most recent session state verification |

**State transitions**:
- `not_exists` → `setup_required` (directory missing)
- `setup_required` → `valid` (user runs `--setup`, logs in, presses Enter)
- `valid` → `expired` (x.com redirects to login URL on next startup)
- `expired` → `valid` (user re-runs `--setup`)

**Storage**: Browser persistent context on disk. Not a vault markdown file. No serialization needed beyond what Playwright manages.

---

### 2. TwitterActionFile

**Represents**: A vault markdown file created when a Twitter notification or DM matches a keyword

**Location**: `vault/Needs_Action/TWITTER_{sender_slug}_{timestamp}.md`

**Frontmatter fields**:

| Field | Type | Values / Example |
|-------|------|-----------------|
| `type` | `str` | `"twitter"` (constant) |
| `id` | `str` | `"TWITTER_{short_id}_{timestamp}"` |
| `source` | `str` | `"twitter_watcher"` |
| `item_type` | `str` | `"notification"` \| `"direct_message"` |
| `sender` | `str` | Twitter handle or display name |
| `preview` | `str` | First 200 chars of content |
| `received` | `str` | ISO 8601 timestamp |
| `priority` | `str` | `"high"` \| `"medium"` \| `"low"` |
| `status` | `str` | `"pending"` |
| `matched_keyword` | `str` | Keyword that triggered the match |
| `needs_reply` | `bool` | `True` for DMs (messages requiring a response) |
| `original_url` | `str` | Link back to the tweet/DM thread (when available) |

**Validation rules**:
- `type` MUST be `"twitter"`
- `item_type` MUST be one of: `notification`, `direct_message`
- `preview` truncated to 200 chars max
- `received` MUST be ISO 8601 UTC

---

### 3. TwitterPostDraft

**Represents**: A draft tweet flowing through the HITL approval pipeline

**Locations** (by status):
- `vault/Pending_Approval/TWITTER_POST_{YYYY-MM-DD}.md`
- `vault/Approved/TWITTER_POST_{YYYY-MM-DD}.md`
- `vault/Done/TWITTER_POST_{YYYY-MM-DD}.md`
- `vault/Rejected/TWITTER_POST_{YYYY-MM-DD}.md`

**Frontmatter fields**:

| Field | Type | Values / Example |
|-------|------|-----------------|
| `type` | `str` | `"twitter_post"` (constant) |
| `platform` | `str` | `"twitter"` (constant) |
| `status` | `str` | `"pending_approval"` → `"approved"` → `"done"` \| `"rejected"` |
| `topic` | `str` | Topic title, e.g. `"AI and Automation"` |
| `topic_index` | `int` | 0-based topic position in Content_Strategy |
| `template_id` | `str` | Template used, e.g. `"twitter_ai_01"` |
| `generated_at` | `str` | ISO 8601 generation timestamp |
| `scheduled_date` | `str` | `YYYY-MM-DD` |
| `character_count` | `int` | Length of post body (MUST be ≤ 280) |
| `published_at` | `str` | ISO 8601 timestamp (added on success) |
| `dev_mode` | `bool` | `true` if posted in DEV_MODE |
| `rejection_reason` | `str` | Reason string if status = rejected |

**State transitions**:
```
pending_approval → approved  (human moves file to vault/Approved/)
approved         → done      (TwitterPoster publishes successfully)
approved         → rejected  (TwitterPoster: char limit exceeded or publish failed)
```

**Validation rule**: `character_count` MUST be ≤ 280 before posting. Files exceeding this are auto-rejected by the poster.

---

### 4. TwitterDeduplicationStore

**Represents**: Persistent JSON store tracking processed Twitter item IDs to prevent duplicate action files

**Location**: `vault/Logs/processed_twitter.json`

**Schema**:
```json
{
  "processed_ids": {
    "sender|content_excerpt|timestamp": "2026-02-21T10:00:00+05:00"
  },
  "last_cleanup": "2026-02-21T10:00:00+05:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `processed_ids` | `dict[str, str]` | Map of dedup_key → ISO 8601 processed_at timestamp |
| `last_cleanup` | `str` | ISO 8601 timestamp of last 7-day retention sweep |

**Dedup key format**: `"{sender}|{text[:100]}|{timestamp}"` (identical to Facebook/Instagram pattern)

**Retention policy**: Entries older than 7 days (168 hours) are purged on the first check after 24 hours since last cleanup.

**File lifecycle**:
- Created automatically on first successful action file creation
- Updated atomically on each new processed item
- Purged entries on cleanup cycle (every 24 hours)

---

### 5. TwitterTemplate (Post Generator)

**Represents**: A Twitter-specific post template in the in-memory TEMPLATES dictionary

| Field | Type | Description |
|-------|------|-------------|
| `template_id` | `str` | Unique ID, format: `"twitter_{topic_key}_{n:02d}"` |
| `topic_key` | `str` | `"ai_automation"` \| `"backend_development"` \| `"hackathon_journey"` \| `"cloud_devops"` \| `"career_tips"` |
| `format_type` | `str` | `"twitter_short"` (new format type for Twitter) |
| `body` | `str` | Full tweet text including hashtags, MUST be ≤ 280 chars |
| `hashtags` | `list[str]` | 1-3 hashtags already embedded in body |

**Constraint**: `len(body) ≤ 280` enforced at template authoring time AND runtime validation.

---

## Entity Relationships

```
Content_Strategy.md
    [platform: twitter] tag
           │
           ▼
    TwitterTemplate (post_generator.py)
           │ generates
           ▼
    TwitterPostDraft (vault/Pending_Approval/TWITTER_POST_*.md)
           │ human approves
           ▼
    vault/Approved/TWITTER_POST_*.md
           │ TwitterPoster validates (≤280 chars)
           ▼
    vault/Done/ or vault/Rejected/

TwitterSession (config/twitter_session/)
    │ required for
    ├─── TwitterWatcher (monitors x.com/notifications + x.com/messages)
    │         │ creates
    │         ▼
    │    TwitterActionFile (vault/Needs_Action/TWITTER_*.md)
    │         │ dedup via
    │         └─── TwitterDeduplicationStore (vault/Logs/processed_twitter.json)
    │
    └─── TwitterPoster (publishes vault/Approved/TWITTER_POST_*.md)
```

---

## Action File Lifecycle

```
TwitterWatcher detects matching item
    → _make_dedup_key(sender, text, timestamp)
    → check TwitterDeduplicationStore → skip if exists
    → create_action_file() → writes TWITTER_{sender}_{ts}.md to vault/Needs_Action/
    → update TwitterDeduplicationStore with new dedup_key
```

---

## Constants

| Constant | Value | Module |
|---------|-------|--------|
| `TWITTER_CHAR_LIMIT` | `280` | `backend/scheduler/post_generator.py` |
| `PROCESSED_IDS_RETENTION_DAYS` | `7` | `backend/watchers/twitter_watcher.py` |
| `MAX_NOTIFICATIONS` | `20` | `backend/watchers/twitter_watcher.py` |
| `MAX_MESSAGES` | `15` | `backend/watchers/twitter_watcher.py` |
| `MAX_POSTS_PER_RUN` | `5` | `backend/actions/twitter_poster.py` |
| `POST_CHECK_INTERVAL` | `300` | `backend/actions/twitter_poster.py` |
