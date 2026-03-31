# Feature Specification: Twitter (X) Integration

**Feature Branch**: `005-twitter-x-integration`
**Created**: 2026-02-21
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Twitter Session Setup (Priority: P1)

As the AI Employee owner, I want to authenticate with Twitter/X once using a simple setup command, so that the system can access Twitter on my behalf without requiring me to log in each time.

**Why this priority**: Without a valid Twitter session, neither monitoring nor posting can operate. This foundational step must succeed before all other Twitter capabilities become available.

**Independent Test**: Run the Twitter watcher with `--setup` flag → browser opens → user logs in manually → session is saved locally → next run without `--setup` skips login and proceeds directly, confirming session persistence.

**Acceptance Scenarios**:

1. **Given** no Twitter session exists, **When** I run the Twitter watcher with `--setup`, **Then** a browser window opens for manual login and after I complete login, the session is saved to the configured session path.
2. **Given** a valid Twitter session exists, **When** the Twitter watcher starts without `--setup`, **Then** it proceeds directly to monitoring without displaying any login prompt.
3. **Given** a saved session has expired or become invalid, **When** the watcher detects the invalid state on startup, **Then** it logs an error and instructs the user to re-run with `--setup`.

---

### User Story 2 - Twitter Notification Monitoring (Priority: P2)

As the AI Employee owner, I want the system to automatically monitor my Twitter/X notifications and direct messages for relevant keywords, so that important Twitter interactions are surfaced in my vault for review without manual checking.

**Why this priority**: Monitoring incoming interactions is the perception layer of the AI Employee — it ensures the system is aware of Twitter activity around the clock. This is core to the 24/7 monitoring promise.

**Independent Test**: With DEV_MODE enabled, run the watcher → synthetic mention/DM data containing configured keywords generates action files in `vault/Needs_Action/` with `type: twitter`, verifying the full monitoring pipeline without a real browser.

**Acceptance Scenarios**:

1. **Given** a tweet mention or reply contains a keyword from TWITTER_KEYWORDS, **When** the watcher scans notifications, **Then** an action file with `type: twitter` is created in `vault/Needs_Action/` including sender handle, content excerpt, interaction type, keyword matched, and original URL.
2. **Given** a direct message contains a keyword from TWITTER_KEYWORDS, **When** the watcher scans messages, **Then** an action file is created in `vault/Needs_Action/` with DM content and sender details.
3. **Given** a notification or DM has already been processed within the 7-day deduplication window, **When** the watcher runs again, **Then** no duplicate action file is created.
4. **Given** no notifications or DMs contain matching keywords, **When** the watcher completes a cycle, **Then** no action files are created and the watcher exits cleanly.
5. **Given** DEV_MODE is enabled, **When** the watcher runs, **Then** it returns synthetic notification data without opening a real browser session.

---

### User Story 3 - Twitter Auto-Post (Priority: P3)

As the AI Employee owner, I want the system to automatically publish my approved tweet drafts to Twitter/X, so that once I approve a draft in my vault it is posted without further manual steps.

**Why this priority**: Auto-posting closes the human-in-the-loop cycle — after I review and approve a draft, the system handles publishing and records the outcome. This delivers the full value of the AI Employee content pipeline.

**Independent Test**: Place a `TWITTER_POST_*.md` file with `type: twitter_post` and content ≤ 280 characters in `vault/Approved/` → run poster in DEV_MODE → file moves to `vault/Done/` with `status: done` and `dev_mode: true`, confirming the approval-to-execution flow.

**Acceptance Scenarios**:

1. **Given** a tweet draft exists in `vault/Approved/` with `type: twitter_post` and content ≤ 280 characters, **When** the poster runs, **Then** the tweet is published to Twitter and the file moves to `vault/Done/` with `status: done` and `posted_at` timestamp.
2. **Given** a tweet draft has content exceeding 280 characters, **When** the poster evaluates the file, **Then** it rejects the draft by moving it to `vault/Rejected/` with `status: rejected` and `rejection_reason: exceeds_character_limit` — no tweet is published.
3. **Given** DEV_MODE is enabled, **When** the poster runs, **Then** no real tweet is published; the file moves to `vault/Done/` with `status: done` and `dev_mode: true` recorded.
4. **Given** no approved tweet files exist, **When** the poster runs, **Then** it exits cleanly with no errors.
5. **Given** a session error occurs during posting, **When** the poster fails, **Then** the source file remains in `vault/Approved/` unchanged and the error is recorded in the system log for investigation.

---

### User Story 4 - Content Scheduler Integration (Priority: P4)

As the AI Employee owner, I want the content scheduler to generate Twitter-optimized draft posts when I tag a topic with `[platform: twitter]` in my Content Strategy file, so that my full Twitter content pipeline runs automatically from strategy through draft to publishing.

**Why this priority**: Integrating Twitter into the content scheduler completes the end-to-end pipeline. It enables fully automated draft generation so the only human step required is reviewing and approving the draft.

**Independent Test**: Add a topic line tagged `[platform: twitter]` to `vault/Content_Strategy.md` → run content scheduler → `TWITTER_POST_{today}.md` appears in `vault/Pending_Approval/` with `type: twitter_post` and content ≤ 280 characters, ready for human review.

**Acceptance Scenarios**:

1. **Given** a topic in Content_Strategy.md includes `[platform: twitter]`, **When** the content scheduler runs, **Then** a `TWITTER_POST_{today}.md` draft is generated in `vault/Pending_Approval/` with `type: twitter_post` frontmatter.
2. **Given** a Twitter draft is generated, **When** I inspect the content, **Then** it is ≤ 280 characters, uses a casual and punchy tone, and includes relevant hashtags.
3. **Given** a Twitter draft for today already exists in Pending_Approval or Approved, **When** the scheduler runs again, **Then** no duplicate draft is created.
4. **Given** topics tagged for `linkedin`, `facebook`, and `twitter` all exist, **When** the scheduler runs, **Then** one platform-specific draft is generated per platform independently.

---

### Edge Cases

- What happens when a tweet draft is exactly 280 characters (boundary — should be accepted)?
- How does the system handle a Twitter session that expires mid-monitoring cycle?
- What if TWITTER_KEYWORDS is empty — does the watcher monitor all notifications or skip monitoring entirely?
- What if the user edits an approved draft to exceed 280 characters before the poster runs?
- What if two watcher instances run simultaneously and attempt to process the same notification?

## Requirements *(mandatory)*

### Functional Requirements

**Session Management (US1)**

- **FR-001**: The system MUST provide a `--setup` flag that opens an interactive browser window allowing the user to manually log in to Twitter/X.
- **FR-002**: The system MUST persist the authenticated browser session locally at the path configured by `TWITTER_SESSION_PATH`, so the session survives process restarts.
- **FR-003**: The system MUST detect an expired or invalid saved session on startup and alert the user to re-run the `--setup` flow.
- **FR-004**: The session storage directory MUST be listed in `.gitignore` and MUST NEVER be committed to version control.

**Notification Monitoring (US2)**

- **FR-005**: The system MUST monitor Twitter notifications (mentions, replies) and direct messages on a configurable polling interval defined by `TWITTER_CHECK_INTERVAL` (default: 300 seconds).
- **FR-006**: The system MUST filter monitored items against keywords defined in the `TWITTER_KEYWORDS` environment variable (comma-separated, case-insensitive); only matching items produce action files.
- **FR-007**: For each matching item, the system MUST create a Markdown action file in `vault/Needs_Action/` with `type: twitter` frontmatter, including: sender handle, content excerpt, interaction type (mention/reply/DM), keyword matched, original item URL, and ISO 8601 timestamp.
- **FR-008**: The system MUST prevent duplicate action files for previously processed items using a persistent deduplication store, retaining processed item IDs for 7 days.
- **FR-009**: When `DEV_MODE=true`, the system MUST return synthetic notification data without launching a real browser or accessing Twitter.

**Auto-Posting (US3)**

- **FR-010**: The system MUST scan `vault/Approved/` for files with `type: twitter_post` frontmatter.
- **FR-011**: The system MUST reject (and move to `vault/Rejected/`) any approved draft whose post content exceeds 280 characters, recording `rejection_reason: exceeds_character_limit`.
- **FR-012**: On successful posting, the system MUST move the file to `vault/Done/` with `status: done` and a `posted_at` ISO 8601 timestamp.
- **FR-013**: All tweets MUST require prior human approval — the system MUST NOT auto-approve or auto-post without a file in `vault/Approved/`.
- **FR-014**: When `DEV_MODE=true`, the system MUST simulate the full posting workflow (file moves, status updates) without publishing a real tweet, recording `dev_mode: true` in the Done file.

**Content Scheduler Integration (US4)**

- **FR-015**: The content scheduler MUST recognize `[platform: twitter]` tags within topic lines in `vault/Content_Strategy.md` and use them to select the Twitter content template.
- **FR-016**: Twitter-specific content templates MUST produce content ≤ 280 characters using casual, punchy language optimized for Twitter engagement, including relevant hashtags.
- **FR-017**: Twitter scheduler drafts MUST be saved as `TWITTER_POST_{YYYY-MM-DD}.md` in `vault/Pending_Approval/` with `type: twitter_post` and `platform: twitter` frontmatter fields.
- **FR-018**: The daily draft existence check MUST include the `TWITTER` filename prefix alongside existing `LINKEDIN` and `FACEBOOK` prefixes.

**Orchestration (Cross-Cutting)**

- **FR-019**: The orchestrator MUST include the Twitter watcher in its watcher startup configuration, using `TWITTER_CHECK_INTERVAL`, `TWITTER_KEYWORDS`, and `TWITTER_SESSION_PATH` environment variables.
- **FR-020**: The action executor MUST route `type: twitter_post` action files to the Twitter poster handler.
- **FR-021**: A skill definition MUST exist at `skills/twitter-manager/SKILL.md` documenting the Twitter Manager capability, its triggers, permissions, and DEV_MODE behavior.

### Key Entities

- **TwitterSession**: Persistent browser authentication state stored locally; attributes: storage path, validity status, last-verified timestamp.
- **TwitterActionFile**: Vault Markdown file (`type: twitter`) created in `vault/Needs_Action/`; attributes: sender handle, content excerpt, interaction type (mention/reply/DM), keyword matched, source URL, created timestamp.
- **TwitterPostDraft**: Vault Markdown file (`type: twitter_post`) flowing through Pending_Approval → Approved → Done or Rejected; attributes: post content (≤280 chars), platform, status, scheduled date, posted_at timestamp.
- **TwitterDeduplicationStore**: Persistent store tracking processed notification/DM IDs; attributes: item ID, processed timestamp, 7-day retention window.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After running `--setup` once, all subsequent watcher and poster invocations complete without requiring user login interaction.
- **SC-002**: 100% of Twitter notifications and DMs containing configured keywords are captured as vault action files within one polling cycle (≤ `TWITTER_CHECK_INTERVAL` seconds of occurrence).
- **SC-003**: Zero duplicate action files are created for items already processed within the 7-day deduplication window.
- **SC-004**: 100% of approved tweet drafts are validated for the 280-character limit before posting — drafts exceeding the limit are moved to Rejected and never published.
- **SC-005**: Scheduler-generated Twitter drafts are ≤ 280 characters in length and available in `vault/Pending_Approval/` for human review without requiring manual content editing.
- **SC-006**: In DEV_MODE, no real tweets are published and no real Twitter browser session is opened; all workflows complete successfully using synthetic data.
- **SC-007**: Test suite covers: session state detection, keyword filtering, deduplication, 280-character enforcement, DEV_MODE lifecycle for watcher and poster, content scheduler platform routing for Twitter.

## Assumptions

- Twitter/X permits browser-based session access via Playwright for reading notifications and composing tweets; no official API token is required for this integration.
- The user performs manual login once via `--setup`; the system stores only the browser session state, never raw credentials.
- `TWITTER_KEYWORDS` is a comma-separated list of case-insensitive keywords; at least one keyword must be configured for monitoring to produce action files.
- The Playwright browser runtime is already installed in the project environment from the Meta social integration (Feature 004).
- Twitter DMs and notifications are accessible from a single authenticated browser session.

## Scope

### In Scope

- Twitter/X session setup and persistence with `--setup` flag
- Notification monitoring (mentions, replies, DMs) with TWITTER_KEYWORDS filtering and deduplication
- Approved tweet publishing with 280-character validation, HITL enforcement, and DEV_MODE support
- Content scheduler `[platform: twitter]` tag support with Twitter-specific short-form templates
- Orchestrator watcher registration and ActionExecutor handler routing
- `skills/twitter-manager/SKILL.md` skill definition

### Out of Scope

- Twitter API v2 / OAuth2 developer token integration (session-based only)
- Replying to specific tweets (new posts only)
- Twitter analytics, follower tracking, or engagement metrics
- Scheduled tweet threads (multi-tweet posts)
- Image or video attachments in tweets
- WhatsApp or LinkedIn reply automation (separate features)
