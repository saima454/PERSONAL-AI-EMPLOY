---
id: "002"
title: "Twitter X Integration Plan"
stage: plan
date: "2026-02-21"
surface: agent
model: claude-sonnet-4-6
feature: 005-twitter-x-integration
branch: 005-twitter-x-integration
user: PMLS
command: /sp.plan
labels: ["twitter", "playwright", "architecture", "data-model", "dom-selectors", "content-scheduler", "orchestrator"]
links:
  spec: specs/005-twitter-x-integration/spec.md
  ticket: "null"
  adr: "null"
  pr: "null"
files:
  - specs/005-twitter-x-integration/plan.md
  - specs/005-twitter-x-integration/research.md
  - specs/005-twitter-x-integration/data-model.md
  - specs/005-twitter-x-integration/quickstart.md
tests:
  - "null"
---

## Prompt

/sp.plan

## Response snapshot

Ran `setup-plan.ps1` → branch `005-twitter-x-integration`, FEATURE_SPEC and IMPL_PLAN paths confirmed.

Read existing codebase (FacebookWatcher, FacebookPoster, orchestrator._build_watcher_configs(), action_executor.HANDLERS, content_scheduler.Topic, post_generator.py, schedule_manager.draft_exists_today()) to extract exact patterns for Twitter to follow.

**Phase 0 — research.md** (10 decisions):
- D1: Use x.com (not twitter.com) for all navigation URLs
- D2: Playwright persistent context at config/twitter_session/ (separate from config/meta_session/)
- D3: DOM selector strategy — data-testid primary, URL-based fast-path; research agent confirmed notification selector = `article[data-testid="notification"]`, DM = `[data-testid="conversationItem"]`; auth detection = `[data-testid="AppTabBar_Home_Link"]`
- D4: DEV_MODE returns synthetic item dict without browser launch
- D5: 280-char limit enforced in poster (hard reject, no truncation) + template authoring constraint; post_generator emergency truncation as fallback
- D6: 5 Twitter templates (one per topic), format_type="twitter_short", ≤280 chars
- D7: Dedup key = `sender|text[:100]|timestamp` → vault/Logs/processed_twitter.json (7-day retention)
- D8: Orchestrator add `_twitter_factory()` following exact facebook_factory pattern
- D9: ContentScheduler already generic — only templates + TWITTER prefix + schedule_manager update needed
- D10: Four new env vars: TWITTER_CHECK_INTERVAL, TWITTER_KEYWORDS, TWITTER_SESSION_PATH, TWITTER_HEADLESS

**Phase 1 — data-model.md**: 5 entities (TwitterSession, TwitterActionFile, TwitterPostDraft, TwitterDeduplicationStore, TwitterTemplate) with field tables, state transitions, relationships diagram.

**Phase 1 — quickstart.md**: 7 scenarios covering: setup, DEV_MODE watcher, real-mode watcher, DEV_MODE poster, char-limit rejection, scheduler integration, full HITL loop.

**Phase 1 — plan.md**: Full technical plan with Architecture Design (class skeletons), implementation order (4 phases: new files → modifications → tests → validation), test plan (7 classes, ~59 tests), constitution check (all 8 principles PASS).

**Agent context**: Updated CLAUDE.md via update-agent-context.ps1.

## Outcome

- ✅ Impact: Feature 005 plan is complete. 4 artifacts created (plan.md, research.md, data-model.md, quickstart.md). Constitution check: all 8 principles pass. Implementation follows Feature 004 patterns exactly — minimal cognitive overhead.
- 🧪 Tests: Not applicable (planning phase).
- 📁 Files: 4 files created/modified — research.md, data-model.md, quickstart.md, plan.md (updated from template)
- 🔁 Next prompts: `/sp.tasks` to generate the task breakdown in tasks.md, then `/sp.implement`
- 🧠 Reflection: TwitterPoster is simpler than FacebookPoster — Twitter home page auto-focuses the tweet textarea so no "click composer trigger" step is needed. The existing ContentScheduler platform routing requires zero changes (already generic); only templates + TWITTER prefix need adding.

## Evaluation notes (flywheel)

- Failure modes observed: Research agent returned `article[data-testid="notification"]` as primary notification selector (not `article[data-testid="tweet"]` as initially assumed) — research.md updated accordingly. Selector cascades protect against future changes.
- Graders run and results (PASS/FAIL): Constitution check 8/8 PASS; plan.md completeness PASS
- Prompt variant (if applicable): standard /sp.plan flow
- Next experiment (smallest change to try): Run /sp.tasks and verify 7 test classes (session, watcher, poster, dedup, templates, scheduler, action-executor) generate with correct task IDs and [P] markers

📋 Architectural decision detected: Separate Twitter session from Meta session (config/twitter_session/ vs config/meta_session/) — each platform gets its own Playwright persistent context directory. Document reasoning? Run `/sp.adr twitter-session-isolation`
