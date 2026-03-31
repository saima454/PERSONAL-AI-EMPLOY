# Quickstart & Integration Scenarios: Meta Social Integration (004)

**Date**: 2026-02-21
**Feature**: 004-meta-social-integration

---

## Prerequisites

```bash
# Install dependencies (tzdata already added in feature 003)
uv sync

# Configure environment
cp config/.env.example config/.env
# Edit config/.env and set:
#   FACEBOOK_CHECK_INTERVAL=120
#   FACEBOOK_KEYWORDS=urgent,invoice,meeting
#   FACEBOOK_HEADLESS=false   # false for first-time setup
#   INSTAGRAM_CHECK_INTERVAL=60
#   INSTAGRAM_KEYWORDS=urgent,collab,invoice
#   INSTAGRAM_HEADLESS=false  # false for first-time setup
#   DEV_MODE=true             # always start in dev mode
```

---

## Scenario 1: One-Time Meta Session Setup

**Goal**: Establish a single Meta session covering both Facebook and Instagram.

```bash
# Step 1: Facebook setup (headed browser)
uv run python backend/watchers/facebook_watcher.py --setup

# Browser opens facebook.com → log in manually
# Then navigate to instagram.com in same browser → log in (or "Continue with Facebook")
# Press Enter in terminal when both are logged in
# Session saved to config/meta_session/

# Verify session was saved
ls config/meta_session/   # should contain Chromium profile files
```

**Expected log output**:
```
INFO Starting Meta session setup (headed mode)...
INFO Initial session state: login_required
INFO Please log in to Facebook and Instagram, then press Enter...
INFO User confirmed. Verifying session...
INFO Facebook authenticated. Verifying Instagram...
INFO Meta session saved to config/meta_session/
INFO Setup complete!
```

---

## Scenario 2: Facebook Watcher — DEV_MODE Single Check

**Goal**: Verify watcher runs without errors in DEV_MODE.

```bash
DEV_MODE=true uv run python backend/watchers/facebook_watcher.py --once
```

**Expected log output**:
```
INFO [DEV_MODE] FacebookWatcher: skipping real browser — returning synthetic item
INFO [DEV_MODE] Would create: FACEBOOK_dev_mode_20260221_090000.md (priority: low, from: [DEV_MODE])
INFO Check complete. Found 1 matching items.
```

**Expected vault effect**: No file created (dry_run implied by DEV_MODE=true).

---

## Scenario 3: Instagram Watcher — DEV_MODE Single Check

```bash
DEV_MODE=true uv run python backend/watchers/instagram_watcher.py --once
```

**Expected**: Same as Scenario 2 but with `INSTAGRAM_` prefix and `platform: instagram`.

---

## Scenario 4: Full Facebook Monitoring Cycle (with live session)

**Goal**: Real Facebook notification captured and vaulted.

```bash
# Set DEV_MODE=false and ensure session exists
DEV_MODE=false FACEBOOK_HEADLESS=true uv run python backend/watchers/facebook_watcher.py --once
```

**Expected vault file** (`vault/Needs_Action/FACEBOOK_john_doe_20260221_090000.md`):
```markdown
---
type: facebook
id: FACEBOOK_abc1234_20260221_090000
source: facebook_watcher
item_type: notification
sender: John Doe
preview: "Commented on your post: Great content about AI..."
received: "2026-02-21T09:00:00Z"
priority: medium
status: pending
matched_keyword: meeting
---

## Facebook Notification

**From:** John Doe
**Type:** notification
**Time:** 2 hours ago
**Priority:** medium (keyword: meeting)

## Content

Commented on your post: Great content about AI...

## Suggested Actions

- [ ] Review on Facebook
- [ ] Reply if needed
- [ ] Mark as processed
```

---

## Scenario 5: Content Scheduler — Generate Facebook Draft

**Goal**: Content Scheduler generates a `facebook_post` draft.

**Prerequisites**: Add a Facebook topic to `vault/Content_Strategy.md`:
```yaml
topics:
  - name: "Behind the Scenes"
    platform: facebook
    template: "casual"
    frequency: weekly
```

```bash
uv run python -m backend.scheduler.content_scheduler --generate-now
```

**Expected vault file** (`vault/Pending_Approval/FACEBOOK_POST_2026-02-21.md`):
```markdown
---
type: facebook_post
status: pending_approval
platform: facebook
topic: behind-the-scenes
character_count: 487
generated_at: "2026-02-21T09:00:00Z"
---

Behind the Scenes at our AI Employee project...

[generated post body]
```

---

## Scenario 6: Facebook Auto-Post — DEV_MODE (End-to-End HITL)

**Goal**: Verify the full HITL publish loop works in DEV_MODE.

```bash
# Step 1: Place a test approval file
cat > vault/Approved/FACEBOOK_POST_test.md << 'EOF'
---
type: facebook_post
status: approved
platform: facebook
character_count: 50
---

Test Facebook post from AI Employee.
EOF

# Step 2: Start orchestrator (DEV_MODE=true)
DEV_MODE=true uv run python main.py
```

**Expected log output**:
```
INFO Processing: FACEBOOK_POST_test.md (type=facebook_post)
INFO [DEV_MODE] Would post to Facebook: "Test Facebook post from AI Employee."
INFO Moved to Done: FACEBOOK_POST_test.md
```

**Expected vault state**: `vault/Done/FACEBOOK_POST_test.md` with `status: done`.

---

## Scenario 7: Instagram Auto-Post — Character Limit Validation

**Goal**: Verify that an over-limit caption is rejected, not published.

```bash
# Create a draft exceeding 2200 chars
python -c "
from pathlib import Path
long_text = 'A' * 2300
content = f'''---
type: instagram_post
status: approved
platform: instagram
character_count: 2300
---

{long_text}
'''
Path('vault/Approved/INSTAGRAM_POST_oversize.md').write_text(content, encoding='utf-8')
print('Created oversize test file')
"

DEV_MODE=false uv run python main.py
```

**Expected log output**:
```
WARNING Instagram post caption exceeds 2200 character limit (2300 chars): INSTAGRAM_POST_oversize.md
INFO Moved to Rejected: INSTAGRAM_POST_oversize.md
```

**Expected vault state**: `vault/Rejected/INSTAGRAM_POST_oversize.md` with `rejection_reason: character_count_exceeded`.

---

## Scenario 8: Session Expiry Graceful Degradation

**Goal**: Verify that an expired session is detected and skipped without crashing.

**Simulated**: Delete `config/meta_session/` directory.

```bash
rm -rf config/meta_session/
DEV_MODE=false uv run python backend/watchers/facebook_watcher.py --once
```

**Expected log output**:
```
WARNING Meta session not found at config/meta_session/ — run --setup to initialize
INFO FacebookWatcher: skipping cycle (no session)
INFO Check complete. Found 0 matching items.
```

**Expected**: No crash, no vault files created.

---

## Scenario 9: Running Full Test Suite

```bash
uv run pytest tests/test_meta_social.py -v
```

**Expected**: All tests pass. Key test classes:
- `TestMetaSessionSetup` — session detection and expiry handling
- `TestFacebookWatcher` — notification capture, dedup, DEV_MODE
- `TestInstagramWatcher` — notification capture, dedup, DEV_MODE
- `TestFacebookPoster` — post publishing, validation, lifecycle
- `TestInstagramPoster` — post publishing, character limit validation
- `TestContentSchedulerPlatformExtension` — platform routing in PostGenerator
- `TestActionExecutorRouting` — facebook_post and instagram_post dispatch

---

## Scenario 10: Checking --status After Setup

```bash
uv run python backend/watchers/facebook_watcher.py --status
```

**Expected output**:
```
Meta Session Status
═══════════════════
Session path:  config/meta_session/        ✓ EXISTS
Facebook:      ✓ AUTHENTICATED
Instagram:     ✓ AUTHENTICATED
Last checked:  2026-02-21T09:00:00Z
```
