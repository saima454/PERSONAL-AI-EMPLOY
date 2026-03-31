# MCP Tool Contracts: Email MCP Server

**Feature**: 001-email-mcp-server
**Protocol**: Model Context Protocol (MCP) via stdio transport
**Date**: 2026-02-14

## Tool: `search_email`

**Priority**: P1 (Foundation) | **Approval Required**: No | **Rate Limited**: No

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Gmail search query (e.g., 'from:user@example.com subject:invoice after:2026/01/01')"
    },
    "max_results": {
      "type": "integer",
      "description": "Maximum number of results to return",
      "default": 5,
      "minimum": 1,
      "maximum": 50
    }
  },
  "required": ["query"]
}
```

### Output

**Success** — Returns formatted text with matching emails:
```
Found 3 emails matching "invoice":

1. From: john@example.com | Subject: Invoice #1234 | Date: 2026-02-10
   Snippet: Please find attached the invoice for January services...
   Message ID: 18d5a... | Thread ID: 18d5a...

2. From: billing@vendor.com | Subject: Invoice overdue | Date: 2026-02-08
   ...
```

**No results**: `"No emails found matching: invoice"`

**Error**: `"Error searching emails: <error message>"`

### Behavior
- Read-only operation; always allowed regardless of DEV_MODE
- Calls Gmail API `users.messages.list` + `users.messages.get` for metadata
- Logs audit entry with action_type `search_email`

---

## Tool: `draft_email`

**Priority**: P2 (Low-risk write) | **Approval Required**: No | **Rate Limited**: No

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "to": {
      "type": "string",
      "description": "Recipient email address"
    },
    "subject": {
      "type": "string",
      "description": "Email subject line"
    },
    "body": {
      "type": "string",
      "description": "Plain text email body"
    }
  },
  "required": ["to", "subject", "body"]
}
```

### Output

**Success**: `"Draft created successfully. Draft ID: r1234567890. Review it in your Gmail drafts folder."`

**DEV_MODE**: `"[DEV_MODE] Draft logged but not created. To: j***@example.com, Subject: Meeting notes"`

**Validation error**: `"Error: Invalid email address format: not-an-email"`

**Error**: `"Error creating draft: <error message>"`

### Behavior
- Creates draft in Gmail (does NOT send)
- No approval file required (drafts are harmless)
- In DEV_MODE: logs to vault but does NOT call Gmail API
- Logs audit entry with action_type `draft_email`

---

## Tool: `send_email`

**Priority**: P3 (High-risk write) | **Approval Required**: Yes | **Rate Limited**: Yes (10/hour)

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "to": {
      "type": "string",
      "description": "Recipient email address"
    },
    "subject": {
      "type": "string",
      "description": "Email subject line"
    },
    "body": {
      "type": "string",
      "description": "Plain text email body"
    }
  },
  "required": ["to", "subject", "body"]
}
```

### Output

**Success**: `"Email sent successfully. Message ID: 18d5a... Thread ID: 18d5a..."`

**No approval**: `"Rejected: No matching approval file found in vault/Approved/ for sending to j***@example.com. Create an approval file with type: email_send and move it to vault/Approved/."`

**Rate limited**: `"Rejected: Rate limit exceeded (10 emails/hour). Next send available in 12 minutes."`

**DEV_MODE**: `"[DEV_MODE] Send logged but not executed. To: j***@example.com, Subject: Meeting notes"`

**Validation error**: `"Error: Invalid email address format: not-an-email"`

**Error**: `"Error sending email: <error message>"`

### Behavior
1. Validate input parameters
2. Check DEV_MODE → log-only if true
3. Check approval file in `vault/Approved/` → reject if missing
4. Check rate limit → reject if exceeded
5. Send via Gmail API `users.messages.send`
6. Move approval file to `vault/Done/` on success
7. Log audit entry with action_type `send_email`

### Pre-conditions
- Valid approval file in `vault/Approved/` with `type: email_send`, `status: approved`, matching `to`
- Rate limit not exceeded (< 10 sends in rolling 1-hour window)
- DEV_MODE=false for actual sending

---

## Tool: `reply_email`

**Priority**: P4 (Thread-aware write) | **Approval Required**: Yes | **Rate Limited**: Yes (10/hour)

### Input Schema

```json
{
  "type": "object",
  "properties": {
    "thread_id": {
      "type": "string",
      "description": "Gmail thread ID to reply to"
    },
    "message_id": {
      "type": "string",
      "description": "Gmail message ID to reply to (for correct threading headers)"
    },
    "body": {
      "type": "string",
      "description": "Plain text reply body"
    }
  },
  "required": ["thread_id", "message_id", "body"]
}
```

### Output

**Success**: `"Reply sent successfully. Message ID: 18d5b... Thread ID: 18d5a..."`

**No approval**: `"Rejected: No matching approval file found in vault/Approved/ for replying to thread 18d5a.... Create an approval file with type: email_reply and move it to vault/Approved/."`

**Rate limited**: `"Rejected: Rate limit exceeded (10 emails/hour). Next send available in 12 minutes."`

**Invalid thread**: `"Error: Thread ID 18d5a... not found or no longer accessible."`

**DEV_MODE**: `"[DEV_MODE] Reply logged but not executed. Thread: 18d5a..., Body length: 245 chars"`

**Error**: `"Error replying to thread: <error message>"`

### Behavior
1. Validate thread_id and message_id
2. Check DEV_MODE → log-only if true
3. Check approval file in `vault/Approved/` → reject if missing
4. Check rate limit → reject if exceeded
5. Fetch original message headers (Message-ID, References, Subject, From)
6. Build reply with `In-Reply-To`, `References`, and `Re:` subject
7. Send via Gmail API `users.messages.send` with `threadId`
8. Move approval file to `vault/Done/` on success
9. Log audit entry with action_type `reply_email`

### Pre-conditions
- Valid approval file in `vault/Approved/` with `type: email_reply`, `status: approved`, matching `thread_id`
- Rate limit not exceeded
- DEV_MODE=false for actual sending
- Original message must be accessible in Gmail

---

## Error Taxonomy

| Error | HTTP Status (Gmail) | MCP Tool Response | Retry |
|-------|---------------------|-------------------|-------|
| Invalid input | N/A | Validation error message | No |
| Auth expired | 401 | Auto-refresh token, retry | Yes (auto) |
| Auth revoked | 401 (no refresh token) | Clear error directing to re-auth | No |
| Insufficient permissions | 403 | Permission error | No |
| Rate limit (Gmail) | 429 | Retry with exponential backoff | Yes (auto) |
| Rate limit (internal) | N/A | Remaining cooldown time | No (user waits) |
| Not found (thread/message) | 404 | Clear "not found" message | No |
| Transient server error | 500/503 | Retry with backoff (max 3) | Yes (auto) |
| No approval file | N/A | Rejection with guidance | No |
| DEV_MODE active | N/A | Log-only confirmation | No |

## Idempotency

- `search_email`: Naturally idempotent (read-only)
- `draft_email`: NOT idempotent (creates a new draft each call). Claude should avoid repeat calls.
- `send_email`: NOT idempotent (sends a new email each call). Approval file is consumed (moved to Done) after first successful send, preventing accidental re-sends.
- `reply_email`: NOT idempotent. Same approval file consumption pattern as `send_email`.
