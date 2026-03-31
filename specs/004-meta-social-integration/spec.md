# Feature Specification: Meta Social Integration (Facebook & Instagram)

**Feature Branch**: `004-meta-social-integration`
**Created**: 2026-02-20
**Status**: Draft
**Tier**: Gold

## Overview

Extend the Personal AI Employee with Facebook and Instagram awareness and publishing capabilities. The system monitors both platforms for notifications, messages, and mentions, surfaces actionable items in the Obsidian vault for human review, and publishes approved social media drafts to Facebook and Instagram on behalf of the user. Both platforms share a single Meta authentication session to minimize login overhead.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Meta Session Setup (Priority: P1)

As the AI Employee operator, I want to establish and persist a shared Meta (Facebook + Instagram) browser session so the system can interact with both platforms without requiring repeated manual logins.

**Why this priority**: All subsequent Facebook and Instagram functionality depends on an authenticated session being available. Without a working session, watchers cannot poll and posters cannot publish.

**Independent Test**: Operator runs a session-setup command, authenticates manually once in a visible browser, and verifies that a session file is saved at `config/meta_session/`. On the next cold start, the system reuses the saved session without prompting for credentials.

**Acceptance Scenarios**:

1. **Given** no saved Meta session exists, **When** the operator runs the session-setup command, **Then** a browser window opens allowing manual Facebook login, and upon completion a session file is persisted to `config/meta_session/`.

2. **Given** a valid saved session exists, **When** the system starts, **Then** the system reuses the saved session without opening a login prompt, and both Facebook and Instagram are accessible.

3. **Given** a saved session that has expired or been invalidated, **When** the system attempts to use it, **Then** the system logs a warning `"Meta session expired — re-run setup"` and gracefully skips all Meta-dependent watchers and posters rather than crashing.

4. **Given** `DEV_MODE=true`, **When** any Meta operation runs, **Then** no real browser interaction occurs; operations log `[DEV_MODE]` and return mock data.

---

### User Story 2 - Facebook Monitoring (Priority: P2)

As the AI Employee operator, I want the system to periodically check my Facebook account for new notifications (mentions, comments, page messages) and surface actionable items in the Obsidian vault so I can review and respond via the HITL workflow.

**Why this priority**: Passive monitoring of Facebook is high-value and non-destructive. It enables responsiveness without any posting risk, making it a safe early milestone after session setup.

**Independent Test**: With a live Meta session, trigger a Facebook notification (e.g., a comment on a post). Within the next polling cycle, verify that a markdown file appears in `vault/Needs_Action/` with the source, content, and a suggested response.

**Acceptance Scenarios**:

1. **Given** a valid Meta session and new Facebook notifications exist, **When** the watcher polling cycle runs, **Then** each unread notification is captured as a markdown file in `vault/Inbox/` or `vault/Needs_Action/` with fields: platform (`facebook`), notification type, sender, content excerpt, and timestamp.

2. **Given** a Facebook Messenger message matching a configured keyword, **When** the watcher runs, **Then** a vault file is created with the full message content and a `needs_reply: true` flag.

3. **Given** notifications were already captured in a previous cycle, **When** the watcher runs again, **Then** duplicate vault files are NOT created for the same notification (deduplication by notification ID).

4. **Given** the Meta session is expired, **When** the watcher attempts to poll, **Then** it logs a warning and skips without raising an unhandled exception.

5. **Given** `DEV_MODE=true`, **When** the watcher runs, **Then** it creates one synthetic vault file with `[DEV_MODE]` in the title and does not open a real browser.

---

### User Story 3 - Facebook Auto-Post (Priority: P3)

As the AI Employee operator, I want drafts placed in `vault/Approved/` with `type: facebook_post` to be automatically published to my Facebook profile or page, completing the HITL publish loop.

**Why this priority**: Publishing is higher-risk than monitoring and requires the HITL approval step to be well-exercised first. Comes after monitoring (P2) to ensure the vault workflow is established before adding publish actions.

**Independent Test**: Place a markdown file with `type: facebook_post` and `status: pending_approval` in `vault/Approved/`. Start the action executor. Verify the post is published (or logged as `[DEV_MODE]` publish) and the file is moved to `vault/Done/`.

**Acceptance Scenarios**:

1. **Given** a file in `vault/Approved/` with `type: facebook_post`, **When** the action executor processes it, **Then** the post body is extracted from the file content and submitted to Facebook, and the file is moved to `vault/Done/`.

2. **Given** `DEV_MODE=true` or `dry_run=true`, **When** the action executor processes a `facebook_post` file, **Then** the post is NOT submitted to Facebook; instead a `[DEV_MODE] Would post to Facebook` log entry is written and the file is moved to `vault/Done/`.

3. **Given** a Facebook post draft that exceeds platform character limits, **When** the action executor processes it, **Then** it logs a validation error, moves the file to `vault/Rejected/`, and does NOT post to Facebook.

4. **Given** a Facebook post with an image attachment path in the frontmatter, **When** the action executor processes it, **Then** the image is uploaded alongside the post text.

5. **Given** a transient Facebook API error during publishing, **When** the action executor encounters it, **Then** it retries once after a short delay before marking the file as failed and moving it to `vault/Rejected/`.

---

### User Story 4 - Instagram Monitoring (Priority: P4)

As the AI Employee operator, I want the system to periodically check my Instagram account for new notifications (mentions, comments, DMs) and surface actionable items in the Obsidian vault using the same HITL workflow as Facebook.

**Why this priority**: Mirrors Facebook Monitoring (P2) but for Instagram. Lower priority because Facebook monitoring is the foundational pattern; Instagram uses the same session and vault workflow, reducing incremental risk.

**Independent Test**: With a live Meta session linked to an Instagram account, trigger an Instagram mention or DM. Verify that within the next polling cycle a vault file appears with `platform: instagram` and the correct content.

**Acceptance Scenarios**:

1. **Given** a valid Meta session with Instagram access and new Instagram notifications exist, **When** the watcher polling cycle runs, **Then** each unread notification is captured as a markdown file in `vault/Inbox/` or `vault/Needs_Action/` with fields: platform (`instagram`), notification type, sender handle, content excerpt, and timestamp.

2. **Given** an Instagram Direct Message matching a configured keyword, **When** the watcher runs, **Then** a vault file is created with `needs_reply: true` and the full message content.

3. **Given** notifications already captured in a prior cycle, **When** the watcher runs again, **Then** no duplicate vault files are created (deduplication by notification ID).

4. **Given** Instagram changes its notification structure (flaky scraping), **When** the watcher encounters a parsing error, **Then** it logs a structured warning with the raw element and continues rather than crashing.

5. **Given** `DEV_MODE=true`, **When** the watcher runs, **Then** one synthetic Instagram vault file is created with `[DEV_MODE]` in the title and no real browser interaction occurs.

---

### User Story 5 - Content Scheduler Integration (Priority: P5)

As the AI Employee operator, I want the existing Content Scheduler to generate Facebook and Instagram post drafts alongside LinkedIn drafts, so I can manage all social media from the same Obsidian-based HITL workflow.

**Why this priority**: Builds on the proven LinkedIn Content Scheduler (feature 003). Lower priority as it requires both the Content Scheduler and the posting infrastructure (P3) to be working first.

**Independent Test**: Configure the Content Scheduler strategy file with a Facebook or Instagram topic. Run `python -m backend.scheduler.content_scheduler --generate-now`. Verify a draft file appears in `vault/Pending_Approval/` with `type: facebook_post` or `type: instagram_post` and valid frontmatter.

**Acceptance Scenarios**:

1. **Given** the Content Strategy file includes a topic with `platform: facebook`, **When** the Content Scheduler generates a draft, **Then** a markdown file is created in `vault/Pending_Approval/` with `type: facebook_post` and a character count appropriate for Facebook (≤ 63,206 characters).

2. **Given** the Content Strategy file includes a topic with `platform: instagram`, **When** the Content Scheduler generates a draft, **Then** a markdown file is created with `type: instagram_post` and character count ≤ 2,200 characters (Instagram caption limit).

3. **Given** both LinkedIn and Facebook topics in the strategy, **When** the scheduler runs, **Then** today's scheduled topic is selected by round-robin rotation and the correct `type` is set in the draft frontmatter.

4. **Given** a draft with `type: instagram_post` is approved and moved to `vault/Approved/`, **When** the action executor processes it, **Then** it is posted to Instagram via the Instagram poster.

---

### Edge Cases

- What happens when the Meta session cookie store becomes corrupted? System detects cookie parse error, logs a structured error, and skips all Meta watchers for this cycle without crashing.
- What happens when Facebook or Instagram changes their page structure between releases? Watchers log a `scraping_error` with the raw HTML element for debugging, skip the malformed notification, and continue processing remaining items.
- What happens when a post draft has no body content (empty file after frontmatter)? Action executor logs a validation error, moves the file to `vault/Rejected/`, and does not publish.
- What happens if both a Facebook watcher and Instagram watcher encounter the same Meta session expiry simultaneously? Each watcher independently detects the expiry, logs its own warning, and skips; the system does not deadlock waiting on a shared resource.
- What happens when the vault `Approved/` directory contains a `facebook_post` file while `DEV_MODE` is toggled off mid-run? The dry_run and dev_mode flags are read at process startup and do not change mid-run; the executor uses the flag values from when it was started.
- What happens if the image path specified in a Facebook post frontmatter does not exist? The executor logs a file-not-found error, moves the post to `vault/Rejected/`, and does not attempt to publish a post without its attachment.

---

## Requirements *(mandatory)*

### Functional Requirements

**Session Management**

- **FR-001**: System MUST provide a CLI command to establish and persist a Meta (Facebook + Instagram) authentication session to `config/meta_session/` that works without code changes.
- **FR-002**: System MUST detect when a saved Meta session has expired and emit a human-readable warning rather than crashing.
- **FR-003**: System MUST reuse a saved Meta session across process restarts without requiring the user to log in again.
- **FR-004**: System MUST operate with `DEV_MODE=true` (no real browser interactions) by default; real interactions require explicit opt-out.

**Facebook Monitoring**

- **FR-005**: System MUST poll Facebook for new notifications (mentions, comments, page messages) at a configurable interval (default: 120 seconds).
- **FR-006**: System MUST create a structured markdown vault file for each unread Facebook notification containing: platform, notification type, sender, content excerpt, and ISO 8601 timestamp.
- **FR-007**: System MUST deduplicate Facebook notifications by notification ID; the same notification MUST NOT produce more than one vault file per run.
- **FR-008**: System MUST support keyword filtering for Facebook Messenger messages, creating vault files only for messages matching configured keywords (empty = capture all).

**Facebook Publishing**

- **FR-009**: System MUST publish the text body of any vault file in `vault/Approved/` with `type: facebook_post` to the authenticated Facebook account.
- **FR-010**: System MUST support optional image attachment for Facebook posts when an image file path is provided in the draft frontmatter.
- **FR-011**: System MUST validate Facebook post character count before publishing and reject drafts that exceed the platform limit.
- **FR-012**: System MUST move successfully published Facebook post files to `vault/Done/` and failed files to `vault/Rejected/`.

**Instagram Monitoring**

- **FR-013**: System MUST poll Instagram for new notifications (mentions, comments, DMs) at a configurable interval (default: 60 seconds).
- **FR-014**: System MUST create a structured markdown vault file for each unread Instagram notification with the same fields as Facebook notifications plus `platform: instagram`.
- **FR-015**: System MUST deduplicate Instagram notifications by notification ID.
- **FR-016**: System MUST support keyword filtering for Instagram DMs.

**Instagram Publishing**

- **FR-017**: System MUST publish the caption body of any vault file in `vault/Approved/` with `type: instagram_post` to the authenticated Instagram account.
- **FR-018**: System MUST validate Instagram caption character count (≤ 2,200) before publishing and reject over-limit drafts.
- **FR-019**: System MUST move successfully published Instagram post files to `vault/Done/` and failed files to `vault/Rejected/`.

**Content Scheduler Extension**

- **FR-020**: The Content Scheduler MUST support `platform: facebook` and `platform: instagram` as valid topic platform values in the strategy file.
- **FR-021**: The Content Scheduler MUST set `type: facebook_post` or `type: instagram_post` in generated draft frontmatter based on the topic's configured platform.
- **FR-022**: The Content Scheduler's topic rotation MUST work correctly when the strategy file contains a mix of LinkedIn, Facebook, and Instagram topics.

**Orchestrator Integration**

- **FR-023**: The orchestrator MUST start a Facebook watcher and an Instagram watcher as concurrent async tasks alongside existing watchers, with the same restart-on-failure behavior.
- **FR-024**: All new watchers and posters MUST respect the `DEV_MODE` and `dry_run` flags from the orchestrator configuration.

### Key Entities

- **MetaSession**: Represents a persisted authentication state for the Meta platform (Facebook + Instagram). Attributes: session file path, last-verified timestamp, account identifier. Used by both Facebook and Instagram watchers and posters.
- **FacebookNotification**: A captured Facebook event (mention, comment, Messenger message, page notification). Attributes: notification ID, type, sender name, content excerpt, URL, timestamp, keyword-matched flag.
- **InstagramNotification**: A captured Instagram event (mention, comment, Direct Message). Attributes: notification ID, type, sender handle, content excerpt, timestamp, keyword-matched flag.
- **FacebookPostDraft**: An approved vault file targeting Facebook. Attributes: `type: facebook_post`, post body, optional image path, character count, status.
- **InstagramPostDraft**: An approved vault file targeting Instagram. Attributes: `type: instagram_post`, caption body, optional image path, character count (≤ 2,200), status.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new Meta session can be established and verified end-to-end in under 5 minutes of human interaction (excluding manual login time at the browser).
- **SC-002**: After session setup, the system reuses the saved session on the next 3 consecutive cold starts without prompting for credentials.
- **SC-003**: Facebook and Instagram watchers detect and vault a new notification within 2 polling cycles of it appearing on the platform (under normal network conditions).
- **SC-004**: Zero duplicate vault files are created for the same notification across 10 consecutive polling cycles.
- **SC-005**: A `facebook_post` or `instagram_post` draft placed in `vault/Approved/` is published and moved to `vault/Done/` within 60 seconds of the action executor's next cycle.
- **SC-006**: In `DEV_MODE=true`, all watchers and posters complete their cycle without opening a real browser, confirmed by zero browser process spawns.
- **SC-007**: The full test suite (including Meta Social Integration tests) passes with zero regressions against the existing 351-test baseline.
- **SC-008**: Character count validation prevents over-limit drafts from being published in 100% of test cases.

---

## Assumptions

- The operator's Facebook account is a personal profile or page accessible via the Meta login used during session setup. Business Suite accounts require the same credentials.
- Instagram is linked to the same Facebook account and accessible via Meta's unified session.
- The Content Strategy file format from feature 003 is extended with an optional `platform` field per topic; omitting `platform` defaults to `linkedin` for backward compatibility.
- Playwright is already available as a project dependency (used by the existing LinkedIn watcher and poster).
- Rate limits applied: Facebook check max 10 notifications/cycle, Instagram check max 10 notifications/cycle, consistent with the constitution's social media rate limit of 5 posts/day/platform.
- The action executor already routes by `type` field in frontmatter (confirmed: `fm.get("type")` pattern in action_executor.py:81).
