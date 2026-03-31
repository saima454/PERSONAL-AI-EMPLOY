# Research: Email MCP Server

**Feature**: 001-email-mcp-server
**Date**: 2026-02-14
**Status**: Complete

## Research Tasks

### RT-1: MCP Python SDK for stdio-based tool server

**Decision**: Use the official `mcp` package with `FastMCP` from `mcp.server.fastmcp`

**Rationale**:
- The official `mcp` PyPI package (v1.26.0+) includes `FastMCP` at `mcp.server.fastmcp`
- Provides decorator-based tool definition (`@mcp.tool()`) with automatic JSON Schema generation from Python type hints
- Supports stdio transport natively via `mcp.run(transport="stdio")`
- Lifespan management for shared resources (Gmail service) via `asynccontextmanager`
- Context injection for progress reporting and logging

**Alternatives Considered**:
- Standalone `fastmcp` package (v2.x): More features but separate dependency chain; official `mcp` package already includes `FastMCP` which is sufficient
- Raw `mcp.server.Server` with low-level protocol handling: More control but significantly more boilerplate

**Key Finding**: For stdio transport, logging MUST go to stderr (stdout is reserved for JSON-RPC messages)

### RT-2: Gmail API async pattern for MCP tools

**Decision**: Use `asyncio.to_thread()` to wrap synchronous `google-api-python-client` calls

**Rationale**:
- `google-api-python-client` is synchronous-only (no native async support)
- The existing `gmail_watcher.py` already uses `asyncio.to_thread()` at line 275 — proven pattern in this codebase
- Thread-safe for independent API calls
- Zero new dependencies

**Alternatives Considered**:
- `aiogoogle` package: Fully async but introduces a separate auth flow and dependency chain that diverges from existing `gmail_watcher.py` patterns
- Sync tools (no async): FastMCP supports sync tools, but constitution mandates `async/await` for all I/O operations

### RT-3: Gmail OAuth scopes for send/draft/search/reply

**Decision**: Add `gmail.send` scope to existing `gmail.readonly` + `gmail.modify`

**Rationale**:
- `gmail.readonly`: Already used by gmail_watcher for search
- `gmail.modify`: Already used by gmail_watcher for label modifications
- `gmail.send`: Required for sending emails (not covered by modify)
- The MCP server needs all three since it handles both read (search) and write (send/draft/reply) operations

**Key Finding**: Token must be re-authorized when adding `gmail.send` scope if the existing token.json only has readonly+modify

### RT-4: HITL approval file verification pattern

**Decision**: Parse YAML frontmatter from files in `vault/Approved/` matching the action type and parameters

**Rationale**:
- Existing vault infrastructure uses YAML frontmatter (see `backend/utils/frontmatter.py`)
- Approval files already have a defined schema: `type`, `status`, action summary, risk assessment, rollback plan
- The `send_email` and `reply_email` tools check for a matching file in `vault/Approved/` before executing
- Match criteria: `type: email_send` or `type: email_reply`, with matching recipient and subject

**Alternatives Considered**:
- Database-backed approval: Over-engineered for file-based vault system
- API-based approval: Violates local-first principle (Constitution I)

### RT-5: Rate limiting implementation

**Decision**: In-memory sliding window counter with configurable limits from `config/rate_limits.json`

**Rationale**:
- Spec explicitly states rate limit counter resets on server restart (no persistence needed)
- `config/rate_limits.json` already defines: 10 sends/hour, 50 sends/day
- Sliding window is more accurate than fixed window for burst prevention
- Simple `collections.deque` of timestamps, pruned on each check

**Alternatives Considered**:
- Token bucket algorithm: More complex, unnecessary for single-instance server
- File-based persistence: Spec says reset on restart is acceptable for Silver tier

### RT-6: Email reply threading in Gmail API

**Decision**: Use `threadId` + `In-Reply-To` + `References` headers for correct threading

**Rationale**:
- Gmail requires three things for proper threading:
  1. `threadId` in the API `send()` call body
  2. `In-Reply-To` header matching the original message's `Message-ID`
  3. `References` header containing the full reference chain
- The `reply_email` tool must first fetch the original message's headers to extract `Message-ID`

**Key Finding**: Subject must start with "Re: " for Gmail to display it as a reply in the UI

### RT-7: DEV_MODE behavior for email MCP server

**Decision**: When `DEV_MODE=true`, tools log the action to `vault/Logs/dev_actions.md` instead of executing Gmail API calls

**Rationale**:
- Constitution Principle V explicitly requires: "Email/messaging actions MUST write to `/vault/Logs/dev_actions.md` instead of sending"
- `search_email` can operate normally in DEV_MODE (read-only, no side effects)
- `draft_email` should log-only in DEV_MODE (write operation)
- `send_email` and `reply_email` must always log-only in DEV_MODE

### RT-8: Existing utility reuse

**Decision**: Reuse `backend/utils/*` modules for logging, timestamps, frontmatter, and correlation IDs

**Rationale**:
- `log_action()` from `logging_utils.py` — vault audit trail (JSON format)
- `now_iso()`, `today_iso()` from `timestamps.py` — consistent timestamp formatting
- `correlation_id()`, `short_id()` from `uuid_utils.py` — action tracing
- `parse_frontmatter()`, `extract_frontmatter()` from `frontmatter.py` — approval file parsing

**Key Finding**: All utilities are synchronous; wrap in `asyncio.to_thread()` only if I/O-bound (frontmatter parsing is CPU-bound and fast — no wrapping needed)

### RT-9: MCP configuration for Claude Code

**Decision**: Update `config/mcp.json` to enable the email server with correct command and capabilities

**Rationale**:
- `config/mcp.json` already has an `email` entry with `command: "python"`, `args: ["-m", "backend.mcp_servers.email_server"]`
- Capabilities list needs updating to match actual tools: `send_email`, `draft_email`, `reply_email`, `search_email`
- Set `enabled: true` when implementation is complete

**Key Finding**: Claude Code also requires a `.claude/mcp.json` or equivalent MCP config in the user's Claude Code settings. The project's `config/mcp.json` documents the intended config but the actual Claude Code integration requires the user to add the server to their Claude Code MCP settings.
