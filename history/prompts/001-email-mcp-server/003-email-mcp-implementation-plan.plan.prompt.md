---
id: 003
title: Email MCP Server Implementation Plan
stage: plan
date: 2026-02-14
surface: agent
model: claude-opus-4-6
feature: 001-email-mcp-server
branch: 001-email-mcp-server
user: PMLS
command: /sp.plan
labels: ["mcp", "email", "gmail", "architecture", "plan"]
links:
  spec: specs/001-email-mcp-server/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/001-email-mcp-server/plan.md
  - specs/001-email-mcp-server/research.md
  - specs/001-email-mcp-server/data-model.md
  - specs/001-email-mcp-server/quickstart.md
  - specs/001-email-mcp-server/contracts/mcp-tools.md
tests:
  - null
---

## Prompt

/sp.plan

(User invoked the plan command with no additional input to generate the implementation plan for the 001-email-mcp-server feature.)

## Response snapshot

Generated a complete implementation plan for the Email MCP Server feature. The plan includes:

1. **research.md** — 9 research tasks covering MCP SDK selection (official `mcp` package with FastMCP), async pattern (`asyncio.to_thread()`), Gmail scopes, HITL approval pattern, rate limiting (in-memory sliding window), reply threading, DEV_MODE behavior, utility reuse, and MCP configuration.

2. **data-model.md** — 4 entities (EmailMessage, ApprovalFile, RateLimitCounter, AuditLogEntry) with full field definitions, validation rules, state transitions, Pydantic models, and relationship diagram.

3. **contracts/mcp-tools.md** — Complete MCP tool contracts for all 4 tools (search_email, draft_email, send_email, reply_email) with input schemas, output formats, behavior descriptions, error taxonomy, and idempotency analysis.

4. **quickstart.md** — Setup and usage guide covering prerequisites, installation, configuration, Claude Code registration, usage examples, and troubleshooting.

5. **plan.md** — Master plan with technical context, constitution check (all 8 principles PASS), source code structure (4 new modules + 1 skill + 4 test files), module design for each component, dependency graph, and risk analysis.

Key architectural decisions:
- FastMCP from official `mcp` package (not standalone fastmcp)
- asyncio.to_thread() wrapping sync google-api-python-client (consistent with existing gmail_watcher.py)
- 4-module separation: email_server.py, gmail_client.py, approval.py, rate_limiter.py
- Reuse all existing backend/utils/* modules

## Outcome

- ✅ Impact: Complete Phase 0 + Phase 1 plan artifacts generated. Ready for /sp.tasks.
- 🧪 Tests: No tests run (planning phase only). Test structure defined in plan.
- 📁 Files: 5 files created (plan.md, research.md, data-model.md, quickstart.md, contracts/mcp-tools.md)
- 🔁 Next prompts: `/sp.tasks` to generate actionable implementation tasks from the plan
- 🧠 Reflection: Research phase was thorough — codebase already has strong patterns (gmail_watcher auth, utility modules) that the MCP server can directly reuse. Constitution check passed cleanly with no violations.

## Evaluation notes (flywheel)

- Failure modes observed: None
- Graders run and results (PASS/FAIL): Constitution gate check: PASS (8/8 principles)
- Prompt variant (if applicable): N/A
- Next experiment (smallest change to try): N/A
