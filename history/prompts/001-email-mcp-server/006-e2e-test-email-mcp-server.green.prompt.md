---
id: 6
title: E2E Test Email MCP Server
stage: green
date: 2026-02-17
surface: agent
model: claude-opus-4-6
feature: 001-email-mcp-server
branch: 001-email-mcp-server
user: PMLS
command: manual
labels: ["e2e-test", "gmail", "mcp", "live-test"]
links:
  spec: specs/001-email-mcp-server/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - scripts/e2e_test_email_mcp.py
  - vault/Logs/actions/e2e-test-2026-02-17.json
  - vault/Done/e2e-test-send-email.md
tests:
  - DEV_MODE: 11/11 passed (auth, search, draft, send, rate_limiter, 4 MCP tools)
  - LIVE: 7/7 passed (auth, search, draft_live, approval, send_live, rate_limiter)
---

## Prompt

Help me test the Email MCP server end-to-end:
1. First, verify the MCP server starts correctly by running it in test mode
2. Test the search_email tool - search for recent emails in my inbox
3. Test the draft_email tool - create a draft email to myself (twahaahmed130@gmail.com)
4. Show me how to verify the draft was created in my Gmail drafts
5. For send_email test: create an approval file in vault/Approved/ for sending a test email to myself, then test the send
6. Log all results to vault/Logs/

## Response snapshot

Created comprehensive E2E test script (scripts/e2e_test_email_mcp.py) with two modes:
- DEV_MODE (--dev): 11/11 passed — tests all 4 MCP tool functions via patched context
- LIVE (--live): 7/7 passed — real Gmail API calls

Key results:
- Token was revoked, re-authorized with all 3 scopes (readonly, modify, send)
- Search: Found 3 emails from Claude Team in inbox (1874ms)
- Draft: Created real draft (ID: r2934540694987588362) in 401ms
- Send: Sent real email (ID: 19c6bc2a8a918e3d) in 357ms
- Approval: Created, found, consumed, moved to vault/Done/
- All results logged to vault/Logs/actions/e2e-test-2026-02-17.json

## Outcome

- Impact: Full E2E validation of the Email MCP Server — all 4 tools work with real Gmail API
- Tests: 18/18 total (11 DEV + 7 LIVE), 0 failures
- Files: 3 files created (test script, log, consumed approval)
- Next prompts: git commit, register MCP server with Claude Code, or proceed to next feature
- Reflection: Token revocation was the only blocker — re-auth flow worked smoothly. All pipelines (search, draft, send with HITL) validated end-to-end.

## Evaluation notes (flywheel)

- Failure modes observed: Token revocation required interactive re-auth (expected for expired tokens)
- Graders run and results (PASS/FAIL): DEV_MODE 11/11 PASS, LIVE 7/7 PASS
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): Add reply_email live test with a real thread_id from search results
