# Quickstart: Smart Content Scheduler

**Branch**: `003-content-scheduler` | **Date**: 2026-02-20

---

## Prerequisites

1. Python 3.13+ with `uv` installed
2. Project dependencies installed: `uv sync`
3. `config/.env` file exists (copy from `config/.env.example`)
4. `vault/` directory structure exists (created by orchestrator on first run)

---

## Step 1: Configure Your Content Strategy

Create `vault/Content_Strategy.md` with your topics and rules:

```markdown
---
last_updated: 2026-02-20
post_frequency: daily
preferred_time: "09:00"
tone: professional but approachable
max_hashtags: 5
---

## Topics I Want to Post About
1. AI and Automation - Share insights about building AI agents
2. Backend Development - Python, FastAPI, system design tips
3. Hackathon Journey - Updates on my AI Employee project
4. Cloud & DevOps - Kubernetes, Docker, deployment tips
5. Career Tips - Lessons learned as a developer

## Content Rules
- Keep posts under 1300 characters
- Always include a question to drive engagement
- Use emojis sparingly (1-2 per post)
- Include 3-5 relevant hashtags
- Rotate topics (don't repeat same topic 2 days in a row)
- Reference my experience as Agentic AI & Senior Backend Engineer

## Do NOT Post About
- Politics or religion
- Negative content about competitors
- Personal/private matters
```

---

## Step 2: Add Environment Variables

Add to `config/.env`:

```env
# Content Scheduler
CONTENT_POST_FREQUENCY=daily
CONTENT_POST_TIME=09:00
CONTENT_TIMEZONE=Asia/Karachi
CONTENT_SKIP_WEEKENDS=false
```

---

## Step 3: Check Schedule Status

```bash
uv run python -m backend.scheduler.content_scheduler --status
```

Expected output:
```
Content Scheduler Status
========================
Last post date  : None (no posts yet)
Last topic      : None
Next topic      : AI and Automation
Due today       : YES
Posts today     : 0
Next run time   : 09:00 Asia/Karachi
```

---

## Step 4: Preview a Draft (no files written)

```bash
uv run python -m backend.scheduler.content_scheduler --preview
```

Expected output:
```
[PREVIEW] Topic: AI and Automation
[PREVIEW] Template: ai_automation_tip_01 (tip)
[PREVIEW] Character count: 847/1300
[PREVIEW] ---
[post content here]
---
[PREVIEW] No files written.
```

---

## Step 5: Generate a Draft

**Normal (schedule-aware):**
```bash
uv run python -m backend.scheduler.content_scheduler
```

**Force generate (ignores existing drafts today):**
```bash
uv run python -m backend.scheduler.content_scheduler --generate-now
```

Both commands create: `vault/Pending_Approval/LINKEDIN_POST_2026-02-20.md`

---

## Step 6: Review & Approve in Obsidian

1. Open Obsidian and navigate to `vault/Pending_Approval/`
2. Open `LINKEDIN_POST_2026-02-20.md`
3. Review the post content
4. If approved: move the file to `vault/Approved/`
5. If rejected: move the file to `vault/Rejected/`

---

## Step 7: Auto-Posting via Orchestrator

The action executor polls `vault/Approved/` every 30 seconds. When it finds a file with `type: linkedin_post`, it calls the LinkedIn poster.

**DEV_MODE (default):**
```
[ActionExecutor] [DEV_MODE] Would execute linkedin_post from LINKEDIN_POST_2026-02-20.md
→ File moved to vault/Done/
```

**Production mode (DEV_MODE=false):**
- LinkedIn poster launches Playwright browser
- Opens linkedin.com/feed/ with saved session
- Types and submits the post
- File moves to `vault/Done/`

---

## Step 8: Verify End-to-End

After approval + executor run, check:

```bash
# Should be empty (file moved to Done)
ls vault/Approved/LINKEDIN_POST_*.md

# Should have the completed post
ls vault/Done/LINKEDIN_POST_*.md

# Check the log
cat vault/Logs/posted_topics.json
```

---

## Automated Run via Orchestrator

The orchestrator checks the content schedule on every startup:

```bash
# Start full orchestrator (includes content schedule check)
uv run python -m backend.orchestrator

# Expected log line on startup:
# [Orchestrator] Content scheduler: draft generated → vault/Pending_Approval/LINKEDIN_POST_2026-02-20.md
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ContentStrategyError: file not found` | `vault/Content_Strategy.md` missing | Create it (Step 1) |
| Draft not generated (already exists) | `LINKEDIN_POST_{today}.md` exists in Pending_Approval or Approved | Use `--generate-now` to override |
| Post exceeds 1300 characters | Template filled with long context | Use `--preview` to inspect; system auto-retries with shorter template |
| LinkedIn poster fails: "Not logged in" | Session expired | Run `uv run python backend/actions/linkedin_poster.py --setup` |
| `posting_schedule.json` corrupt | Manual edit or disk error | Delete the file; scheduler recreates with defaults |

---

## Tests

```bash
# Run all content scheduler tests
uv run pytest tests/test_content_scheduler.py -v

# Run with coverage
uv run pytest tests/test_content_scheduler.py --cov=backend.scheduler -v
```
