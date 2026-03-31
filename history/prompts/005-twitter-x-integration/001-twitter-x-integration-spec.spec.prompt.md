---
id: "001"
title: "Twitter X Integration Spec"
stage: spec
date: "2026-02-21"
surface: agent
model: claude-sonnet-4-6
feature: 005-twitter-x-integration
branch: 005-twitter-x-integration
user: PMLS
command: /sp.specify
labels: ["twitter", "playwright", "watcher", "poster", "content-scheduler", "hitl", "session-management"]
links:
  spec: specs/005-twitter-x-integration/spec.md
  ticket: "null"
  adr: "null"
  pr: "null"
files:
  - specs/005-twitter-x-integration/spec.md
  - specs/005-twitter-x-integration/checklists/requirements.md
tests:
  - "null"
---

## Prompt

/sp.specify Twitter (X) Integration (Gold Tier) — Playwright-based watcher and auto-poster for Twitter/X. Part 1: TwitterWatcher monitors notifications, mentions, replies, and DMs using keywords from TWITTER_KEYWORDS env var; creates action files in vault/Needs_Action/ with type: twitter. Part 2: TwitterPoster reads approved posts from vault/Approved/ (type: twitter_post), navigates to Twitter via Playwright, composes and posts a tweet (max 280 chars), moves file to vault/Done/. Session stored at config/twitter_session/ using Playwright persistent context. Includes --setup flag for manual login. Content Scheduler integration adds Twitter-specific templates (short, punchy, max 280 chars, casual tone, hashtag-focused) and supports [platform: twitter] topic tag. All tweets require HITL approval. Orchestrator and ActionExecutor extended to include Twitter watcher/poster. TWITTER_CHECK_INTERVAL=300, TWITTER_KEYWORDS=urgent,help,project,collab,opportunity,mention, TWITTER_SESSION_PATH=config/twitter_session, TWITTER_HEADLESS=false. New files: backend/watchers/twitter_watcher.py, backend/actions/twitter_poster.py, skills/twitter-manager/SKILL.md.

## Response snapshot

Created branch `005-twitter-x-integration` and wrote complete spec.md for Feature 005: Twitter (X) Integration.

**Spec structure:**
- US1 (P1): Twitter Session Setup — `--setup` flag, persistent context at TWITTER_SESSION_PATH, session expiry detection
- US2 (P2): Twitter Notification Monitoring — notifications + DMs, TWITTER_KEYWORDS filtering, vault/Needs_Action/ action files (type: twitter), 7-day dedup, DEV_MODE synthetic data
- US3 (P3): Twitter Auto-Post — vault/Approved/ scan (type: twitter_post), 280-char enforcement (reject if exceeded), HITL required, vault/Done/ on success, DEV_MODE lifecycle
- US4 (P4): Content Scheduler Integration — `[platform: twitter]` tag in Content_Strategy.md, TWITTER_POST_{today}.md, ≤280 char casual templates, draft_exists_today() extended

**21 functional requirements** across session management, monitoring, posting, scheduler integration, and orchestration.
**7 success criteria** — all measurable and technology-agnostic.
**4 key entities**: TwitterSession, TwitterActionFile, TwitterPostDraft, TwitterDeduplicationStore.

Checklist: all 14 items [X] — spec passes quality validation.

## Outcome

- ✅ Impact: Feature 005 spec is complete and ready for planning. All 4 user stories are independently testable, cover the full Twitter pipeline from session setup through content generation to publishing.
- 🧪 Tests: No tests at spec stage (pre-implementation).
- 📁 Files: 2 files created — specs/005-twitter-x-integration/spec.md, specs/005-twitter-x-integration/checklists/requirements.md
- 🔁 Next prompts: `/sp.plan` to generate architecture plan, data model, and research artifacts for Feature 005
- 🧠 Reflection: Key constraint is the 280-character limit — it flows from FR-016 (template generation) through FR-011 (posting validation) and SC-004/SC-005 (success criteria). The [platform: twitter] scheduler integration mirrors the existing Facebook/Instagram pattern from Feature 004.

## Evaluation notes (flywheel)

- Failure modes observed: create-new-feature.ps1 errored on `-Description` named parameter (positional arg expected), but branch and spec.md were still created successfully; PHR bash script not present (used agent-native write instead)
- Graders run and results (PASS/FAIL): Checklist validation PASS (14/14 items)
- Prompt variant (if applicable): continued from compacted session
- Next experiment (smallest change to try): Run `/sp.plan` and verify research.md resolves Playwright selector patterns for Twitter notification tabs vs. DM inbox
