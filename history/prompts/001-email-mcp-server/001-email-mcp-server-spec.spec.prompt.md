---
id: 1
title: Email MCP Server Spec
stage: spec
date: 2026-02-14
surface: agent
model: claude-opus-4-6
feature: 001-email-mcp-server
branch: 001-email-mcp-server
user: PMLS
command: /sp.specify
labels: ["email", "mcp", "gmail", "silver-tier"]
links:
  spec: specs/001-email-mcp-server/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/001-email-mcp-server/spec.md
  - specs/001-email-mcp-server/checklists/requirements.md
tests:
  - null
---

## Prompt

/sp.specify

## Feature: Email MCP Server (Silver Tier) - Python

Create an Email MCP server in PYTHON that allows Claude Code to send emails through Gmail API.

### Important: Use Python, NOT Node.js
Our entire project is Python-based. Use the `mcp` Python package (pip install mcp) to create the MCP server.

### What This Does
The Email MCP server gives Claude Code "hands" to send emails. It exposes tools that Claude can call:
- send_email: Send an email to a recipient
- draft_email: Create a draft in Gmail (safer, for review)
- reply_email: Reply to an existing email thread
- search_email: Search Gmail for specific emails

### Architecture
- Python MCP server using the `mcp` package
- Communicates with Claude Code via stdio
- Uses Gmail API with existing OAuth2 credentials (config/token.json)
- All sends require file in vault/Approved/ (HITL safety)

### MCP Server Structure
backend/mcp_servers/email_mcp/
├── __init__.py
├── server.py             # MCP server entry point
├── tools/
│   ├── __init__.py
│   ├── send_email.py     # Send email tool
│   ├── draft_email.py    # Create draft tool
│   ├── reply_email.py    # Reply to thread tool
│   └── search_email.py   # Search emails tool
└── utils/
    ├── __init__.py
    ├── gmail_auth.py     # OAuth2 using existing token.json
    └── logger.py         # Audit logging

### Tool Definitions

**send_email:**
- Parameters: to, subject, body, cc (optional), bcc (optional)
- Returns: message_id, thread_id, status
- Safety: Checks vault/Approved/ for matching approval file before sending
- Logs to vault/Logs/

**draft_email:**
- Parameters: to, subject, body
- Returns: draft_id, status
- Safety: No approval needed (just creates a draft)

**reply_email:**
- Parameters: thread_id, message_id, body
- Returns: message_id, status
- Safety: Checks approval for replies to new contacts

**search_email:**
- Parameters: query, max_results (default 5)
- Returns: list of {from, subject, snippet, date, message_id, thread_id}
- Safety: Read-only, no approval needed

### Configuration
MCP config for Claude Code (.claude/mcp.json) with uv run command, Gmail credentials paths, vault path.

### Security
- send_email and reply_email check vault/Approved/ before executing
- All actions logged to vault/Logs/ with full audit trail
- Rate limit: max 10 emails per hour
- New recipients require explicit approval

### Acceptance Criteria
- Python MCP server using mcp package follows Model Context Protocol standard
- All 4 tools implemented (send, draft, reply, search)
- Uses existing Gmail OAuth credentials from config/
- send_email checks for approval file before sending
- Audit logging for all actions
- Rate limiting (10 emails/hour)
- .claude/mcp.json configuration file created
- SKILL.md in skills/email-mcp/
- Tests for each tool
- Update pyproject.toml with mcp dependency

## Response snapshot

Created feature specification for Email MCP Server (Silver Tier). Generated branch `001-email-mcp-server`, wrote spec.md with 4 prioritized user stories (search P1, draft P2, send P3, reply P4), 14 functional requirements, 8 measurable success criteria, 6 edge cases, and clear scope boundaries. All quality checklist items pass — no clarifications needed. Spec is ready for `/sp.plan`.

## Outcome

- ✅ Impact: Feature specification created with full user scenarios, requirements, and success criteria
- 🧪 Tests: No tests at spec stage
- 📁 Files: 2 files created (spec.md, checklists/requirements.md)
- 🔁 Next prompts: /sp.clarify or /sp.plan
- 🧠 Reflection: User provided extremely detailed feature description — all requirements were unambiguous, so no clarification markers were needed

## Evaluation notes (flywheel)

- Failure modes observed: None — user description was comprehensive
- Graders run and results (PASS/FAIL): Quality checklist PASS (all items)
- Prompt variant (if applicable): N/A
- Next experiment (smallest change to try): N/A
