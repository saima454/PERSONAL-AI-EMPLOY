---
name: whatsapp-watcher
version: 1.0.0
description: |
  PERCEPTION layer skill for monitoring WhatsApp Web via Playwright browser automation.
  Polls for unread messages matching configurable keywords and creates action files
  in the vault for Claude Code to process.

  TRIGGERS: Use this skill when you need to:
  - Set up WhatsApp Web monitoring ("setup whatsapp", "configure whatsapp")
  - Check WhatsApp status ("check whatsapp", "any new whatsapp messages")
  - Understand message filtering ("what whatsapp messages are monitored")
  - Debug WhatsApp watcher issues ("whatsapp watcher not working")

  NOTE: This skill documents the whatsapp_watcher Python script behavior.
  The actual watcher runs as a background process, not invoked directly.
dependencies:
  - vault-manager
permissions:
  - read: whatsapp web (via Playwright browser automation)
  - write: vault/Needs_Action/*.md
  - write: vault/Logs/**/*.json
sensitivity: high
---

# WhatsApp Watcher Skill

Monitor WhatsApp Web for important messages and create action files in the vault. This is a PERCEPTION layer component - it observes and writes, never sends messages or modifies conversations.

## Architecture Role

```
┌─────────────────────────────────────────────────────────────────┐
│                    PERCEPTION LAYER                             │
│                                                                 │
│  whatsapp_watcher.py ──────► vault/Needs_Action/WHATSAPP_*.md  │
│        │                                                        │
│        └──────────────────► vault/Logs/actions/*.json           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    REASONING LAYER                              │
│                                                                 │
│  Claude Code reads action files, creates plans, requests HITL   │
└─────────────────────────────────────────────────────────────────┘
```

## Privacy Notice

All messages are processed locally. No message content is sent to external services.
WhatsApp Web runs in a local Playwright browser instance. Session data is stored
in `config/whatsapp_session/` on your machine only.

## Setup Instructions

### Step 1: Install Playwright Browsers

```bash
uv run playwright install chromium
```

### Step 2: Configure Environment Variables

Edit your `.env` file:

```bash
# WhatsApp Configuration
WHATSAPP_CHECK_INTERVAL=30
WHATSAPP_KEYWORDS=urgent,asap,help,deadline,invoice,payment,meeting,important
WHATSAPP_SESSION_PATH=config/whatsapp_session
WHATSAPP_HEADLESS=false
```

### Step 3: First-Time QR Code Login

The first run MUST use headed mode (visible browser) so you can scan the QR code:

```bash
# First run - opens visible browser for QR code scan
uv run python backend/watchers/whatsapp_watcher.py --setup
```

**Process:**
1. Chromium browser opens showing WhatsApp Web
2. Open WhatsApp on your phone
3. Go to Settings > Linked Devices > Link a Device
4. Scan the QR code displayed in the browser
5. Wait for WhatsApp Web to fully load (chats visible)
6. Press Enter in the terminal to confirm login
7. Session is saved to `config/whatsapp_session/`

### Step 4: Start Monitoring

After initial setup, the watcher can run headless:

```bash
# Set headless mode in .env
WHATSAPP_HEADLESS=true

# Start watcher
uv run python backend/watchers/whatsapp_watcher.py
```

## Message Filtering

### Keyword Matching

Messages are filtered by configurable keywords. Only messages containing at least
one keyword generate action files.

**Default Keywords:** urgent, asap, help, deadline, invoice, payment, meeting, important

Configure via `WHATSAPP_KEYWORDS` in `.env` (comma-separated).

### Priority Classification

| Priority | Keywords |
|----------|----------|
| HIGH | urgent, asap, critical, payment, invoice |
| MEDIUM | important, meeting, deadline, help |
| LOW | (other matched keywords) |

## Action File Format

### File Location

`vault/Needs_Action/WHATSAPP_{sender}_{timestamp}.md`

Example: `WHATSAPP_John-Smith_20260211T091500.md`

### Frontmatter Schema

```yaml
---
type: whatsapp
id: WHATSAPP_a1b2c3d4_20260211T091500
source: whatsapp_watcher
sender: John Smith
message_preview: "Can you send the invoice ASAP?"
received: 2026-02-11T09:15:00Z
priority: high
status: pending
chat_name: John Smith
---
```

### Body Template

```markdown
## WhatsApp Message

**From:** {sender}
**Chat:** {chat_name}
**Time:** {timestamp}
**Priority:** {priority} (keyword: {matched_keyword})

## Recent Messages (Context)

- [09:13] John Smith: Hey, about the project...
- [09:14] John Smith: We need to finalize the budget
- [09:15] John Smith: Can you send the invoice ASAP?

## Suggested Actions

- [ ] Reply to sender
- [ ] Forward info to relevant party
- [ ] Mark as processed
```

## Duplicate Prevention

### Processed Messages Tracking

Location: `vault/Logs/processed_whatsapp.json`

```json
{
  "processed_ids": {
    "John Smith|Can you send the invoice ASAP?|2026-02-11T09:15:00Z": "2026-02-11T09:16:00Z"
  },
  "last_cleanup": "2026-02-11T00:00:00Z"
}
```

### Deduplication Logic

```
1. Detect unread chat indicators on WhatsApp Web
2. For each unread chat:
   a. Extract sender name and recent messages
   b. Generate dedup key from sender + message text + timestamp
   c. Check if key in processed_ids
   d. If YES → Skip (already processed)
   e. If NO → Check keyword match → Create action file if matched
3. Clean up IDs older than 7 days
```

## Error Handling

### Common WhatsApp Web Issues

| Error | Cause | Resolution |
|-------|-------|------------|
| QR code timeout | Session not set up | Run `--setup` in headed mode |
| "Phone not connected" | Phone offline/disconnected | Alert in logs, retry next cycle |
| Session expired | WhatsApp logged out | Alert human, re-run `--setup` |
| Element not found | WhatsApp Web UI changed | Check selector updates |
| Browser crash | Memory/resource issue | Auto-restart on next cycle |

### Retry Policy

```python
RETRY_CONFIG = {
    "max_retries": 3,
    "initial_delay_seconds": 5,
    "max_delay_seconds": 60,
    "exponential_base": 2,
}
```

### Error Logging

All errors logged to `vault/Logs/errors/{date}.json`:

```json
{
  "timestamp": "2026-02-11T09:16:00Z",
  "correlation_id": "uuid",
  "actor": "whatsapp_watcher",
  "action_type": "error",
  "target": "whatsapp_web",
  "error": "session_expired",
  "details": {
    "consecutive_errors": 1,
    "dev_mode": true
  },
  "result": "failure"
}
```

## Watcher Operations

### Setup (First Time)

```bash
uv run python backend/watchers/whatsapp_watcher.py --setup
```

### Start Watcher

```bash
# Foreground (for testing)
uv run python backend/watchers/whatsapp_watcher.py

# Single check
uv run python backend/watchers/whatsapp_watcher.py --once

# Background
uv run python backend/watchers/whatsapp_watcher.py &
```

### Stop Watcher

```bash
pkill -f whatsapp_watcher.py
```

### Check Status

```bash
pgrep -f whatsapp_watcher.py
```

## DEV_MODE Behavior

When `DEV_MODE=true`:
- WhatsApp Web is still monitored (read-only)
- Action files are created normally
- Messages are NOT marked as read
- Log entries include `"dev_mode": true`

When `DRY_RUN=true`:
- Messages are detected and logged but no action files are created
- Useful for testing keyword filters

## Session Management

### Session Storage

WhatsApp Web session is persisted via Playwright's persistent browser context:
- Location: `config/whatsapp_session/` (configurable via `WHATSAPP_SESSION_PATH`)
- Contains browser cookies and local storage
- Survives watcher restarts without re-scanning QR code

### Session Expiry

WhatsApp Web sessions can expire if:
- Phone is offline for extended period (>14 days)
- User logs out from phone
- "Linked Devices" is cleared on phone

The watcher detects expiry by checking for the QR code page or
"Phone not connected" alerts and logs appropriately.

## Constraints

- **READ ONLY**: Watcher MUST NOT send messages, only read
- **NO MODIFICATIONS**: Watcher MUST NOT modify/delete conversations
- **VAULT WRITES ONLY**: All output goes to vault/Needs_Action or vault/Logs
- **LOCAL ONLY**: All data stays on the local machine
- **RATE LIMITS**: Check interval minimum 15 seconds to avoid WhatsApp detection
- **PRIVACY**: Message content stored locally only, never transmitted externally

## Troubleshooting

### "QR code not appearing"

```bash
# Re-run setup with headed browser
WHATSAPP_HEADLESS=false uv run python backend/watchers/whatsapp_watcher.py --setup
```

### "Session keeps expiring"

1. Ensure phone has stable internet connection
2. Check WhatsApp app is updated
3. Re-link device: Phone > Settings > Linked Devices

### "No messages being detected"

1. Check keyword filter in `.env` (`WHATSAPP_KEYWORDS`)
2. Verify messages are actually unread in WhatsApp Web
3. Check `vault/Logs/processed_whatsapp.json` for already-processed messages
4. Review selector compatibility in `skills/whatsapp-watcher/references/whatsapp_web_selectors.md`

### "Action files not appearing"

1. Check `DRY_RUN` setting in `.env`
2. Check `vault/Logs/errors/` for errors
3. Verify vault path in `.env`
