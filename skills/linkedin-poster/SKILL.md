---
name: linkedin-poster
version: 1.0.0
description: |
  Combined PERCEPTION + ACTION layer skill for LinkedIn integration.
  Part 1 (Watcher): Monitors LinkedIn notifications and messages for important items.
  Part 2 (Poster): Auto-posts approved content to LinkedIn feed.

  TRIGGERS: Use this skill when you need to:
  - Set up LinkedIn monitoring ("setup linkedin", "configure linkedin")
  - Check LinkedIn notifications ("check linkedin", "any linkedin messages")
  - Create a LinkedIn post draft ("draft linkedin post", "write linkedin post")
  - Post approved content to LinkedIn ("post to linkedin")
  - Debug LinkedIn issues ("linkedin not working")

  NOTE: The watcher runs as a background process. The poster reads approved
  files from the vault and posts them.
dependencies:
  - vault-manager
permissions:
  - read: linkedin.com (via Playwright browser automation)
  - write: linkedin.com/feed (posting - requires HITL approval)
  - write: vault/Needs_Action/*.md
  - write: vault/Logs/**/*.json
  - move: vault/Approved/ -> vault/Done/
sensitivity: high
---

# LinkedIn Integration Skill

Monitor LinkedIn for important notifications/messages and auto-post approved content. This skill has two components:

1. **LinkedIn Watcher** (PERCEPTION layer) - observes notifications and messages
2. **LinkedIn Poster** (ACTION layer) - posts approved content to feed

## Architecture Role

```
┌─────────────────────────────────────────────────────────────────┐
│                    PERCEPTION LAYER                             │
│                                                                 │
│  linkedin_watcher.py ──────► vault/Needs_Action/LINKEDIN_*.md  │
│        │                                                        │
│        └──────────────────► vault/Logs/actions/*.json           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    REASONING LAYER                              │
│                                                                 │
│  Claude Code creates draft posts ──► vault/Pending_Approval/   │
│  Human reviews in Obsidian ────────► vault/Approved/           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ACTION LAYER                                 │
│                                                                 │
│  linkedin_poster.py reads vault/Approved/ (type: linkedin_post)│
│        │                                                        │
│        ├──────────────────► Posts to LinkedIn feed              │
│        └──────────────────► vault/Done/ + vault/Logs/          │
└─────────────────────────────────────────────────────────────────┘
```

## Privacy Notice

All data is processed locally. LinkedIn credentials are stored as browser session
data in `config/linkedin_session/` on your machine only. Post content is drafted
and approved locally before being published.

## Setup Instructions

### Step 1: Install Playwright Browsers

```bash
uv run playwright install chromium
```

### Step 2: Configure Environment Variables

Edit your `config/.env` file:

```bash
# LinkedIn Configuration
LINKEDIN_CHECK_INTERVAL=300
LINKEDIN_KEYWORDS=opportunity,invoice,project,meeting,urgent,proposal,partnership,job
LINKEDIN_SESSION_PATH=config/linkedin_session
LINKEDIN_HEADLESS=false
```

### Step 3: First-Time Login

LinkedIn requires manual login (no QR code). The first run opens a headed browser:

```bash
uv run python backend/watchers/linkedin_watcher.py --setup
```

**Process:**
1. Chromium browser opens showing LinkedIn login page
2. Log in with your LinkedIn credentials manually
3. Complete any 2FA/CAPTCHA challenges
4. Wait for LinkedIn feed to load (you see your feed)
5. Press Enter in the terminal to confirm login
6. Session is saved to `config/linkedin_session/`

### Step 4: Start Monitoring

```bash
# Set headless mode after setup
LINKEDIN_HEADLESS=true

# Start watcher
uv run python backend/watchers/linkedin_watcher.py
```

## Part 1: LinkedIn Watcher

### Notification Monitoring

The watcher checks LinkedIn notifications page for new items.

**Default Keywords:** opportunity, invoice, project, meeting, urgent, proposal, partnership, job

Configure via `LINKEDIN_KEYWORDS` in `config/.env`.

### Priority Classification

| Priority | Keywords |
|----------|----------|
| HIGH | urgent, invoice, proposal |
| MEDIUM | opportunity, project, meeting, job, partnership |
| LOW | (other matched keywords) |

### Action File Format

**File Location:** `vault/Needs_Action/LINKEDIN_{source}_{timestamp}.md`

**Frontmatter Schema:**

```yaml
---
type: linkedin
id: LINKEDIN_a1b2c3d4_20260212T091500
source: linkedin_watcher
item_type: notification | message
sender: John Smith
preview: "Mentioned you in a comment about the project..."
received: 2026-02-12T09:15:00Z
priority: medium
status: pending
---
```

### Duplicate Prevention

Location: `vault/Logs/processed_linkedin.json`

Dedup key: `sender|preview_text[:100]|timestamp`

## Part 2: LinkedIn Poster

### HITL Approval Workflow

Posts MUST go through the approval workflow:

```
Claude drafts post → vault/Pending_Approval/  (type: linkedin_post)
Human reviews      → moves to vault/Approved/
Poster runs        → reads vault/Approved/, posts, moves to vault/Done/
```

### Draft Post Format

Files in `vault/Pending_Approval/` with type `linkedin_post`:

```yaml
---
type: linkedin_post
id: LPOST_a1b2c3d4_20260212T090000
source: claude_draft
status: pending_approval
created: 2026-02-12T09:00:00Z
action_summary: "Post about AI hackathon experience"
risk_assessment: "Public post visible to all connections"
rollback_plan: "Delete post from LinkedIn manually"
sensitivity: medium
---

# Post Content

Your LinkedIn post text goes here. This is what will be posted.

Supports multiple paragraphs.

#hashtags #work #great
```

### Posting Process

```bash
# Check for approved posts and publish them
uv run python backend/actions/linkedin_poster.py --once

# Continuous polling (checks every 5 minutes)
uv run python backend/actions/linkedin_poster.py
```

The poster:
1. Scans `vault/Approved/` for files with `type: linkedin_post`
2. Opens LinkedIn feed
3. Clicks "Start a post"
4. Types the post body content
5. Clicks "Post"
6. Moves the file to `vault/Done/` with `completed_at` and `result` fields
7. Logs the action to `vault/Logs/actions/`

### DEV_MODE / DRY_RUN Behavior

When `DEV_MODE=true`:
- **Watcher**: LinkedIn is monitored normally, action files created
- **Poster**: Post content is logged but NOT actually posted to LinkedIn

When `DRY_RUN=true`:
- **Watcher**: Notifications detected and logged, no action files created
- **Poster**: Post files detected and logged, no posting or file moves

## Error Handling

### Common LinkedIn Issues

| Error | Cause | Resolution |
|-------|-------|------------|
| Login page shown | Session expired | Run `--setup` to re-login |
| CAPTCHA challenge | LinkedIn security | Run `--setup` in headed mode |
| "Start a post" not found | LinkedIn UI change | Update selectors |
| Rate limit | Too many actions | Increase check interval |
| Post failed | Network or UI issue | File stays in Approved, retry next cycle |

### Error Logging

All errors logged to `vault/Logs/errors/{date}.json`.

## Watcher Operations

### Setup

```bash
uv run python backend/watchers/linkedin_watcher.py --setup
```

### Start Watcher

```bash
uv run python backend/watchers/linkedin_watcher.py          # continuous
uv run python backend/watchers/linkedin_watcher.py --once    # single check
```

### Start Poster

```bash
uv run python backend/actions/linkedin_poster.py             # continuous
uv run python backend/actions/linkedin_poster.py --once      # single check
```

## Constraints

- **HITL REQUIRED**: Posts MUST be in /Approved folder (human-approved)
- **NEVER auto-post**: The poster never creates post content, only publishes approved content
- **READ-ONLY watcher**: Watcher MUST NOT interact with notifications, only observe
- **LOCAL ONLY**: All data stays on the local machine
- **RATE LIMITS**: Minimum 5-minute check interval for watcher, max 5 posts/day
- **LOGGING**: Every post is logged with full audit trail

## Troubleshooting

### "Session expired"

```bash
uv run python backend/watchers/linkedin_watcher.py --setup
```

### "No notifications detected"

1. Check keyword filter in `config/.env`
2. Open LinkedIn manually — do you have notifications?
3. Check `vault/Logs/processed_linkedin.json` for already-processed items

### "Post not publishing"

1. Check `DEV_MODE` setting — must be `false` for real posts
2. Check `DRY_RUN` setting
3. Verify file is in `vault/Approved/` (not Pending_Approval)
4. Check frontmatter has `type: linkedin_post`
5. Check `vault/Logs/errors/` for details
