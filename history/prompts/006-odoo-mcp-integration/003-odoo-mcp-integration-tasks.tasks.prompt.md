---
id: "003"
title: "Odoo MCP Integration Tasks"
stage: tasks
date: "2026-02-22"
surface: agent
model: claude-sonnet-4-6
feature: 006-odoo-mcp-integration
branch: 006-odoo-mcp-integration
user: PMLS
command: /sp.tasks
labels: ["odoo", "mcp", "tasks", "hitl", "xmlrpc", "rate-limit", "tests"]
links:
  spec: specs/006-odoo-mcp-integration/spec.md
  ticket: "null"
  adr: "null"
  pr: "null"
files:
  - specs/006-odoo-mcp-integration/tasks.md (created — 33 tasks, 8 phases, 5 user stories)
tests:
  - "null"
---

## Prompt

/sp.tasks

## Response snapshot

Generated `specs/006-odoo-mcp-integration/tasks.md` with 33 tasks across 8 phases organized by the 5 user stories from spec.md.

**Phase breakdown**:
- Phase 1 (Setup): T001–T004 — __init__.py, rate_limits.json, .env.example, mcp.json
- Phase 2 (Foundational): T005–T007 — OdooClient class, odoo_server.py scaffold, utils.py draft writers
- Phase 3 (US1 P1 — Query Financial Data): T008–T017 — 5 OdooClient read methods + 5 MCP @mcp.tool() registrations
- Phase 4 (US2 P2 — CEO Briefing): T018–T019 — get_financial_summary() + briefing cache helpers
- Phase 5 (US3 P3 — Create Invoice HITL): T020–T022 — create_invoice client method + MCP tool with HITL + _reject_approval_file helper
- Phase 6 (US4 P4 — Record Payment HITL): T023–T025 — create_payment client method + MCP tool with HITL + already_paid rejection
- Phase 7 (US5 P5 — Create Customer): T026–T027 — create_customer with duplicate check + MCP tool (no HITL)
- Phase 8 (Polish): T028–T033 — tests (6 classes, 40+ tests), ruff check, full regression, SKILL.md, E2E DEV_MODE validation

**Key task specifics**:
- OdooClient methods have full DEV_MODE mock data specified in task descriptions
- _reject_approval_file() helper defined in T022, reused by T025 (US4)
- OdooRateLimiter subclass defined in T006 (scaffold), reads `odoo.writes_per_hour` from rate_limits.json
- Duplicate customer detection (search before create) in T026
- 14 tasks marked [P] for parallel execution

## Outcome

- ✅ Impact: 33 tasks generated covering all 5 user stories and 8 MCP tools. Zero ambiguity — each task specifies exact file path, method signatures, DEV_MODE behavior, and mock data. Immediately executable by /sp.implement.
- 🧪 Tests: T028 defines 6 test classes with 40+ tests; T029 runs them; T031 runs full regression
- 📁 Files: 1 file created (tasks.md)
- 🔁 Next prompts: `/sp.implement` to execute all 33 tasks
- 🧠 Reflection: _reject_approval_file() helper is a cross-cutting concern shared by US3 and US4 — placed in US3 (T022) and referenced by US4 (T025); this creates a soft dependency between US3 and US4 noted in dependency graph. OdooRateLimiter subclass placed in odoo_server.py scaffold (T006) rather than a separate file to keep the package slim.

## Evaluation notes (flywheel)

- Failure modes observed: None — all design artifacts (spec, plan, data-model, contracts, research, quickstart) were fully available; no NEEDS CLARIFICATION markers remained
- Graders run and results (PASS/FAIL): format validation — all 33 tasks have checkbox + TaskID + optional [P] + optional [Story] + description with file path (PASS)
- Prompt variant (if applicable): standard /sp.tasks flow
- Next experiment (smallest change to try): Run /sp.implement to execute T001–T033 sequentially
