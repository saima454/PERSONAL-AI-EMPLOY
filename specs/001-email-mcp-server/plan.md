# Implementation Plan: Email MCP Server

**Branch**: `001-email-mcp-server` | **Date**: 2026-02-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-email-mcp-server/spec.md`

## Summary

Build a Python MCP server that exposes four Gmail tools (`search_email`, `draft_email`, `send_email`, `reply_email`) via stdio transport, enabling Claude Code to interact with Gmail. Uses the official `mcp` Python SDK with `FastMCP`, wraps synchronous `google-api-python-client` calls with `asyncio.to_thread()`, enforces HITL approval for send/reply, implements in-memory rate limiting (10/hour), and logs all actions to the vault audit trail.

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: `mcp[cli]>=1.26.0`, `google-api-python-client>=2.100.0`, `google-auth-oauthlib>=1.2.0`, `pydantic>=2.5.0`
**Storage**: File-based (Obsidian vault markdown files + JSON audit logs)
**Testing**: pytest + pytest-asyncio
**Target Platform**: Windows 11, local execution via Claude Code
**Project Type**: Single backend service (MCP server via stdio)
**Performance Goals**: Search results within 5 seconds (SC-001), server startup within 3 seconds (SC-007)
**Constraints**: All I/O async (constitution), stdout reserved for JSON-RPC (MCP stdio), DEV_MODE default true
**Scale/Scope**: Single user, single Gmail account, single MCP server instance

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | How Addressed |
|---|-----------|--------|---------------|
| I | Local-First & Privacy | PASS | OAuth creds in `config/` (gitignored). Logs redact emails (`j***@example.com`). No data leaves local env without approval. |
| II | Separation of Concerns | PASS | MCP server is **ACTION layer** — executes only approved actions. Does NOT watch or reason. |
| III | Agent Skills | PASS | `skills/email-sender/SKILL.md` will define the skill. MCP tools are the action mechanism. |
| IV | HITL Safety | PASS | `send_email` and `reply_email` require approval file in `vault/Approved/`. `draft_email` exempt (no send). `search_email` exempt (read-only). |
| V | DEV_MODE Safety | PASS | `DEV_MODE=true` default. Send/draft/reply log to `vault/Logs/dev_actions.md` instead of executing. Search works normally. |
| VI | Rate Limiting | PASS | In-memory sliding window: 10 sends/hour from `config/rate_limits.json`. Rejection returns remaining cooldown. |
| VII | Logging & Auditability | PASS | Every tool invocation → `vault/Logs/actions/<date>.json` via existing `log_action()`. Redacted params. Correlation IDs. |
| VIII | Error Handling | PASS | Retry with exponential backoff (max 3). Token auto-refresh. Circuit breaker from config. Clear error messages. |

**Gate Result**: ALL PASS — proceed to implementation.

**Post-Phase 1 Re-check**: All principles remain satisfied after design phase. No violations introduced.

## Project Structure

### Documentation (this feature)

```text
specs/001-email-mcp-server/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete)
├── data-model.md        # Phase 1 output (complete)
├── quickstart.md        # Phase 1 output (complete)
├── contracts/
│   └── mcp-tools.md     # Phase 1 output (complete)
└── tasks.md             # Phase 2 output (created by /sp.tasks)
```

### Source Code (repository root)

```text
backend/
├── mcp_servers/
│   ├── __init__.py              # Package init
│   ├── email_server.py          # FastMCP server entry point + 4 tool definitions
│   ├── gmail_client.py          # Gmail API wrapper (sync ops: send, draft, search, reply)
│   ├── approval.py              # HITL approval file verification logic
│   └── rate_limiter.py          # In-memory sliding window rate limiter
├── utils/                       # [EXISTING] Shared utilities
│   ├── frontmatter.py           # [EXISTING] YAML frontmatter parsing
│   ├── logging_utils.py         # [EXISTING] Audit logging (log_action)
│   ├── timestamps.py            # [EXISTING] ISO 8601 timestamps
│   └── uuid_utils.py            # [EXISTING] Correlation ID generation

skills/
└── email-sender/
    └── SKILL.md                 # Skill definition for email MCP server

tests/
├── test_email_server.py         # MCP tool integration tests (4 tools)
├── test_gmail_client.py         # Gmail API wrapper unit tests
├── test_approval.py             # Approval verification unit tests
└── test_rate_limiter.py         # Rate limiter unit tests

config/
├── mcp.json                     # [UPDATE] Enable email server, update capabilities
└── rate_limits.json             # [EXISTING] Rate limit configuration
```

**Structure Decision**: Follows existing `backend/` convention. MCP servers live in `backend/mcp_servers/` as defined by the canonical folder structure. Each concern is a separate module: server entry point, Gmail API client, approval logic, rate limiting. This matches the separation pattern used by `backend/watchers/` (watcher logic separate from utilities).

## Module Design

### `email_server.py` — MCP Server Entry Point

**Responsibility**: Define the FastMCP server, register 4 tools, manage lifespan (Gmail service init), handle DEV_MODE/DRY_RUN flags.

**Key Design**:
- `FastMCP("email-mcp-server", lifespan=app_lifespan)` with lifespan pattern for Gmail service injection
- Each `@mcp.tool()` async function: validate → check gates → execute → log → return
- Logging to stderr only (stdout is JSON-RPC)
- Entry point: `mcp.run(transport="stdio")`
- CLI: `python -m backend.mcp_servers.email_server` (also supports `--auth-only`)

**Dependencies**: `gmail_client`, `approval`, `rate_limiter`, `backend.utils.*`

### `gmail_client.py` — Gmail API Wrapper

**Responsibility**: Synchronous Gmail API operations. Thin wrapper around `google-api-python-client`. Authentication and token refresh.

**Key Design**:
- `GmailClient` class with methods: `authenticate()`, `send_message()`, `create_draft()`, `search_messages()`, `reply_to_thread()`, `get_message_headers()`
- All methods are synchronous (called via `asyncio.to_thread()` from tools)
- Reuses auth pattern from `gmail_watcher.py:106-131` (same token/credentials paths)
- Scopes: `gmail.readonly` + `gmail.modify` + `gmail.send`
- Retry logic with exponential backoff for transient errors (HttpError 429, 500, 503)
- Builds `EmailMessage` objects using Python's `email.message.EmailMessage`

### `approval.py` — HITL Approval Verification

**Responsibility**: Check vault/Approved/ for matching approval files. Parse frontmatter. Move consumed approvals to vault/Done/.

**Key Design**:
- `find_approval(vault_path, action_type, **match_fields) -> ApprovalFile | None`
- Scans `vault/Approved/` for `.md` files matching criteria
- Uses existing `extract_frontmatter()` from `backend/utils/frontmatter.py`
- `consume_approval(approval_path, vault_path)` — moves file to `vault/Done/` after successful send
- Match by: `type` (email_send/email_reply), `status` (approved), `to` or `thread_id`

### `rate_limiter.py` — Rate Limiting

**Responsibility**: Track email sends in memory. Enforce 10/hour rolling window.

**Key Design**:
- `RateLimiter` class with `collections.deque` of timestamps
- `check(action_type) -> tuple[bool, int]` — returns (allowed, seconds_until_next_slot)
- Loads limits from `config/rate_limits.json` on init
- Prunes expired timestamps on each check
- Resets on server restart (per spec)

## Dependency Graph

```
email_server.py
├── gmail_client.py          (Gmail API operations)
├── approval.py              (HITL file verification)
│   └── backend.utils.frontmatter  (YAML parsing)
├── rate_limiter.py          (send rate enforcement)
└── backend.utils.*          (logging, timestamps, UUIDs)
```

## Complexity Tracking

No constitution violations to justify. All gates pass cleanly.

## Risks & Follow-ups

1. **Token scope mismatch**: Existing `token.json` may lack `gmail.send` scope. Mitigation: `--auth-only` CLI flag triggers re-authorization with expanded scopes.
2. **Approval file format ambiguity**: The exact frontmatter schema for approval files isn't yet standardized across the project. Mitigation: Define the schema in `data-model.md` (done) and validate strictly.
3. **MCP SDK version stability**: The `mcp` package is evolving rapidly. Mitigation: Pin to `>=1.26.0` and test against the installed version. Avoid using experimental APIs.
