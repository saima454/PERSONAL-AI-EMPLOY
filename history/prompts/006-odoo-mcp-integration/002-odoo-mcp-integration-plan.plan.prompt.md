---
id: "002"
title: "Odoo MCP Integration Plan"
stage: plan
date: "2026-02-22"
surface: agent
model: claude-sonnet-4-6
feature: 006-odoo-mcp-integration
branch: 006-odoo-mcp-integration
user: PMLS
command: /sp.plan
labels: ["odoo", "mcp", "plan", "xmlrpc", "hitl", "rate-limit", "ceo-briefing", "data-model"]
links:
  spec: specs/006-odoo-mcp-integration/spec.md
  ticket: "null"
  adr: "null"
  pr: "null"
files:
  - specs/006-odoo-mcp-integration/plan.md (created — full implementation plan)
  - specs/006-odoo-mcp-integration/research.md (created — Odoo XML-RPC patterns, decisions)
  - specs/006-odoo-mcp-integration/data-model.md (created — 7 entities, vault file formats)
  - specs/006-odoo-mcp-integration/quickstart.md (created — 8 integration scenarios)
  - specs/006-odoo-mcp-integration/contracts/tools.md (created — 8 MCP tool contracts)
  - CLAUDE.md (modified — agent context updated with Odoo technology)
tests:
  - "null"
---

## Prompt

/sp.plan

## Response snapshot

Executed full /sp.plan workflow for Feature 006 Odoo Accounting MCP Integration.

**Phase 0 (Research)**: Launched research agent to confirm Odoo XML-RPC API patterns. Key findings:
- `xmlrpc.client` (stdlib) is optimal — zero new dependencies
- Odoo auth: `xmlrpc/2/common.authenticate()` → uid, then `xmlrpc/2/object.execute_kw()` for all data ops
- account.move (invoices), account.payment (payments), res.partner (customers), account.account + account.move.line (balances/transactions)
- API key auth preferred over password

**Phase 1 (Design Artifacts)**:
- `research.md`: 10 decisions covering auth, model fields, HITL pattern reuse, rate limit strategy, async wrapping, DEV_MODE, CEO briefing integration
- `data-model.md`: 7 entities (OdooInvoice, OdooPayment, OdooCustomer, OdooAccount, OdooTransaction, OdooInvoiceDraftFile, OdooPaymentDraftFile) with fields, validation, and state machines
- `contracts/tools.md`: 8 MCP tool contracts with parameters, return formats, and full error tables
- `quickstart.md`: 8 integration scenarios covering all user stories (list invoices, create customer, full invoice HITL flow, full payment HITL flow, CEO briefing, rate limit rejection, Odoo unreachable)
- `plan.md`: Full implementation plan with Technical Context, Constitution Check (all 6 gates passing), Project Structure, Architecture Detail (4 layers), 5 key technical decisions, test coverage plan (40+ tests, 6 classes)

**Constitution Check**: ALL GATES PASS
- HITL: create_invoice + create_payment require vault/Approved/ files; create_customer exempt (non-financial)
- Privacy: ODOO_* in .env only; amounts redacted in audit logs
- DEV_MODE: All 8 tools support mock data / simulated writes
- Rate Limiting: 20 write ops/hour shared via OdooRateLimiter subclass
- Audit Logging: Every tool invocation → vault/Logs/actions/
- Error Handling: xmlrpc.client.Fault + ProtocolError caught; CEO briefing degrades gracefully

## Outcome

- ✅ Impact: Feature 006 planning complete. 5 artifacts generated. Architecture validated against constitution. Zero violations. Ready for /sp.tasks.
- 🧪 Tests: n/a (plan stage — test coverage plan defined in plan.md: 40+ tests, 6 classes)
- 📁 Files: 5 new files created (research.md, data-model.md, quickstart.md, contracts/tools.md, plan.md updated), CLAUDE.md modified
- 🔁 Next prompts: `/sp.tasks` to generate tasks.md with T001–TXXXX implementation tasks
- 🧠 Reflection: xmlrpc.client stdlib choice eliminates all new dependencies. OdooRateLimiter subclass reuses proven sliding-window implementation. CEO briefing integration via utils.py helper keeps briefing generator unchanged. create_customer without HITL is justified (non-financial, reversible).

## Evaluation notes (flywheel)

- Failure modes observed: None — research agent returned comprehensive Odoo field reference; existing codebase patterns (email_server.py, approval.py, rate_limiter.py) provided clear implementation blueprint
- Graders run and results (PASS/FAIL): Constitution check PASS (6/6 gates); spec quality checklist already 14/14 from previous session
- Prompt variant (if applicable): standard /sp.plan flow
- Next experiment (smallest change to try): Run /sp.tasks to generate ~40 ordered implementation tasks with TDD structure
