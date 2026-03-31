---
id: 002
title: Email MCP Server Research - SDK Patterns and Gmail API
stage: general
date: 2026-02-14
surface: agent
model: claude-opus-4-6
feature: 001-email-mcp-server
branch: 001-email-mcp-server
user: PMLS
command: research
labels: ["mcp", "gmail-api", "python-sdk", "research", "async"]
links:
  spec: null
  ticket: null
  adr: null
  pr: null
files:
  - history/prompts/001-email-mcp-server/002-email-mcp-research.general.prompt.md
tests:
  - none
---

## Prompt

Research the following for building an Email MCP server in Python:

1. **MCP Python SDK**: Search for the official `mcp` Python package (Model Context Protocol). What's the current API for creating an MCP server with stdio transport? Look for `mcp.server`, `FastMCP`, or similar patterns. Find the latest recommended way to define tools.

2. **Gmail API Python**: What's the current recommended way to use Gmail API in Python with `google-api-python-client` and `google-auth-oauthlib`? Specifically:
   - How to authenticate with existing OAuth2 tokens (token.json + credentials.json)
   - How to send emails, create drafts, search emails, reply to threads
   - How to handle token refresh

3. **MCP + Gmail integration patterns**: Any existing patterns or examples of MCP servers that wrap Gmail API?

4. **Best practices for async MCP servers in Python**: The constitution requires async/await for all I/O.

Report: concrete code patterns, package names with versions, and API signatures.

## Response snapshot

Comprehensive research report delivered covering: MCP Python SDK v1.26.0 with FastMCP, Gmail API patterns with google-api-python-client, existing mcp-gmail reference implementation by jeremyjordan, and async wrapping patterns using asyncio.to_thread for sync Google API calls. Full code patterns and API signatures provided.

## Outcome

- Impact: Research complete, all four areas covered with concrete code patterns
- Tests: N/A (research task)
- Files: 1 PHR created
- Next prompts: Implement email MCP server based on research findings
- Reflection: Rich ecosystem of MCP+Gmail examples exists; key decision is whether to use sync tools with to_thread or invest in aiogoogle

## Evaluation notes (flywheel)

- Failure modes observed: None
- Graders run and results (PASS/FAIL): N/A
- Prompt variant (if applicable): N/A
- Next experiment (smallest change to try): N/A
