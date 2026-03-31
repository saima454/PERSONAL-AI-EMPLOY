# Quickstart: Email MCP Server

**Feature**: 001-email-mcp-server
**Date**: 2026-02-14

## Prerequisites

1. **Python 3.13+** installed
2. **uv** package manager installed
3. **Gmail OAuth credentials** already configured (`config/credentials.json` and `config/token.json` from Gmail watcher setup)
4. Gmail API scopes must include `gmail.send` (may require re-authorization)

## Setup

### 1. Install MCP dependency

```bash
uv add "mcp[cli]>=1.26.0"
```

### 2. Verify Gmail credentials have send scope

```bash
uv run python -c "
from google.oauth2.credentials import Credentials
creds = Credentials.from_authorized_user_file('config/token.json')
print('Scopes:', creds.scopes)
# Should include: https://www.googleapis.com/auth/gmail.send
"
```

If `gmail.send` is missing, re-authorize:
```bash
uv run python backend/mcp_servers/email_server.py --auth-only
```

### 3. Configure environment

Ensure `.env` has:
```env
DEV_MODE=true
DRY_RUN=true
VAULT_PATH=./vault
GMAIL_CREDENTIALS_PATH=config/credentials.json
GMAIL_TOKEN_PATH=config/token.json
```

### 4. Test the MCP server locally

```bash
# Start server in stdio mode (manual testing)
uv run python -m backend.mcp_servers.email_server

# Run tests
uv run pytest tests/test_email_server.py tests/test_gmail_client.py -v
```

### 5. Register with Claude Code

Add to your Claude Code MCP settings (`.claude/mcp.json` or Claude Code preferences):

```json
{
  "mcpServers": {
    "email": {
      "command": "uv",
      "args": ["run", "python", "-m", "backend.mcp_servers.email_server"],
      "cwd": "<absolute-path-to-project-root>"
    }
  }
}
```

## Usage

### Search emails
Ask Claude: "Search my Gmail for emails about invoices from last week"

### Draft an email
Ask Claude: "Draft a reply to John about rescheduling the meeting to Friday"

### Send an email (requires approval)
1. Claude creates a plan file in `vault/Plans/`
2. Review and move to `vault/Approved/`
3. Ask Claude: "Send the approved email to john@example.com"

### Reply to a thread (requires approval)
1. Search for the thread first
2. Create and approve a reply plan
3. Ask Claude: "Reply to thread [thread_id] with the approved response"

## Safety Notes

- `DEV_MODE=true` (default): All send/draft/reply operations are logged but NOT executed
- `DRY_RUN=true`: Additional safety layer; all external calls are simulated
- Rate limit: 10 emails per hour maximum
- `send_email` and `reply_email` always require an approval file in `vault/Approved/`
- `draft_email` does NOT require approval (drafts are not sent)
- `search_email` is read-only and always allowed

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No valid Gmail token" | Run `uv run python backend/mcp_servers/email_server.py --auth-only` |
| "Permission denied" | Token missing `gmail.send` scope — re-authorize |
| "Rate limit exceeded" | Wait for rolling window to clear (check `vault/Logs/actions/`) |
| "No approval file found" | Create approval file in `vault/Approved/` with matching `type` and `to` |
| Server not appearing in Claude Code | Check MCP config path and ensure `cwd` is correct |
