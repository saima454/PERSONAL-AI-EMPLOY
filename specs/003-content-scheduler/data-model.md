# Data Model: Smart Content Scheduler

**Branch**: `003-content-scheduler` | **Date**: 2026-02-20 | **Phase**: 1

---

## Entities

### 1. ContentStrategy

**Source of truth**: `vault/Content_Strategy.md` (Markdown with YAML frontmatter)

**Frontmatter fields:**

```yaml
---
last_updated: 2026-02-20       # ISO date, updated by user
post_frequency: daily          # daily | weekdays_only | custom_days
preferred_time: "09:00"        # HH:MM 24-hour, local timezone
tone: professional but approachable
max_hashtags: 5
---
```

**Body sections (parsed by `ContentScheduler`):**

| Section Heading | Content | Required |
|---|---|---|
| `## Topics I Want to Post About` | Numbered list of topic entries | Yes |
| `## Content Rules` | Bullet list of freeform rules | No |
| `## Do NOT Post About` | Bullet list of exclusions | No |

**Topic entry format**: `N. <Title> - <Description>`

**Python representation** (dataclass in `content_scheduler.py`):

```python
@dataclass
class ContentStrategy:
    topics: list[Topic]                   # Ordered list
    post_frequency: str                   # "daily" | "weekdays_only" | "custom_days"
    preferred_time: str                   # "09:00"
    tone: str                             # Freeform string
    max_hashtags: int                     # Default: 5
    content_rules: list[str]              # Parsed bullet points
    excluded_topics: list[str]            # Parsed Do NOT Post list

@dataclass
class Topic:
    index: int                            # 1-based position in list
    title: str                            # "AI and Automation"
    description: str                      # "Share insights about building AI agents"
```

---

### 2. PostDraft

**Persisted as**: `vault/Pending_Approval/LINKEDIN_POST_{YYYY-MM-DD}.md`

**Frontmatter fields:**

```yaml
---
type: linkedin_post                # Required by ActionExecutor routing (RQ-1)
status: pending_approval           # pending_approval → approved (by user) → done
topic: AI and Automation           # Selected topic title
topic_index: 1                     # 0-based index in strategy topics list
template_id: ai_automation_tip_01  # Template identifier used
generated_at: 2026-02-20T09:00:00+05:00   # ISO 8601 with timezone
scheduled_date: 2026-02-20         # YYYY-MM-DD, date this post is for
character_count: 847               # Character count of post body (excl. heading)
---

# Post Content

[Actual LinkedIn post text with hashtags]
```

**State transitions**:
```
pending_approval
    ↓ (user moves file to vault/Approved/)
approved              (status updated to "approved" by user or HITL workflow)
    ↓ (ActionExecutor processes)
done                  (status updated to "done" by ActionExecutor._move_to_done)
```

**Naming convention**: `LINKEDIN_POST_YYYY-MM-DD.md` — one file per calendar day.

---

### 3. PostingHistory

**Persisted as**: `vault/Logs/posted_topics.json`

**Schema**:
```json
{
  "entries": [
    {
      "date": "2026-02-20",
      "topic_index": 0,
      "topic_title": "AI and Automation",
      "template_id": "ai_automation_tip_01",
      "draft_path": "vault/Pending_Approval/LINKEDIN_POST_2026-02-20.md",
      "generated_at": "2026-02-20T09:00:12+05:00"
    }
  ]
}
```

**Python representation**:
```python
@dataclass
class PostingHistoryEntry:
    date: str              # YYYY-MM-DD
    topic_index: int       # 0-based index
    topic_title: str
    template_id: str
    draft_path: str
    generated_at: str      # ISO 8601

@dataclass
class PostingHistory:
    entries: list[PostingHistoryEntry]

    def last_topic_index(self) -> int | None: ...
    def was_posted_today(self, date: str) -> bool: ...
    def add_entry(self, entry: PostingHistoryEntry) -> None: ...
```

**Retention**: All entries kept (grows over time). File is append-friendly (JSON array).

---

### 4. ScheduleState

**Persisted as**: `vault/Logs/posting_schedule.json`

**Schema**:
```json
{
  "last_run_date": "2026-02-20",
  "last_topic_index": 0,
  "next_topic_index": 1,
  "post_frequency": "daily",
  "skip_weekends": false,
  "timezone": "Asia/Karachi",
  "posts_today": 1,
  "updated_at": "2026-02-20T09:00:15+05:00"
}
```

**Python representation**:
```python
@dataclass
class ScheduleState:
    last_run_date: str | None       # YYYY-MM-DD or None (first run)
    last_topic_index: int           # 0-based, last topic used
    next_topic_index: int           # 0-based, next to use
    post_frequency: str             # "daily" | "weekdays_only" | "custom_days"
    skip_weekends: bool
    timezone: str                   # e.g. "Asia/Karachi"
    posts_today: int                # Count of drafts generated today
    updated_at: str                 # ISO 8601
```

**Default state** (created if file missing):
```json
{
  "last_run_date": null,
  "last_topic_index": -1,
  "next_topic_index": 0,
  "post_frequency": "daily",
  "skip_weekends": false,
  "timezone": "Asia/Karachi",
  "posts_today": 0,
  "updated_at": null
}
```

---

### 5. PostTemplate

**Persisted as**: In-code Python dataclasses in `backend/scheduler/post_generator.py`

**Structure**:
```python
@dataclass
class PostTemplate:
    template_id: str          # e.g. "ai_automation_tip_01"
    topic_key: str            # e.g. "ai_automation" (normalized topic title)
    format_type: str          # "tip" | "insight" | "question" | "story" | "announcement"
    body: str                 # Template string with {insight}, {question}, {hashtags}
    default_hashtags: list[str]  # Topic-specific defaults (3-5)
    max_length: int           # Expected max after filling (safety check)
```

**Template format types** (5 required per topic):

| Format | Description | Trigger phrase |
|--------|-------------|---------------|
| `tip` | How-to / actionable advice | "Here's what I learned..." |
| `insight` | Personal observation or opinion | "Hot take:" or "Unpopular opinion:" |
| `question` | Engagement-driving question | "What do you think about..." |
| `story` | Short personal experience narrative | "Last week I..." |
| `announcement` | Achievement or update | "Excited to share..." |

**Topic keys** (5 topics × 5 templates = 25 minimum):
- `ai_automation` — AI and Automation
- `backend_development` — Backend Development
- `hackathon_journey` — Hackathon Journey
- `cloud_devops` — Cloud & DevOps
- `career_tips` — Career Tips

---

## File Layout (Vault)

```
vault/
├── Content_Strategy.md                     # User config (read by scheduler)
├── Pending_Approval/
│   └── LINKEDIN_POST_YYYY-MM-DD.md         # Generated drafts (HITL)
├── Approved/
│   └── LINKEDIN_POST_YYYY-MM-DD.md         # Human-approved posts
├── Done/
│   └── LINKEDIN_POST_YYYY-MM-DD.md         # Published posts
└── Logs/
    ├── posted_topics.json                  # PostingHistory
    └── posting_schedule.json               # ScheduleState
```

---

## State Transitions Diagram

```
[Content_Strategy.md]
        ↓ (ContentScheduler reads on run)
[ScheduleState: is_due?]
        ↓ YES
[PostGenerator: select topic, fill template]
        ↓
[PostDraft: status=pending_approval]
        → vault/Pending_Approval/LINKEDIN_POST_{date}.md
        ↓ (user moves to Approved/)
[PostDraft: status=approved]
        → vault/Approved/LINKEDIN_POST_{date}.md
        ↓ (ActionExecutor polls, finds type=linkedin_post)
[LinkedInPoster: publishes via Playwright]
        ↓
[PostDraft: status=done]
        → vault/Done/LINKEDIN_POST_{date}.md
```

---

## Validation Rules

| Field | Rule | Error handling |
|---|---|---|
| `topics` | Min 1 entry required | Log error, exit without draft |
| `character_count` | Must be ≤ 1300 | Retry with shorter template; truncate as last resort |
| `LINKEDIN_POST_{date}.md` | Must not already exist in Pending_Approval or Approved | Skip (idempotency) |
| `posting_schedule.json` | Must be valid JSON | Reset to default state on parse error |
| `posted_topics.json` | Must be valid JSON | Reset to empty on parse error |
| `topic_index` | Must be 0 ≤ n < len(topics) | Wrap around (modulo) |
