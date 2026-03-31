# Skill: Content Scheduler

## Metadata

```yaml
name: content-scheduler
version: 1.0.0
layer: PERCEPTION
sensitivity: MEDIUM
```

## Triggers

Invoke this skill when the user says:
- "generate a LinkedIn post"
- "create a post draft"
- "check content schedule"
- "preview today's post"
- "what should I post today"
- "generate now" / "force generate post"
- "show post status" / "scheduler status"
- "is a post due today"

## What This Skill Does

The Content Scheduler is a PERCEPTION layer skill. It reads the user's content strategy, selects the next topic in rotation, generates a LinkedIn post draft from templates, and saves it to `vault/Pending_Approval/` for human review.

**It does NOT post to LinkedIn directly.** That is handled by the `linkedin-poster` skill after human approval.

## End-to-End Flow

```
vault/Content_Strategy.md
        ↓ (scheduler reads topics + rules)
Topic Selection (rotation — no consecutive repeats)
        ↓
Template Selection (random from 5 formats: tip/insight/question/story/announcement)
        ↓
vault/Pending_Approval/LINKEDIN_POST_{date}.md   ← HITL checkpoint
        ↓ (human approves in Obsidian)
vault/Approved/LINKEDIN_POST_{date}.md
        ↓ (action executor + linkedin-poster skill)
Published on LinkedIn → vault/Done/
```

## Permissions

```yaml
permissions:
  vault_read:
    - vault/Content_Strategy.md
    - vault/Company_Handbook.md
    - vault/Business_Goals.md
    - vault/Logs/posted_topics.json
    - vault/Logs/posting_schedule.json
  vault_write:
    - vault/Pending_Approval/LINKEDIN_POST_*.md
    - vault/Logs/posted_topics.json
    - vault/Logs/posting_schedule.json
  external_apis: none        # Template-based, no LLM API calls
  browser: none              # Posting handled by linkedin-poster skill
```

## HITL Requirement

**REQUIRED** — all generated drafts go to `vault/Pending_Approval/` first.

LinkedIn posts are flagged `sensitivity: high` per constitution Principle IV. The system NEVER auto-approves social media posts.

## Dependencies

- `skills/linkedin-poster/` — required for the action execution leg (P5)
- `backend/scheduler/` — Python implementation
- `vault/Content_Strategy.md` — must exist and be populated by user

## CLI Commands

```bash
# Check schedule status
uv run python -m backend.scheduler.content_scheduler --status

# Preview without saving
uv run python -m backend.scheduler.content_scheduler --preview

# Force generate now
uv run python -m backend.scheduler.content_scheduler --generate-now

# Normal run (respects schedule)
uv run python -m backend.scheduler.content_scheduler
```

## Decision Tree

```
User: "generate post" / scheduler runs
    ↓
Content_Strategy.md exists?
    NO → Error: "Create vault/Content_Strategy.md first"
    YES ↓
Is a post due today? (frequency + skip_weekends check)
    NO → Skip (log reason)
    YES ↓
Draft already exists today?
    YES → Skip (idempotency) unless --generate-now
    NO ↓
Select next topic (rotation: no consecutive repeats)
    ↓
Generate post from template (validate ≤ 1300 chars)
    ↓
Save to vault/Pending_Approval/LINKEDIN_POST_{date}.md
    ↓
Notify: "Draft ready for review in Obsidian"
```

## Rate Limits

- Maximum 1 draft generated per calendar day (idempotency guard)
- `--generate-now` overrides the daily limit
- LinkedIn posting: 5 posts/day/platform (enforced by constitution Principle VI)

## Environment Variables

```
CONTENT_POST_FREQUENCY=daily       # daily | weekdays_only | custom_days
CONTENT_POST_TIME=09:00            # HH:MM local time
CONTENT_TIMEZONE=Asia/Karachi      # IANA timezone name
CONTENT_SKIP_WEEKENDS=false        # true = no posts on Sat/Sun
```

## Template Topics Covered

1. **AI and Automation** — 5 templates (tip, insight, question, story, announcement)
2. **Backend Development** — 5 templates
3. **Hackathon Journey** — 5 templates
4. **Cloud & DevOps** — 5 templates
5. **Career Tips** — 5 templates

**Total**: 25+ templates, all persona-specific to Taha (Agentic AI & Senior Backend Engineer)

## Safety Constraints

- Never modify files in `vault/Approved/` or `vault/Done/`
- Never call LinkedIn API or open browser
- Always respect `DEV_MODE` flag (no real actions in dev mode)
- Always respect `--dry-run` flag (log actions, no file writes)
- Rotation counter skipped days do NOT count as "posted" for topic tracking
