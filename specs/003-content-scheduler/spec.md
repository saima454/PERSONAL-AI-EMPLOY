# Feature Specification: Smart Content Scheduler

**Feature Branch**: `003-content-scheduler`
**Created**: 2026-02-20
**Status**: Draft
**Input**: User description: "Smart Content Scheduler (Gold Tier) — automatically generates LinkedIn post drafts from predefined topics, schedules them, and posts approved content via HITL workflow."

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Define Strategy Once, Get Daily Drafts (Priority: P1)

As Taha (Agentic AI & Senior Backend Engineer), I want to define my content topics and posting rules once in a single file, and have the system automatically generate a ready-to-review LinkedIn post draft each day at my preferred time — so I never have to stare at a blank page.

**Why this priority**: This is the core value proposition. Without automated draft generation, nothing else in the feature works. It eliminates the daily friction of content creation.

**Independent Test**: Can be fully tested by populating `vault/Content_Strategy.md` with topics and running the scheduler manually — a draft appears in `vault/Pending_Approval/` ready for review, without any further input.

**Acceptance Scenarios**:

1. **Given** `vault/Content_Strategy.md` exists with at least one topic, **When** the scheduler runs (manually or on schedule), **Then** a LinkedIn post draft is saved to `vault/Pending_Approval/LINKEDIN_POST_{date}.md` with valid frontmatter and post body.
2. **Given** a draft already exists for today, **When** the scheduler runs again, **Then** no duplicate draft is created and the scheduler exits gracefully.
3. **Given** `vault/Content_Strategy.md` is missing or empty, **When** the scheduler runs, **Then** the system logs a clear error and does not crash.

---

### User Story 2 - Topic Rotation Without Repetition (Priority: P2)

As Taha, I want the system to rotate through my defined topics automatically — never repeating the same topic two days in a row — so my LinkedIn feed stays varied and engaging.

**Why this priority**: Repeated topics reduce audience engagement. Rotation is core to a credible content strategy and directly referenced in the content rules.

**Independent Test**: Can be tested by running the scheduler 6 days in a row with 5 topics defined — each day selects a different topic, and the cycle restarts correctly on day 6.

**Acceptance Scenarios**:

1. **Given** the last posted topic was "AI and Automation", **When** the scheduler runs next, **Then** any topic except "AI and Automation" is selected.
2. **Given** all 5 topics have been posted once each, **When** the scheduler runs for the 6th time, **Then** the rotation restarts from the beginning (excluding yesterday's topic).
3. **Given** `vault/Logs/posted_topics.json` is missing, **When** the scheduler runs, **Then** it creates a new history file and starts with the first topic.

---

### User Story 3 - CLI Control: Generate Now, Preview, Status (Priority: P3)

As Taha, I want command-line control to force-generate a post immediately, preview what would be generated without saving, or check the current schedule status — so I have full visibility and control outside the normal schedule.

**Why this priority**: Enables operational control, testing, and manual overrides without modifying schedule files.

**Independent Test**: Can be fully tested by running the scheduler CLI with `--generate-now`, `--preview`, and `--status` flags and confirming correct output for each.

**Acceptance Scenarios**:

1. **Given** the scheduler, **When** run with `--generate-now`, **Then** a draft is generated immediately regardless of whether one already exists today.
2. **Given** the scheduler, **When** run with `--preview`, **Then** the draft content is printed to the terminal and NO file is written to `vault/Pending_Approval/`.
3. **Given** the scheduler, **When** run with `--status`, **Then** the output shows: last post date, last topic, next scheduled topic, next run time, and posts generated today.

---

### User Story 4 - Orchestrator Integration on Startup (Priority: P4)

As Taha, I want the orchestrator to automatically check on startup whether a content post is due today — and generate a draft if so — so the whole system runs hands-free without me manually invoking the scheduler.

**Why this priority**: Closes the automation loop. The orchestrator already manages all other watchers; the content scheduler should follow the same pattern.

**Independent Test**: Can be tested by starting the orchestrator and verifying that if today's draft is missing and the schedule says it's due, a draft appears in `vault/Pending_Approval/` without any manual action.

**Acceptance Scenarios**:

1. **Given** the orchestrator starts and today's post is due and no draft exists yet, **When** startup completes, **Then** a draft is generated and saved to `vault/Pending_Approval/`.
2. **Given** the orchestrator starts and a draft already exists for today, **When** startup completes, **Then** no duplicate is created and the orchestrator logs that today's post is already prepared.
3. **Given** the scheduler fails during orchestrator startup (e.g., strategy file missing), **When** the error occurs, **Then** the orchestrator continues starting normally and logs a warning — it does not crash.

---

### User Story 5 - Approved Draft Auto-Published to LinkedIn (Priority: P5)

As Taha, I want an approved draft from `vault/Approved/` to be automatically posted to LinkedIn by the action executor — so the full loop from draft to published post is handled without me manually triggering the LinkedIn poster.

**Why this priority**: Completes the end-to-end flow. The HITL approval is already in place; this story closes the final mile.

**Independent Test**: Can be tested by placing a correctly frontmatted `LINKEDIN_POST_*.md` file in `vault/Approved/` and confirming the action executor detects, processes, and moves it to `vault/Done/`.

**Acceptance Scenarios**:

1. **Given** a draft in `vault/Approved/LINKEDIN_POST_{date}.md` with `action_type: linkedin_post`, **When** the action executor polls, **Then** it invokes the LinkedIn poster, moves the file to `vault/Done/`, and logs the result with timestamp.
2. **Given** `DEV_MODE=true`, **When** the action executor processes a LinkedIn post, **Then** it logs "DEV_MODE: would post to LinkedIn" and moves the file to `vault/Done/` without any real browser call.
3. **Given** the LinkedIn poster fails (session expired, network error), **When** the action fails, **Then** the file remains in `vault/Approved/` (not lost), an error is logged, and a retry can be attempted on the next poll.

---

### Edge Cases

- What happens when `vault/Content_Strategy.md` frontmatter is malformed (invalid YAML)?
- What if the generated post exceeds the 1300-character limit after template filling?
- What if the scheduler is invoked twice simultaneously (race condition on log file)?
- What happens when `posting_schedule.json` is corrupted or has unexpected fields?
- What if `vault/Pending_Approval/` already has a post for today from a previous `--generate-now`?
- How does `CONTENT_SKIP_WEEKENDS=true` interact with the rotation counter — does a skipped day count as "posted"?
- What if all templates for the selected topic produce posts over the character limit?

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST read posting strategy (topics, rules, frequency, tone) from `vault/Content_Strategy.md` on every run.
- **FR-002**: System MUST track post history in `vault/Logs/posted_topics.json`, recording date and topic for each generated draft.
- **FR-003**: System MUST select the next topic using rotation logic, ensuring the same topic is not selected on consecutive days.
- **FR-004**: System MUST generate a post draft from templates, respecting all rules in `vault/Content_Strategy.md` (character limit, hashtag count, question requirement, tone).
- **FR-005**: System MUST save the generated draft to `vault/Pending_Approval/LINKEDIN_POST_{YYYY-MM-DD}.md` with YAML frontmatter including `action_type: linkedin_post`, `status: pending_approval`, `topic`, `generated_at`, and `scheduled_date`.
- **FR-006**: System MUST skip draft generation if a file named `LINKEDIN_POST_{today}.md` already exists in `vault/Pending_Approval/` or `vault/Approved/` (idempotency guard).
- **FR-007**: System MUST log all scheduler actions (topic selected, draft saved path, skip reason) to `vault/Logs/` with ISO 8601 timestamps.
- **FR-008**: System MUST support `--generate-now` CLI flag to force draft generation regardless of schedule or existing drafts.
- **FR-009**: System MUST support `--preview` CLI flag to print generated content to stdout without writing any files.
- **FR-010**: System MUST support `--status` CLI flag to display: last post date, last topic, next scheduled topic, and whether a post is due today.
- **FR-011**: System MUST read context from `vault/Company_Handbook.md` and `vault/Business_Goals.md` when available to align post tone and relevance.
- **FR-012**: System MUST track scheduling state in `vault/Logs/posting_schedule.json` with: last run date, last topic index, frequency mode, and skip-weekend setting.
- **FR-013**: System MUST support `daily`, `weekdays_only`, and `custom_days` post frequency modes.
- **FR-014**: System MUST respect `CONTENT_SKIP_WEEKENDS` environment variable — when true, no draft is generated on Saturday or Sunday.
- **FR-015**: The orchestrator MUST check at startup whether a content post is due and invoke the scheduler if so.
- **FR-016**: The action executor MUST detect `action_type: linkedin_post` in `vault/Approved/` and route to the LinkedIn poster skill.
- **FR-017**: When `DEV_MODE=true`, the action executor MUST log the would-be LinkedIn post action without making any real network or browser calls.
- **FR-018**: Post templates MUST include variety across at least 5 formats: tips/how-to, personal insight, question/poll, story/experience, and announcement.
- **FR-019**: System MUST provide at least 5 templates per topic category (minimum 25 templates total across 5 topics).
- **FR-020**: Every generated post MUST stay within 1300 characters including hashtags; the generator MUST truncate or retry with a shorter template if the limit is exceeded.

### Key Entities

- **ContentStrategy**: The user's intent — topics list, content rules (character limit, hashtag count, tone, restrictions), posting frequency, preferred time, and timezone. Source of truth: `vault/Content_Strategy.md`.
- **PostDraft**: A generated LinkedIn post ready for human review — contains post body, topic, hashtags, character count, template used, and generated timestamp. Persisted as a Markdown file with YAML frontmatter in `vault/Pending_Approval/`.
- **PostingHistory**: Log of past draft generations — maps dates to topics for rotation tracking. Persisted as `vault/Logs/posted_topics.json`.
- **ScheduleState**: Operational state — last run date, next due date, current topic index, frequency mode. Persisted as `vault/Logs/posting_schedule.json`.
- **PostTemplate**: A reusable content pattern with format type (tip, story, question, etc.), placeholders `{insight}`, `{question}`, `{hashtags}`, and topic affinity. Defined as in-code data structures within the post generator.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A unique LinkedIn post draft is available in `vault/Pending_Approval/` within 5 seconds of the scheduler running.
- **SC-002**: Topic rotation works correctly across 10 consecutive runs — no topic repeats on back-to-back days, full cycle completes before restart.
- **SC-003**: All 25+ templates produce posts within the 1300-character limit — verified by automated test suite.
- **SC-004**: The scheduler never generates a duplicate draft for the same calendar day when run 3× consecutively (idempotency verified).
- **SC-005**: The orchestrator startup time increases by less than 2 seconds when the content scheduler check is integrated.
- **SC-006**: CLI `--status` output is returned in under 1 second.
- **SC-007**: 100% of approved `LINKEDIN_POST_*.md` files in `vault/Approved/` are processed by the action executor within one polling cycle (default 30-second interval).
- **SC-008**: `DEV_MODE=true` produces zero real LinkedIn browser/API calls — verified by full end-to-end run with no browser session present.
- **SC-009**: At least 25 distinct post templates exist (5 per topic × 5 topics), each passing format validation.
- **SC-010**: All scheduler operations produce structured log entries in `vault/Logs/` — zero silent failures across 20 consecutive test runs.

---

## Assumptions

- `vault/Company_Handbook.md` and `vault/Business_Goals.md` may or may not exist; if missing, the generator falls back to topic-only templates gracefully.
- The LinkedIn poster skill (`skills/linkedin-poster/`) and its Playwright session are already functional — this feature depends on them for the action leg but does not re-implement them.
- The action executor in `backend/orchestrator/action_executor.py` is operational and needs only `linkedin_post` routing added.
- Template-based generation (not a live LLM API call) is the chosen approach — keeps the scheduler fast, deterministic, and runnable without API keys.
- The user persona is "Taha — Agentic AI & Senior Backend Engineer" — templates are pre-authored with this persona baked in.
- `vault/Logs/` directory exists and is writable; the scheduler creates subdirectory files as needed.
- Default timezone is `Asia/Karachi` (UTC+5) unless overridden by `CONTENT_TIMEZONE` env var.
- Single-user, single LinkedIn account scope.

---

## Out of Scope

- Live LLM API calls during draft generation (template-based only for this tier).
- Multi-platform posting (Twitter/X, Instagram, etc.) — LinkedIn only.
- Image or media attachments to posts.
- Post analytics or engagement tracking after publishing.
- Scheduling posts to publish at a future time directly on LinkedIn.
- Multi-user or multi-account support.
- A GUI for managing content strategy (Obsidian vault is the management UI).

---

## Dependencies

- `skills/linkedin-poster/` — must be functional for P5 (approved post publishing).
- `backend/orchestrator/action_executor.py` — needs `linkedin_post` routing added (P4/P5).
- `backend/orchestrator/orchestrator.py` — needs startup scheduler check added (P4).
- `vault/Content_Strategy.md` — must be created and populated by user before first run.
- `config/.env` — must include `CONTENT_POST_FREQUENCY`, `CONTENT_POST_TIME`, `CONTENT_TIMEZONE`, `CONTENT_SKIP_WEEKENDS`.
- `zoneinfo` (Python 3.9+ stdlib) for timezone handling.
