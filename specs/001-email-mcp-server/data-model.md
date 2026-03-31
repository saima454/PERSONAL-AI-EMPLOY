# Data Model: Email MCP Server

**Feature**: 001-email-mcp-server
**Date**: 2026-02-14

## Entities

### 1. EmailMessage

Represents a Gmail message returned by search or referenced in send/reply operations.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| message_id | `str` | Gmail API | Unique Gmail message identifier |
| thread_id | `str` | Gmail API | Gmail conversation thread identifier |
| from_address | `str` | Gmail headers | Sender email address |
| to_address | `str` | Gmail headers | Recipient email address(es) |
| subject | `str` | Gmail headers | Email subject line |
| snippet | `str` | Gmail API | Preview text (max 200 chars) |
| date | `str` | Gmail headers | RFC 2822 date string |
| labels | `list[str]` | Gmail API | Gmail label IDs |

**Validation Rules**:
- `message_id` and `thread_id`: Non-empty strings
- `from_address` / `to_address`: Valid email format (RFC 5322)
- `subject`: Max 998 characters (RFC 2822 limit)

### 2. ApprovalFile

A markdown file in `vault/Approved/` that gates send/reply operations.

| Field | Type | Location | Description |
|-------|------|----------|-------------|
| type | `str` | YAML frontmatter | `"email_send"` or `"email_reply"` |
| status | `str` | YAML frontmatter | Must be `"approved"` |
| action_type | `str` | YAML frontmatter | `"send_email"` or `"reply_email"` |
| to | `str` | YAML frontmatter | Target recipient email |
| subject | `str` | YAML frontmatter | Email subject (for matching) |
| created | `str` | YAML frontmatter | ISO 8601 creation timestamp |
| approved_at | `str` | YAML frontmatter | ISO 8601 approval timestamp |
| risk_assessment | `str` | Body | Risk level and justification |
| rollback_plan | `str` | Body | How to undo (e.g., "recall email if within 30s") |

**Matching Rules** (for `send_email` / `reply_email` to proceed):
1. File exists in `vault/Approved/`
2. `type` matches the action (`email_send` or `email_reply`)
3. `status` equals `"approved"`
4. `to` field matches the requested recipient (case-insensitive)
5. Most recent matching file is used if multiple exist

**State Transitions**:
```
[Created in vault/Plans/]
    → [Moved to vault/Pending_Approval/]
    → [Human moves to vault/Approved/ or vault/Rejected/]
    → [After execution: moved to vault/Done/]
```

### 3. RateLimitCounter

In-memory sliding window counter for email sends.

| Field | Type | Persistence | Description |
|-------|------|-------------|-------------|
| send_timestamps | `deque[float]` | Memory only | UTC timestamps of recent sends |
| window_seconds | `int` | From config | Rolling window size (3600 = 1 hour) |
| max_sends | `int` | From config | Max sends per window (default 10) |

**Validation Rules**:
- Rejects requests when `len(active_timestamps) >= max_sends`
- Returns remaining cooldown time on rejection
- Resets on server restart (per spec assumption)

### 4. AuditLogEntry

Structured log record appended to `vault/Logs/actions/<date>.json`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| timestamp | `str` | Yes | ISO 8601 UTC |
| correlation_id | `str` | Yes | UUID v4 for tracing |
| actor | `str` | Yes | Always `"email_mcp"` |
| action_type | `str` | Yes | Tool name: `send_email`, `draft_email`, `reply_email`, `search_email` |
| target | `str` | Yes | Redacted recipient (e.g., `j***@example.com`) |
| result | `str` | Yes | `"success"`, `"rejected"`, `"rate_limited"`, `"error"`, `"dev_mode"` |
| duration_ms | `int` | No | Execution time in milliseconds |
| parameters | `dict` | No | Redacted request parameters |
| error | `str` | No | Error message if result is `"error"` |

**Redaction Rules** (per Constitution VII):
- Email addresses: `john.doe@example.com` → `j***@example.com`
- Email body: Never logged (only subject snippet if needed)
- Subject: First 50 chars max

## Pydantic Models

```python
from pydantic import BaseModel, EmailStr, Field

class SendEmailRequest(BaseModel):
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., max_length=998, description="Email subject")
    body: str = Field(..., description="Plain text email body")

class DraftEmailRequest(BaseModel):
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., max_length=998, description="Email subject")
    body: str = Field(..., description="Plain text email body")

class ReplyEmailRequest(BaseModel):
    thread_id: str = Field(..., description="Gmail thread ID to reply to")
    message_id: str = Field(..., description="Gmail message ID to reply to")
    body: str = Field(..., description="Plain text reply body")

class SearchEmailRequest(BaseModel):
    query: str = Field(..., description="Gmail search query string")
    max_results: int = Field(default=5, ge=1, le=50, description="Max results to return")

class EmailResult(BaseModel):
    message_id: str
    thread_id: str
    from_address: str
    to_address: str
    subject: str
    snippet: str
    date: str
```

## Relationships

```
SearchEmailRequest ──> [Gmail API] ──> list[EmailResult]
                                            │
                                            ▼
                                     thread_id, message_id
                                            │
                                            ▼
SendEmailRequest ──> [ApprovalFile check] ──> [RateLimitCounter check] ──> [Gmail API] ──> AuditLogEntry
DraftEmailRequest ──> [Gmail API] ──> AuditLogEntry
ReplyEmailRequest ──> [ApprovalFile check] ──> [RateLimitCounter check] ──> [Gmail API] ──> AuditLogEntry
```
