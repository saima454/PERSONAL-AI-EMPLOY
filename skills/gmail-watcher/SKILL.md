---
name: gmail-watcher
version: 1.0.0
description: |
  PERCEPTION layer skill for monitoring Gmail inbox. Polls for unread important
  emails and creates action files in the vault for Claude Code to process.

  TRIGGERS: Use this skill when you need to:
  - Set up Gmail API credentials ("setup gmail", "configure email")
  - Check email status ("check emails", "any new emails")
  - Understand email filtering ("what emails are monitored")
  - Debug email watcher issues ("email watcher not working")

  NOTE: This skill documents the gmail_watcher Python script behavior.
  The actual watcher runs as a background process, not invoked directly.
dependencies:
  - vault-manager
permissions:
  - read: gmail (via API)
  - write: vault/Inbox/*.md
  - write: vault/Needs_Action/*.md
  - write: vault/Logs/**/*.json
sensitivity: medium
---

# Gmail Watcher Skill

Monitor Gmail for important emails and create action files in the vault. This is a PERCEPTION layer component - it observes and writes, never executes actions.

## Architecture Role

```
┌─────────────────────────────────────────────────────────────────┐
│                    PERCEPTION LAYER                             │
│                                                                 │
│  gmail_watcher.py ──────► vault/Needs_Action/email-*.md        │
│        │                                                        │
│        └──────────────────► vault/Logs/actions/*.json          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    REASONING LAYER                              │
│                                                                 │
│  Claude Code reads action files, creates plans, requests HITL   │
└─────────────────────────────────────────────────────────────────┘
```

## Setup Instructions

### Step 1: Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable the **Gmail API**:
   - Navigate to "APIs & Services" → "Library"
   - Search for "Gmail API"
   - Click "Enable"

### Step 2: Create OAuth 2.0 Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. If prompted, configure OAuth consent screen:
   - User Type: External (or Internal for Workspace)
   - App name: "AI Employee Gmail Watcher"
   - Scopes: Add `gmail.readonly` and `gmail.modify`
4. Application type: **Desktop app**
5. Download the credentials JSON file
6. Save as `config/credentials.json`

### Step 3: Configure Environment Variables

Edit your `.env` file:

```bash
# Gmail Configuration
GMAIL_CLIENT_ID=your_client_id.apps.googleusercontent.com
GMAIL_CLIENT_SECRET=your_client_secret
GMAIL_TOKEN_PATH=./config/gmail_token.json
GMAIL_USER_EMAIL=your.email@gmail.com

# Watcher Configuration
GMAIL_POLL_INTERVAL_SECONDS=120
GMAIL_MAX_RESULTS=10
```

### Step 4: First-Time Authentication

Run the watcher once to complete OAuth flow:

```bash
uv run python backend/watchers/gmail_watcher.py --auth-only
```

This opens a browser for Google login. After approval, the token is saved to `GMAIL_TOKEN_PATH`.

## Email Filtering

### Default Query

```
is:unread (is:important OR subject:(urgent OR invoice OR payment OR asap OR help))
```

### Priority Keywords

| Priority | Keywords |
|----------|----------|
| HIGH | urgent, asap, immediate, critical, payment, invoice |
| MEDIUM | important, request, review, deadline |
| LOW | (default for unmatched) |

### Configurable Filters

In `config/gmail_config.json`:

```json
{
  "query": "is:unread is:important",
  "priority_keywords": {
    "high": ["urgent", "asap", "payment", "invoice", "critical"],
    "medium": ["important", "request", "review", "deadline"],
    "low": []
  },
  "exclude_senders": [
    "noreply@",
    "newsletter@",
    "notifications@"
  ],
  "max_results": 10,
  "poll_interval_seconds": 120
}
```

## Action File Format

When an email matches, the watcher creates an action file:

### File Location

`vault/Needs_Action/email-{short_subject}-{timestamp}.md`

Example: `email-contract-review-request-20250204T091600.md`

### Frontmatter Schema

```yaml
---
type: email
source: gmail_watcher
message_id: "18d5a2b3c4e5f6g7"
thread_id: "18d5a2b3c4e5f6g7"
from: sender@example.com
to: your.email@gmail.com
subject: "Contract Review Request"
received: 2025-02-04T09:15:00Z
created: 2025-02-04T09:16:00Z
priority: high
status: needs_action
labels: [INBOX, IMPORTANT, UNREAD]
tags: [contract, client]
---
```

### Body Template

```markdown
# Email: {subject}

## Summary

From: {from}
Date: {received}
Priority: {priority}

## Content

{email_body_or_snippet}

## Suggested Actions

- [ ] Review email content
- [ ] Determine if response needed
- [ ] Create plan if action required
- [ ] Archive if no action needed

## Raw Headers

- Message-ID: {message_id}
- Thread-ID: {thread_id}
- Labels: {labels}
```

## Duplicate Prevention

### Processed Emails Tracking

Location: `vault/Logs/gmail_processed.json`

```json
{
  "last_updated": "2025-02-04T09:16:00Z",
  "processed_ids": {
    "18d5a2b3c4e5f6g7": {
      "processed_at": "2025-02-04T09:16:00Z",
      "action_file": "email-contract-review-20250204T091600.md"
    }
  }
}
```

### Deduplication Logic

```
1. Fetch unread emails from Gmail API
2. For each email:
   a. Check if message_id in processed_ids
   b. If YES → Skip (already processed)
   c. If NO → Create action file, add to processed_ids
3. Clean up IDs older than 30 days
```

## Error Handling

### Authentication Errors

| Error | Cause | Resolution |
|-------|-------|------------|
| `invalid_grant` | Token expired/revoked | Delete token file, re-authenticate |
| `access_denied` | Scopes not approved | Re-run OAuth consent flow |
| `quota_exceeded` | API rate limit | Exponential backoff, wait 1 hour |

### Retry Policy

```python
RETRY_CONFIG = {
    "max_retries": 3,
    "initial_delay_seconds": 5,
    "max_delay_seconds": 300,
    "exponential_base": 2,
    "retryable_errors": [
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "backendError",
        "internalError"
    ]
}
```

### Error Logging

All errors logged to `vault/Logs/errors/{date}.json`:

```json
{
  "timestamp": "2025-02-04T09:16:00Z",
  "correlation_id": "uuid",
  "actor": "gmail_watcher",
  "action_type": "error",
  "target": "gmail_api",
  "error": "rateLimitExceeded",
  "details": {
    "retry_count": 2,
    "next_retry_seconds": 20
  },
  "result": "failure"
}
```

## Watcher Operations

### Start Watcher

```bash
# Foreground (for testing)
uv run python backend/watchers/gmail_watcher.py

# Background (production)
uv run python backend/watchers/gmail_watcher.py &

# With PM2 (recommended)
pm2 start backend/watchers/gmail_watcher.py --name gmail-watcher --interpreter python
```

### Stop Watcher

```bash
# If running in background
pkill -f gmail_watcher.py

# With PM2
pm2 stop gmail-watcher
```

### Check Status

```bash
# Check if running
pgrep -f gmail_watcher.py

# View recent logs
tail -f vault/Logs/actions/$(date +%Y-%m-%d).json
```

### Manual Check (One-Time)

```bash
uv run python backend/watchers/gmail_watcher.py --once
```

## DEV_MODE Behavior

When `DEV_MODE=true`:
- Gmail API is still called (read-only)
- Action files are created normally
- Emails are NOT marked as read
- Log entries include `"dev_mode": true`

## Monitoring & Alerts

### Health Check

The watcher updates `vault/Dashboard.md` system status:

```markdown
| Component | Status | Last Check |
|-----------|--------|------------|
| Gmail Watcher | Running | 2025-02-04T09:16:00Z |
```

### Alert Conditions

| Condition | Alert Level | Action |
|-----------|-------------|--------|
| Watcher not checked in 10 min | Warning | Dashboard alert |
| Authentication failure | Critical | Dashboard alert + stop watcher |
| 3+ consecutive API errors | Warning | Dashboard alert |
| Rate limit exceeded | Info | Log only |

## Examples

### Example 1: Email Creates Action File

**Gmail receives:**
- From: john.client@company.com
- Subject: "URGENT: Contract needs review by EOD"
- Date: 2025-02-04 09:15 UTC

**Watcher creates:** `vault/Needs_Action/email-urgent-contract-needs-review-20250204T091600.md`

```yaml
---
type: email
source: gmail_watcher
message_id: "18d5a2b3c4e5f6g7"
from: john.client@company.com
subject: "URGENT: Contract needs review by EOD"
received: 2025-02-04T09:15:00Z
created: 2025-02-04T09:16:00Z
priority: high
status: needs_action
tags: [urgent, contract, client]
---

# Email: URGENT: Contract needs review by EOD

## Summary

From: john.client@company.com
Date: 2025-02-04T09:15:00Z
Priority: HIGH (keyword: urgent)

## Content

Hi,

Please review the attached contract and provide feedback by end of day.
This is urgent as the client needs to sign tomorrow.

Thanks,
John

## Suggested Actions

- [ ] Review email content
- [ ] Download and review contract attachment
- [ ] Create plan for response
- [ ] Set deadline reminder
```

### Example 2: Duplicate Skipped

**Watcher poll #1:** Creates action file for message_id "abc123"
**Watcher poll #2:** Sees same message_id "abc123" → Skips (already in processed_ids)

### Example 3: Error Recovery

```
Poll #1: API returns "rateLimitExceeded"
         → Log error, wait 5 seconds
Poll #1 retry: API returns "rateLimitExceeded"
         → Log error, wait 10 seconds
Poll #1 retry: Success
         → Process emails normally
```

## Constraints

- **READ ONLY**: Watcher MUST NOT send emails, only read
- **NO MODIFICATIONS**: Watcher MUST NOT modify/delete emails in Gmail
- **VAULT WRITES ONLY**: All output goes to vault/Needs_Action or vault/Logs
- **RATE LIMITS**: Respect Gmail API quotas (250 units/user/second)
- **PRIVACY**: Never log full email bodies, only snippets

## Troubleshooting

### "Token file not found"

```bash
# Re-authenticate
uv run python backend/watchers/gmail_watcher.py --auth-only
```

### "No emails being detected"

1. Check query filter in config
2. Verify email matches `is:unread` and priority criteria
3. Check `vault/Logs/gmail_processed.json` for already-processed IDs

### "Action files not appearing"

1. Check `vault/Logs/errors/` for API errors
2. Verify vault path in `.env`
3. Check file permissions on vault directory

### "Rate limit errors"

Gmail API has quotas. If exceeded:
1. Increase `poll_interval_seconds`
2. Reduce `max_results`
3. Wait 1 hour for quota reset
