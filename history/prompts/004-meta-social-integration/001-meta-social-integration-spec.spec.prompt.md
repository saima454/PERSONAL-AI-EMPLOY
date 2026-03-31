---
id: "001"
title: meta-social-integration-spec
stage: spec
date: 2026-02-20
surface: agent
model: claude-sonnet-4-6
feature: "004-meta-social-integration"
branch: 004-meta-social-integration
user: Taha
command: /sp.specify
labels: ["facebook", "instagram", "meta", "social-watcher", "auto-poster", "hitl", "session-management", "content-scheduler"]
links:
  spec: specs/004-meta-social-integration/spec.md
  ticket: null
  adr: null
  pr: null
files:
  - specs/004-meta-social-integration/spec.md (created — full specification, 5 user stories, 24 FRs, 8 SCs)
  - specs/004-meta-social-integration/checklists/requirements.md (created — all items pass)
tests:
  - (no tests at spec stage)
---

## Prompt

/sp.specify

Facebook & Instagram Integration (Gold Tier)

Add Facebook and Instagram watchers and auto-posters to the Personal AI Employee system, following the same pattern as the existing LinkedIn watcher and poster.

**Facebook Watcher** (`backend/watchers/facebook_watcher.py`):
- Monitor Facebook notifications (mentions, comments, page messages)
- Monitor Facebook Messenger for keywords
- Create vault files in `vault/Needs_Action/` for actionable items
- Support `FACEBOOK_CHECK_INTERVAL`, `FACEBOOK_KEYWORDS`, `FACEBOOK_SESSION_PATH`, `FACEBOOK_HEADLESS` env vars

**Facebook Poster** (`backend/actions/facebook_poster.py`):
- Publish approved drafts with `type: facebook_post` from `vault/Approved/`
- Support image attachments via frontmatter `image_path` field
- Move to `vault/Done/` on success, `vault/Rejected/` on failure
- Respect `DEV_MODE` and `dry_run` flags

**Instagram Watcher** (`backend/watchers/instagram_watcher.py`):
- Monitor Instagram notifications (mentions, comments, DMs)
- Keyword filtering for DMs
- Create vault files in `vault/Needs_Action/`
- Support `INSTAGRAM_CHECK_INTERVAL`, `INSTAGRAM_KEYWORDS`, `INSTAGRAM_HEADLESS` env vars

**Instagram Poster** (`backend/actions/instagram_poster.py`):
- Publish approved drafts with `type: instagram_post` from `vault/Approved/`
- Validate caption ≤ 2,200 characters
- Respect `DEV_MODE` and `dry_run` flags

**Shared Meta Session** (`config/meta_session/`):
- Single Playwright session shared by all 4 components
- Session setup CLI command for manual one-time login
- Auto-detect expired sessions with graceful degradation

**Content Scheduler Extension**:
- Add `platform: facebook` and `platform: instagram` as valid topic platforms
- Set correct `type` in generated draft frontmatter
- Backward compatible with existing LinkedIn topics (default platform: linkedin)

**Orchestrator Integration**:
- Register FacebookWatcher and InstagramWatcher in `_build_watcher_configs()`
- Register `_handle_facebook_post()` and `_handle_instagram_post()` in action_executor.py

**New Skills**: `skills/social-media-manager/SKILL.md` covering all 4 platform actions

## Response snapshot

Created complete specification for Meta Social Integration (Facebook & Instagram) Gold Tier feature.

**Branch**: `004-meta-social-integration` (created by create-new-feature.ps1 with number 4)

**Spec structure**:
- 5 user stories with priorities P1–P5, each independently testable
- 24 functional requirements across 6 domains: session, FB monitoring, FB publishing, IG monitoring, IG publishing, CS extension
- 8 measurable success criteria (technology-agnostic)
- 6 edge cases (session expiry, scraping failures, empty drafts, race conditions)
- 5 key entities: MetaSession, FacebookNotification, InstagramNotification, FacebookPostDraft, InstagramPostDraft
- Assumptions section documenting backward-compat with feature 003

**Checklist**: All 12 requirements.md items pass (no NEEDS CLARIFICATION markers, all SCs measurable, no implementation details leaked).

## Outcome

- ✅ Impact: Full spec for Facebook & Instagram integration written, covering monitoring and publishing for both platforms with shared Meta session, HITL workflow, DEV_MODE safety, and Content Scheduler extension
- 🧪 Tests: No tests at spec stage; 8 measurable success criteria defined for acceptance testing
- 📁 Files: 2 files created (spec.md, checklists/requirements.md)
- 🔁 Next prompts: /sp.plan to generate architecture plan, data model, and API contracts; or /sp.clarify if any requirements need refinement
- 🧠 Reflection: The shared Meta session design (single `config/meta_session/` covering both Facebook and Instagram) is the key architectural insight — it mirrors the LinkedIn session pattern while avoiding duplicate login flows. Content Scheduler backward-compat (default platform: linkedin) prevents breaking feature 003.

## Evaluation notes (flywheel)

- Failure modes observed: PowerShell 5.1 Join-Path error in create-new-feature.ps1 (3+ path segments) — known pattern from feature 003; branch creation succeeds before the error so it is non-fatal
- Graders run and results (PASS/FAIL): Spec checklist PASS (12/12 items); no code tests at spec stage
- Prompt variant (if applicable): sp.specify with full feature description provided upfront
- Next experiment: Run /sp.plan to validate that the shared Meta session architecture is feasible before committing to it
