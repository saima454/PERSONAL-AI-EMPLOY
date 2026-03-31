---
id: "001"
title: "Odoo MCP Integration Spec"
stage: spec
date: "2026-02-21"
surface: agent
model: claude-sonnet-4-6
feature: 006-odoo-mcp-integration
branch: 006-odoo-mcp-integration
user: PMLS
command: /sp.specify
labels: ["odoo", "mcp", "accounting", "invoicing", "hitl", "spec", "gold-tier"]
links:
  spec: specs/006-odoo-mcp-integration/spec.md
  ticket: "null"
  adr: "null"
  pr: "null"
files:
  - specs/006-odoo-mcp-integration/spec.md (created — full feature specification, 5 user stories, 25 FRs, 8 SCs)
  - specs/006-odoo-mcp-integration/checklists/requirements.md (created — all 14 items passing)
tests:
  - "null"
---

## Prompt

/sp.specify Odoo Accounting MCP Integration (Gold Tier) — Create an MCP server that integrates with Odoo Community Edition (self-hosted) for accounting and invoicing via Odoo's XML-RPC API. URL: http://localhost:8069, Database: ai_employee. Exposes 8 tools: list_invoices, create_invoice (HITL), get_invoice, list_customers, create_customer, get_account_balance, list_transactions, create_payment (HITL). MCP server in backend/mcp_servers/odoo/ with odoo_server.py, odoo_client.py, utils.py. Uses xmlrpc.client. Credentials in .env. All write operations rate-limited (20/hour). DEV_MODE support. Audit logging. SKILL.md in skills/odoo-integration/. Feeds into CEO Briefing: revenue, outstanding invoices, payments, cash flow.

## Response snapshot

Created branch `006-odoo-mcp-integration` and spec at `specs/006-odoo-mcp-integration/spec.md`. Spec defines 5 user stories:
- US1 (P1): Query Financial Data — 5 read tools (list_invoices, get_invoice, list_customers, get_account_balance, list_transactions), no approval required
- US2 (P2): CEO Daily Briefing Integration — financial summary section with graceful degradation if Odoo unreachable
- US3 (P3): Create Invoice (HITL) — Pending_Approval → Approved → Done vault workflow for create_invoice
- US4 (P4): Record Payment (HITL) — Pending_Approval → Approved → Done vault workflow for create_payment
- US5 (P5): Create Customer — immediate creation via create_customer, duplicate check before write

25 functional requirements covering all 8 tools, rate limiting (20 write ops/hour), audit logging, DEV_MODE for all tools, credential management via .env. All constitution principles verified (HITL IV, Privacy I, Rate Limits VI, Logging VII). 8 measurable success criteria. Checklist all 14 items passing.

## Outcome

- ✅ Impact: Feature 006 Odoo Accounting MCP Integration fully specified. 5 user stories, 25 FRs, 8 SCs, 5 edge cases. HITL gates on create_invoice and create_payment. Constitution compliance verified. Ready for /sp.plan.
- 🧪 Tests: n/a (spec stage — SC-008 defines test scope for implementation)
- 📁 Files: 2 files created (spec.md, checklists/requirements.md), branch 006-odoo-mcp-integration checked out
- 🔁 Next prompts: `/sp.plan` to generate research.md, data-model.md, contracts/, plan.md
- 🧠 Reflection: Feature description included technical implementation details (XML-RPC, file structure, module names) — these were abstracted to business requirements in spec and deferred to plan.md. create_customer was correctly identified as lower-risk (no HITL required unlike create_invoice and create_payment). CEO Briefing integration confirmed as a user story rather than a footnote.

## Evaluation notes (flywheel)

- Failure modes observed: create-new-feature.ps1 script failed with PositionalParameterNotFound due to long description string — branch and spec directory were created successfully despite the error; spec.md was written via agent-native Write tool
- Graders run and results (PASS/FAIL): spec quality checklist PASS (14/14 items)
- Prompt variant (if applicable): standard /sp.specify flow
- Next experiment (smallest change to try): Run /sp.plan to produce research.md (Odoo XML-RPC patterns, MCP server structure, rate-limit strategy) and design artifacts
