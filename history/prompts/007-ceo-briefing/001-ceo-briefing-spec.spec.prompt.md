---
id: "001"
title: "CEO Briefing Generator Spec"
stage: spec
date: 2026-02-22
surface: agent
model: claude-sonnet-4-6
feature: 007-ceo-briefing
branch: 007-ceo-briefing
user: PMLS
command: /sp.specify
labels: ["ceo-briefing", "spec", "gold-tier", "scheduler", "odoo", "vault"]
links:
  spec: specs/007-ceo-briefing/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/007-ceo-briefing/spec.md
  - specs/007-ceo-briefing/checklists/requirements.md
tests:
  - null
---

## Prompt

/sp.specify Weekly CEO Briefing Generator (Gold Tier) — Create an autonomous CEO Briefing system that audits all activity and generates a comprehensive weekly report every Monday at 8 AM. Reads vault/Business_Goals.md for targets and KPIs, queries Odoo for financial data (revenue, invoices, payments, balances via odoo_client.py), scans vault/Done/ for completed tasks, vault/Logs/ for all actions, vault/Needs_Action/ for pending items, analyzes patterns (bottlenecks, delays, cost optimization), generates briefing at vault/Briefings/YYYY-MM-DD_Monday_Briefing.md, updates vault/Dashboard.md. Architecture: backend/briefing/ with briefing_generator.py, data_collectors.py, report_formatter.py, scheduler.py. Skills: skills/ceo-briefing/SKILL.md. CLI: --generate-now, --preview, --period N, --status. Env vars: CEO_BRIEFING_DAY, CEO_BRIEFING_TIME, CEO_BRIEFING_TIMEZONE, CEO_BRIEFING_PERIOD_DAYS. Integrates with orchestrator (Monday 8 AM check). Output template with frontmatter, Executive Summary, Revenue and Financial Health, Completed Tasks, Pending Items, Communication Summary, Bottlenecks and Delays, Proactive Suggestions. Tests for data collection, formatting, scheduling.

## Response snapshot

Created Feature 007 (ceo-briefing) specification. Branch `007-ceo-briefing` created (PowerShell script errored on long description but branch creation succeeded; spec written agent-natively).

**Spec written to**: `specs/007-ceo-briefing/spec.md`

**5 User Stories defined**:
- US1 (P1): On-Demand Briefing Generation via `--generate-now` — core MVP
- US2 (P2): Automated Weekly Schedule — orchestrator-integrated Monday 8 AM trigger
- US3 (P3): Preview Mode (`--preview`) — console output, no vault writes
- US4 (P4): Custom Period Analysis (`--period N`) — override default 7-day lookback
- US5 (P5): System Status Check (`--status`) — health reporting without generation

**20 Functional Requirements (FR-001 to FR-020)** covering: data collection from Odoo + vault, 7-section report structure, CLI flags, env var configuration, DEV_MODE support, idempotency, graceful degradation, and action logging.

**8 Key Entities**: Briefing Report, Business Goal, Completed Task, Pending Item, Financial Summary, Action Log Entry, Pattern Insight, Briefing Schedule.

**8 Success Criteria (SC-001 to SC-008)**: All measurable and technology-agnostic — generation under 60s, 100% sections even in degraded mode, idempotency, 90%+ test coverage.

**Dependencies**: Feature 006 (Odoo client), Feature 002 (Orchestrator), existing vault structure and watcher logs.

**Out of Scope**: Email/WhatsApp delivery of briefings, LLM prose generation, multi-user support, trend comparison across briefings.

**Checklist**: `specs/007-ceo-briefing/checklists/requirements.md` — all items PASS, no NEEDS CLARIFICATION markers.

## Outcome

- ✅ Impact: Feature 007 specification complete. 5 independently testable user stories defined. 20 FRs, 8 SCs, clear scope boundaries. Branch `007-ceo-briefing` created. Ready for `/sp.plan`.
- 🧪 Tests: No implementation tests yet (spec phase).
- 📁 Files: 2 new files — specs/007-ceo-briefing/spec.md, specs/007-ceo-briefing/checklists/requirements.md
- 🔁 Next prompts: `/sp.plan` to generate research.md, data-model.md, contracts/, quickstart.md; then `/sp.tasks`; then `/sp.implement`.
- 🧠 Reflection: PowerShell create-new-feature.ps1 reliably fails with long description strings (PositionalParameterNotFound) — same pattern as Feature 006. Branch creation succeeds; spec must always be written agent-natively. Note this for future features.

## Evaluation notes (flywheel)

- Failure modes observed: create-new-feature.ps1 PositionalParameterNotFound on long -Json descriptions (recurring issue, Feature 006 and 007); mitigated by agent-native spec writing after branch creation.
- Graders run and results (PASS/FAIL): Spec quality checklist — all items PASS. No NEEDS CLARIFICATION markers.
- Prompt variant (if applicable): null
- Next experiment (smallest change to try): Wrap long description in a temp file and pass file path to PowerShell script to avoid argument length limit.
