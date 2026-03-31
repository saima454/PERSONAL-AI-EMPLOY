# Quickstart: Twitter (X) Integration

**Feature**: 005-twitter-x-integration
**Date**: 2026-02-21

---

## Prerequisites

1. Playwright installed (already present from Feature 004)
2. `config/.env` updated with Twitter env vars
3. Current working directory: repo root

---

## Scenario 1: First-Time Session Setup (US1)

### Steps

```bash
# 1. Copy env template (if not already done)
cp config/.env.example config/.env

# 2. Edit config/.env and set:
# TWITTER_SESSION_PATH=config/twitter_session
# TWITTER_HEADLESS=false

# 3. Run setup (opens headed browser)
uv run python backend/watchers/twitter_watcher.py --setup
```

### Expected behavior

- Browser opens at `https://x.com/home`
- If already logged in: displays "Already logged in!" message, saves session, exits
- If not logged in: shows interactive prompt — log in manually in the browser window, then press Enter
- Terminal displays: `"Twitter session saved to config/twitter_session"`
- Directory `config/twitter_session/` is created with browser state files

### Verify

```bash
ls config/twitter_session/   # Should contain Chromium profile files
uv run python backend/watchers/twitter_watcher.py --once  # Should NOT show login prompt
```

---

## Scenario 2: Twitter Notification Monitoring (US2 — DEV_MODE)

### Steps

```bash
# Ensure DEV_MODE=true in config/.env
uv run python backend/watchers/twitter_watcher.py --once
```

### Expected behavior

```
INFO: [DEV_MODE] TwitterWatcher: returning synthetic item
INFO: Created action file: TWITTER_[DEV_MODE]_20260221_120000.md (priority: low)
INFO: Check complete. Found 1 matching items.
```

### Verify

```bash
ls vault/Needs_Action/TWITTER_*.md
# One file should exist
cat vault/Needs_Action/TWITTER_*.md
# Should show type: twitter, sender: "[DEV_MODE]", preview: "[DEV_MODE] Synthetic..."
```

---

## Scenario 3: Twitter Notification Monitoring (US2 — Real Mode)

### Steps

```bash
# Set DEV_MODE=false, DRY_RUN=false in config/.env
# Set TWITTER_KEYWORDS=urgent,help,project
uv run python backend/watchers/twitter_watcher.py --once
```

### Expected behavior

- Browser launches using `config/twitter_session/`
- Navigates to `https://x.com/notifications`
- Scans up to 20 notification items
- Creates action files for items matching TWITTER_KEYWORDS
- Navigates to `https://x.com/messages`
- Scans up to 15 DM threads
- Exits cleanly

### What success looks like

```
INFO: Starting TwitterWatcher (interval: 300s, dev_mode: False)
INFO: Scanning Twitter notifications...
INFO: Found N notification elements
INFO: Matched Twitter notification: sender='@user', keyword='project'
INFO: Created action file: TWITTER_user_20260221_120000.md (priority: low)
```

---

## Scenario 4: Approve and Post a Tweet (US3 — DEV_MODE)

### Steps

```bash
# 1. Create an approved post file manually (or use content scheduler output)
cat > vault/Approved/TWITTER_POST_2026-02-21.md << 'EOF'
---
type: twitter_post
platform: twitter
status: approved
topic: AI and Automation
topic_index: 0
template_id: twitter_ai_01
generated_at: '2026-02-21T09:00:00+05:00'
scheduled_date: '2026-02-21'
character_count: 247
---
# Post Content

Hot take: The best AI agent asks permission before acting. 🤖

Every action in my AI Employee requires human approval. Slower? Yes. Trustworthy? Absolutely.

What's your HITL strategy?

#AIAgents #BuildInPublic
EOF

# 2. Run poster in DEV_MODE
DEV_MODE=true uv run python backend/actions/twitter_poster.py --once
```

### Expected behavior

```
INFO: Processing Twitter post: TWITTER_POST_2026-02-21.md
INFO: [DEV_MODE] Would post to Twitter: Hot take: The best AI agent...
INFO: File moved to vault/Done/TWITTER_POST_2026-02-21.md
INFO: Twitter poster: processed 1 posts
```

### Verify

```bash
ls vault/Done/TWITTER_POST_2026-02-21.md    # File should exist
grep "status" vault/Done/TWITTER_POST_2026-02-21.md
# Should show: status: done
grep "dev_mode" vault/Done/TWITTER_POST_2026-02-21.md
# Should show: dev_mode: true
```

---

## Scenario 5: Tweet Rejected (Character Limit Exceeded — US3)

### Steps

```bash
# Create a post that's too long (>280 chars)
python3 -c "
content = 'A' * 281
print(f'---\ntype: twitter_post\nplatform: twitter\nstatus: approved\ncharacter_count: 281\n---\n# Post Content\n\n{content}')
" > vault/Approved/TWITTER_POST_TOOLONG.md

uv run python backend/actions/twitter_poster.py --once
```

### Expected behavior

```
WARNING: Twitter post validation failed (exceeds_character_limit): TWITTER_POST_TOOLONG.md
INFO: File moved to vault/Rejected/TWITTER_POST_TOOLONG.md
```

### Verify

```bash
cat vault/Rejected/TWITTER_POST_TOOLONG.md | grep rejection_reason
# Should show: rejection_reason: exceeds_character_limit
```

---

## Scenario 6: Content Scheduler Generates Twitter Draft (US4)

### Steps

```bash
# 1. Add Twitter topic to Content_Strategy.md
# Edit vault/Content_Strategy.md and add:
# 6. Hackathon Journey [platform: twitter] - Quick Twitter updates from the hackathon

# 2. Run content scheduler
uv run python -m backend.scheduler.content_scheduler --generate-now
```

### Expected behavior

```
INFO: ContentScheduler: generated TWITTER_POST_2026-02-21.md (247 chars, platform: twitter)
INFO: Draft saved to vault/Pending_Approval/TWITTER_POST_2026-02-21.md
```

### Verify

```bash
cat vault/Pending_Approval/TWITTER_POST_2026-02-21.md
# Should show: type: twitter_post, platform: twitter, character_count: <= 280
wc -c vault/Pending_Approval/TWITTER_POST_2026-02-21.md | head -1
# character_count field value should be <= 280
```

---

## Scenario 7: Full HITL Loop (US1 → US4 → US3)

This is the end-to-end integration test. Assumes session is set up and DEV_MODE=true.

```bash
# 1. Add Twitter topic to Content_Strategy.md (done in Scenario 6)
# 2. Start orchestrator
uv run python -m backend.orchestrator.orchestrator
```

In Obsidian:
1. Open `vault/Pending_Approval/TWITTER_POST_2026-02-21.md`
2. Change `status: pending_approval` → `status: approved`
3. Move file to `vault/Approved/` folder

Orchestrator detects the approved file and runs TwitterPoster:
```
INFO: Action executor: processing file TWITTER_POST_2026-02-21.md (type: twitter_post)
INFO: [DEV_MODE] Would post to Twitter: ...
INFO: File moved to vault/Done/TWITTER_POST_2026-02-21.md
```

---

## Environment Variables Reference

```bash
# Required for Twitter integration
TWITTER_CHECK_INTERVAL=300         # Seconds between watcher polls (default: 300)
TWITTER_KEYWORDS=urgent,help,project,collab,opportunity,mention  # Comma-separated, case-insensitive
TWITTER_SESSION_PATH=config/twitter_session  # Browser session directory
TWITTER_HEADLESS=false             # false for setup; true for production headless

# Global flags (affect all modules)
DEV_MODE=true                      # true = no real tweets posted
DRY_RUN=false                      # true = no vault files written
```

---

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Twitter session not found" | Session directory missing | Run `--setup` first |
| "Session state: login_required" | Session expired | Re-run `--setup` |
| "exceeds_character_limit" rejection | Draft > 280 chars | Edit draft to ≤ 280 chars and re-approve |
| No notifications found | No keyword matches | Adjust TWITTER_KEYWORDS; check if notifications exist on x.com |
| Browser opens even in DEV_MODE | `DEV_MODE` env var not set | Set `DEV_MODE=true` in `config/.env` |
