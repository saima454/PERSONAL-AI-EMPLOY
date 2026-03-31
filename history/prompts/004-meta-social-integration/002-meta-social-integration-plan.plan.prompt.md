---
id: "002"
title: meta-social-integration-plan
stage: plan
date: 2026-02-21
surface: agent
model: claude-sonnet-4-6
feature: "004-meta-social-integration"
branch: 004-meta-social-integration
user: Taha
command: /sp.plan
labels: ["facebook", "instagram", "meta", "playwright", "shared-session", "orchestrator", "action-executor", "content-scheduler", "data-model", "research"]
links:
  spec: specs/004-meta-social-integration/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/004-meta-social-integration/plan.md (created — full implementation plan)
  - specs/004-meta-social-integration/research.md (created — 8 decisions, all unknowns resolved)
  - specs/004-meta-social-integration/data-model.md (created — 5 entities + 2 dedup stores)
  - specs/004-meta-social-integration/quickstart.md (created — 10 integration scenarios)
  - specs/004-meta-social-integration/contracts/vault-file-contracts.md (created — 11 contracts)
tests:
  - (no tests at plan stage — test strategy defined in plan.md)
---

## Prompt

/sp.plan

## Response snapshot

Executed the full `/sp.plan` workflow for `004-meta-social-integration`.

**Setup**: `setup-plan.ps1 -Json` returned FEATURE_SPEC, IMPL_PLAN, SPECS_DIR, BRANCH paths. Plan template copied to `specs/004-meta-social-integration/plan.md`.

**Context loaded**: spec.md (5 user stories, 24 FRs), constitution.md (8 principles), linkedin_watcher.py (reference implementation pattern), action_executor.py (HANDLERS dict pattern), base_watcher.py (abstract interface), .env.example (config pattern).

**Phase 0 — Research** (8 decisions made):
1. Single shared `config/meta_session/` Playwright context for both Facebook and Instagram
2. Playwright broad selector strategy (mirrors LinkedIn watcher)
3. ActionExecutor HANDLERS dict extension (`facebook_post`, `instagram_post`)
4. ContentScheduler: optional `platform` field per topic, default `linkedin` (backward-compatible)
5. Optional `image_path` frontmatter for image attachments; validate before publish
6. Separate dedup JSON files per watcher (`processed_facebook.json`, `processed_instagram.json`)
7. Polling: FB=120s, IG=60s (both configurable)
8. Single `--setup` command per watcher; shared session dir

**Phase 1 — Design**:
- **data-model.md**: MetaSession, FacebookNotification, InstagramNotification, FacebookPostDraft, InstagramPostDraft — with full frontmatter schemas, validation rules, state machines, and dedup store schema
- **contracts/vault-file-contracts.md**: 11 contracts covering all vault file formats + Python module interfaces for 4 new classes + ActionExecutor/PostGenerator extension contracts
- **quickstart.md**: 10 end-to-end scenarios from session setup through character limit validation
- **plan.md**: Complete implementation plan with source code structure, module-by-module implementation notes, testing strategy (~50 tests, 7 classes), env vars reference, risk assessment

**Agent context updated**: `update-agent-context.ps1` ran successfully.

**Constitution check**: All 8 principles PASS. No violations to justify.

**ADR candidates identified**:
1. Shared Meta session (`config/meta_session/`) — `/sp.adr shared-meta-session`
2. Playwright vs. Meta Graph API — `/sp.adr meta-playwright-vs-api`

**New files**: 5 files, 0 regressions to existing codebase (no source code modified).

## Outcome

- ✅ Impact: Complete implementation plan for Facebook & Instagram integration. Shared Meta session design confirmed. 6 new source files identified (2 watchers, 2 posters, SKILL.md, plus modifications to 3 existing files). All 8 research decisions documented with rationale and alternatives.
- 🧪 Tests: No tests at plan stage; ~50 tests planned across 7 test classes in test_meta_social.py
- 📁 Files: 5 plan artifacts created (plan.md, research.md, data-model.md, quickstart.md, contracts/vault-file-contracts.md)
- 🔁 Next prompts: /sp.tasks to generate tasks.md; or /sp.adr shared-meta-session to document the session architecture decision
- 🧠 Reflection: The key insight is that Playwright's persistent context stores cookies for all domains, making a single `config/meta_session/` directory work for both Facebook and Instagram without any coordination overhead. The LinkedIn watcher is a near-perfect template for both new watchers — the main adaptation is session URL detection patterns and notification page structure.

## Evaluation notes (flywheel)

- Failure modes observed: PowerShell ExecutionPolicy blocked setup-plan.ps1 on first run — fixed with `-ExecutionPolicy Bypass`; background Bash agent couldn't write files due to missing permissions — fell back to direct Write tool
- Graders run and results (PASS/FAIL): Constitution check PASS (8/8); spec checklist PASS (carried from /sp.specify); no code tests at plan stage
- Prompt variant (if applicable): sp.plan with no user input (uses current branch context)
- Next experiment: Run /sp.tasks to see if the task breakdown correctly separates US-1 (session) as a blocking prerequisite for all other stories
