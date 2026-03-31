---
name: email-sender
version: 1.0.0
description: |
  ACTION layer skill for sending, drafting, searching, and replying to emails
  via Gmail. Operates as an MCP server communicating over stdio transport.

  TRIGGERS: Use this skill when you need to:
  - Search emails ("find emails about invoices", "search Gmail for messages from John")
  - Draft emails ("draft a reply to the meeting invite", "compose an email to Jane")
  - Send emails ("send the approved email", "email John about the proposal")
  - Reply to threads ("reply to that thread", "respond to the latest email")

  NOTE: send_email and reply_email require HITL approval files in vault/Approved/.
  draft_email and search_email do not require approval.
dependencies:
  - vault-manager
permissions:
  - read: gmail (via API, gmail.readonly scope)
  - write: gmail (via API, gmail.modify + gmail.send scopes)
  - read: vault/Approved/*.md
  - write: vault/Done/*.md
  - write: vault/Logs/actions/*.json
sensitivity: high
rate_limits:
  email_sends: 10/hour
---

# Email Sender Skill

Send, draft, search, and reply to emails via Gmail through the Email MCP Server. This is an ACTION layer component — it executes approved actions only.

## Architecture Role

```
┌─────────────────────────────────────────────────────────────────┐
│                    ACTION LAYER                                  │
│                                                                  │
│  email_server.py (MCP) ◄──── Claude Code (stdio JSON-RPC)      │
│        │                                                         │
│        ├── search_email ──► Gmail API (read-only, always OK)    │
│        ├── draft_email  ──► Gmail API (creates draft, no HITL)  │
│        ├── send_email   ──► Gmail API (requires HITL approval)  │
│        └── reply_email  ──► Gmail API (requires HITL approval)  │
│                                                                  │
│        └──────────────────► vault/Logs/actions/*.json            │
└─────────────────────────────────────────────────────────────────┘
```

## Decision Tree

```
User request arrives
  │
  ├─ "search emails" ──► search_email (always allowed, no approval)
  │
  ├─ "draft email" ──► draft_email (no approval needed, DEV_MODE safe)
  │
  ├─ "send email" ──► Check vault/Approved/ for matching approval file
  │     ├─ Approval found ──► Check rate limit (10/hour)
  │     │     ├─ Under limit ──► send_email ──► consume approval ──► log
  │     │     └─ Over limit  ──► Reject with cooldown time
  │     └─ No approval ──► Reject with guidance to create approval file
  │
  └─ "reply to thread" ──► Check vault/Approved/ for matching approval file
        ├─ Approval found ──► Check rate limit (10/hour)
        │     ├─ Under limit ──► reply_email ──► consume approval ──► log
        │     └─ Over limit  ──► Reject with cooldown time
        └─ No approval ──► Reject with guidance to create approval file
```

## MCP Tools Reference

### search_email

Search Gmail for emails matching a query. Always allowed.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| query | string | Yes | - | Gmail search syntax |
| max_results | integer | No | 5 | Max results (1-50) |

**Returns**: Formatted list with From, Subject, Date, Snippet, Message ID, Thread ID.

### draft_email

Create an email draft in Gmail (does not send). No approval required.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| to | string | Yes | Recipient email address |
| subject | string | Yes | Email subject line |
| body | string | Yes | Plain text email body |

**Returns**: Draft ID and confirmation message. In DEV_MODE: logged but not created.

### send_email

Send an email via Gmail. Requires HITL approval and is rate limited.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| to | string | Yes | Recipient email address |
| subject | string | Yes | Email subject line |
| body | string | Yes | Plain text email body |

**Pre-conditions**:
- Approval file in `vault/Approved/` with `type: email_send`, `status: approved`, matching `to`
- Rate limit not exceeded (< 10 sends/hour)
- `DEV_MODE=false` for actual sending

### reply_email

Reply to an existing email thread with correct Gmail threading.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| thread_id | string | Yes | Gmail thread ID |
| message_id | string | Yes | Gmail message ID to reply to |
| body | string | Yes | Plain text reply body |

**Pre-conditions**:
- Approval file in `vault/Approved/` with `type: email_reply`, `status: approved`, matching `thread_id`
- Rate limit not exceeded (< 10 sends/hour)
- `DEV_MODE=false` for actual sending

## HITL Approval Workflow

### Creating an Approval File

For `send_email`, create a file in `vault/Approved/`:

```yaml
---
type: email_send
status: approved
to: recipient@example.com
subject: "Meeting follow-up"
approved_at: 2026-02-17T10:00:00Z
risk_assessment: low
---

## Action Summary

Send a follow-up email about the meeting to recipient@example.com.

## Rollback Plan

Recall email if within 30 seconds, otherwise send follow-up correction.
```

For `reply_email`:

```yaml
---
type: email_reply
status: approved
thread_id: "18d5a2b3c4e5f6g7"
approved_at: 2026-02-17T10:00:00Z
risk_assessment: low
---

## Action Summary

Reply to the invoice thread confirming payment.
```

### Approval Lifecycle

```
vault/Plans/       ──► Create action plan
vault/Pending_Approval/ ──► Await human review
vault/Approved/    ──► Human approves (moves file here)
vault/Done/        ──► Auto-moved after successful execution
```

## Safety Notes

- **DEV_MODE** (default: `true`): All send/draft/reply operations are logged but NOT executed
- **Rate Limiting**: 10 email sends per rolling hour window (configurable in `config/rate_limits.json`)
- **HITL Required**: `send_email` and `reply_email` always require explicit approval files
- **Audit Logging**: Every tool invocation logged to `vault/Logs/actions/` with redacted emails
- **Email Redaction**: Addresses masked in logs (e.g., `j***@example.com`)

## Running the MCP Server

```bash
# Start server via MCP stdio transport
uv run python -m backend.mcp_servers.email_server

# Re-authorize Gmail token (if scopes changed)
uv run python -m backend.mcp_servers.email_server --auth-only

# Run tests
uv run pytest tests/test_email_server.py tests/test_gmail_client.py tests/test_approval.py tests/test_rate_limiter.py -v
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No valid Gmail token" | Run `--auth-only` to re-authorize |
| "Permission denied" | Token missing `gmail.send` scope — re-authorize |
| "Rate limit exceeded" | Wait for rolling window to clear |
| "No approval file found" | Create approval file in `vault/Approved/` with matching `type` and `to` |
| Server not responding | Check MCP config in `config/mcp.json`, ensure `enabled: true` |
