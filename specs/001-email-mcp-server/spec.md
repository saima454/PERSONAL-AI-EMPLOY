# Feature Specification: Email MCP Server

**Feature Branch**: `001-email-mcp-server`
**Created**: 2026-02-14
**Status**: Draft
**Input**: User description: "Create an Email MCP server in Python that allows Claude Code to send emails through Gmail API"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Search Emails via Claude Code (Priority: P1)

The user asks Claude Code to find specific emails (e.g., "find all invoices from last week"). Claude Code calls the `search_email` tool through the MCP server, which queries Gmail and returns matching results displayed in the conversation.

**Why this priority**: Read-only operation with zero risk. Establishes Gmail API connectivity and proves the MCP server works end-to-end. Foundation for all other tools.

**Independent Test**: Can be fully tested by asking Claude Code to search for a known email. Delivers immediate value — the user gets email search without leaving the terminal.

**Acceptance Scenarios**:

1. **Given** the MCP server is running and Gmail credentials are valid, **When** the user asks Claude to search for emails matching "invoice", **Then** Claude calls `search_email` and returns a list of matching emails with sender, subject, snippet, date, and identifiers.
2. **Given** the search query matches no emails, **When** `search_email` is called, **Then** the tool returns an empty list with a clear message.
3. **Given** Gmail credentials are expired, **When** `search_email` is called, **Then** the tool attempts token refresh and retries, or returns a clear authentication error.

---

### User Story 2 - Draft Email via Claude Code (Priority: P2)

The user asks Claude Code to draft an email (e.g., "draft a reply to John about the meeting"). Claude Code composes the content and calls `draft_email`, which creates a Gmail draft the user can review in their Gmail client before sending manually.

**Why this priority**: Low-risk write operation — drafts sit in Gmail unsent until the user reviews. Enables Claude to compose emails while keeping the human firmly in control of sending.

**Independent Test**: Can be fully tested by asking Claude to draft an email and verifying the draft appears in Gmail. Delivers value — AI-composed drafts with human review before sending.

**Acceptance Scenarios**:

1. **Given** valid credentials, **When** Claude calls `draft_email` with to, subject, and body, **Then** a draft is created in Gmail and the tool returns a draft identifier and success status.
2. **Given** valid credentials, **When** Claude creates a draft, **Then** the action is logged to the vault audit trail.
3. **Given** an invalid recipient address, **When** `draft_email` is called, **Then** the tool returns a validation error without creating the draft.

---

### User Story 3 - Send Approved Email via Claude Code (Priority: P3)

The user wants Claude Code to send an email on their behalf. Claude creates a plan, the user approves it by moving the plan file to `vault/Approved/`, and then Claude calls `send_email` which verifies the approval file exists before actually sending via Gmail.

**Why this priority**: This is the highest-impact tool but also the highest-risk. Requires the HITL approval workflow to be working. Builds on the foundation of search (P1) and draft (P2).

**Independent Test**: Can be tested by creating an approval file in `vault/Approved/`, then invoking `send_email` and verifying the email arrives. Delivers the core value — AI-sent emails with human safety gates.

**Acceptance Scenarios**:

1. **Given** a matching approval file exists in `vault/Approved/`, **When** Claude calls `send_email` with to, subject, and body, **Then** the email is sent via Gmail and the tool returns message and thread identifiers.
2. **Given** no matching approval file exists, **When** `send_email` is called, **Then** the tool rejects the request with a clear message explaining approval is required.
3. **Given** the hourly rate limit (10 emails) has been reached, **When** `send_email` is called, **Then** the tool rejects the request with a rate-limit error.
4. **Given** a valid send, **When** the email is sent successfully, **Then** the action is logged with correlation ID, recipient, subject, and timestamp.

---

### User Story 4 - Reply to Email Thread (Priority: P4)

The user asks Claude to reply to an existing email thread. Claude calls `reply_email` with the thread and message identifiers, threading the reply correctly in Gmail. Replies to new/unknown contacts require approval; replies within existing threads to known contacts may proceed with lower friction.

**Why this priority**: Builds on send (P3) and search (P1). Requires thread context awareness. Important for ongoing conversations but not standalone MVP.

**Independent Test**: Can be tested by searching for a thread, then replying to it and verifying the reply appears threaded in Gmail.

**Acceptance Scenarios**:

1. **Given** a valid thread ID and approval file, **When** `reply_email` is called with a body, **Then** the reply is sent and correctly threaded in Gmail.
2. **Given** the recipient is a new/unknown contact, **When** `reply_email` is called without an approval file, **Then** the tool rejects the request requiring explicit approval.
3. **Given** an invalid thread or message ID, **When** `reply_email` is called, **Then** the tool returns a clear error without sending.

---

### Edge Cases

- What happens when Gmail API returns a transient 500 error? System retries with exponential backoff (max 3 retries).
- What happens when the OAuth token is fully revoked (not just expired)? System returns a clear error directing the user to re-authenticate.
- What happens when a send is approved but the approval file is malformed? System rejects the send and logs the parsing error.
- What happens when multiple approval files match a single send request? System uses the most recent approval file and logs the ambiguity.
- What happens when the MCP server process crashes mid-send? Gmail API is transactional — the email either sends or doesn't. No partial state. On restart, the server re-initializes cleanly.
- What happens when the email body contains special characters or HTML? System sends as plain text by default, preserving all characters via proper encoding.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose four tools via the Model Context Protocol: `send_email`, `draft_email`, `reply_email`, and `search_email`.
- **FR-002**: System MUST authenticate with Gmail using existing OAuth2 credentials stored in project configuration files.
- **FR-003**: System MUST refresh expired OAuth tokens automatically without user intervention.
- **FR-004**: The `send_email` tool MUST verify a matching approval file exists in `vault/Approved/` before sending any email.
- **FR-005**: The `send_email` tool MUST enforce a rate limit of 10 emails per hour, rejecting requests that exceed this limit.
- **FR-006**: The `draft_email` tool MUST create drafts in Gmail without requiring an approval file (drafts are not sent).
- **FR-007**: The `reply_email` tool MUST correctly thread replies using Gmail thread and message identifiers.
- **FR-008**: The `reply_email` tool MUST require an approval file when replying to contacts not previously seen in the thread.
- **FR-009**: The `search_email` tool MUST accept a query string and return matching emails with sender, subject, snippet, date, and identifiers.
- **FR-010**: The `search_email` tool MUST support a configurable maximum results parameter (default 5).
- **FR-011**: System MUST log every tool invocation to the vault audit trail with timestamp, action type, correlation ID, and result.
- **FR-012**: System MUST communicate via stdio transport as defined by the Model Context Protocol.
- **FR-013**: System MUST validate all input parameters before executing any Gmail API call.
- **FR-014**: System MUST redact sensitive data (email addresses, body content) in log entries per constitution logging requirements.

### Key Entities

- **Approval File**: A markdown file in `vault/Approved/` containing action summary, risk assessment, and rollback plan. Used to gate send/reply operations.
- **Email Message**: Represents a Gmail message with identifiers (message_id, thread_id), headers (from, to, subject, date), and content (snippet/body).
- **Rate Limit Counter**: Tracks email sends per hour. Resets on a rolling window basis. Stored in memory (resets on server restart).
- **Audit Log Entry**: Structured log record with timestamp, actor ("email_mcp"), action type, target, result, correlation ID, and duration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can search their Gmail inbox through Claude Code and receive results within 5 seconds of issuing the request.
- **SC-002**: Users can create email drafts through Claude Code that appear correctly in their Gmail drafts folder.
- **SC-003**: Approved emails are sent successfully with delivery confirmed by Gmail, and the action is fully logged within the vault.
- **SC-004**: Unapproved send attempts are blocked 100% of the time with a clear rejection message guiding the user to the approval workflow.
- **SC-005**: Rate-limited requests are rejected with a clear message indicating remaining cooldown time.
- **SC-006**: All tool invocations produce a complete audit log entry in the vault within 1 second of completion.
- **SC-007**: The MCP server starts and becomes ready to accept tool calls within 3 seconds.
- **SC-008**: Email replies are correctly threaded in Gmail (appear in the same conversation thread as the original message).

## Assumptions

- Gmail OAuth2 credentials (`config/credentials.json` and `config/token.json`) are already configured and valid from the existing Gmail watcher setup.
- The Obsidian vault folder structure (`vault/Approved/`, `vault/Logs/`, etc.) already exists from previous tier work.
- The approval file format follows the existing frontmatter conventions used elsewhere in the project (YAML frontmatter with `type`, `status`, and action fields).
- Rate limit counter resets on server restart (no persistent rate limit storage needed for Silver tier).
- Emails are sent as plain text (HTML email support is out of scope for this tier).
- The MCP server runs as a single instance per Claude Code session (no concurrent instance handling needed).

## Scope Boundaries

**In Scope:**
- Four MCP tools: send, draft, reply, search
- Gmail API integration via existing OAuth2 credentials
- HITL approval checking for send and reply operations
- Audit logging to vault
- Rate limiting (10 emails/hour)
- MCP configuration for Claude Code

**Out of Scope:**
- HTML-formatted emails
- Email attachments
- Calendar integration
- Contact management
- Email templates
- Multi-account Gmail support
- Persistent rate limit storage across restarts
- Email scheduling (send later)
