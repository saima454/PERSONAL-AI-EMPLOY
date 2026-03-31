# Tasks: Email MCP Server

**Input**: Design documents from `/specs/001-email-mcp-server/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/mcp-tools.md

**Tests**: Included per user story — constitution requires minimum 70% coverage for core modules.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add MCP dependency and create package structure

- [x] T001 Add `mcp[cli]>=1.26.0` to `dependencies` in `pyproject.toml` and run `uv lock` to update the lockfile
- [x] T002 Create `backend/mcp_servers/__init__.py` with module docstring describing this as the ACTION layer for MCP servers per constitution Principle II

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core modules that MUST be complete before ANY user story tool can be implemented

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 Implement `GmailClient` class in `backend/mcp_servers/gmail_client.py` with `__init__(credentials_path, token_path)`, `authenticate()` method reusing OAuth pattern from `backend/watchers/gmail_watcher.py:106-131`, token auto-refresh, scopes `["gmail.readonly", "gmail.modify", "gmail.send"]`, and retry wrapper `_execute_with_retry(callable)` using exponential backoff (max 3 retries, 1s initial delay) for HttpError 401/429/500/503. Include `--auth-only` re-authorization support for adding `gmail.send` scope.
- [x] T004 [P] Implement `RateLimiter` class in `backend/mcp_servers/rate_limiter.py` with `collections.deque` of `float` timestamps, `__init__(config_path="config/rate_limits.json")` loading `email.sends_per_hour` (default 10) and window of 3600 seconds, `check() -> tuple[bool, int]` that prunes expired timestamps and returns `(allowed, seconds_until_next_slot)`, and `record_send()` to append current timestamp after successful send.
- [x] T005 [P] Implement `find_approval()` and `consume_approval()` functions in `backend/mcp_servers/approval.py`. `find_approval(vault_path: str, action_type: str, **match_fields) -> dict | None` scans `vault/Approved/*.md` files using `backend.utils.frontmatter.extract_frontmatter()`, matches by `type` (email_send or email_reply), `status` == "approved", and case-insensitive `to` or `thread_id` field. Returns most recent match if multiple. `consume_approval(file_path: Path, vault_path: str)` moves file from `vault/Approved/` to `vault/Done/` with `completed_at` frontmatter update.
- [x] T006 Create `backend/mcp_servers/email_server.py` server scaffold: `FastMCP("email-mcp-server", lifespan=app_lifespan)` with async context manager lifespan that initializes `GmailClient` and `RateLimiter`; load `DEV_MODE` and `DRY_RUN` from environment via `dotenv`; configure `logging` to stderr only; implement `redact_email(address: str) -> str` helper (e.g., `john@example.com` → `j***@example.com`); implement `_log_tool_action(log_path, action_type, target, result, correlation_id, duration_ms, parameters)` wrapper around `backend.utils.logging_utils.log_action()`; add `if __name__ == "__main__": mcp.run(transport="stdio")` entry point and `--auth-only` CLI argument handling.

**Checkpoint**: Foundation ready — GmailClient authenticates, RateLimiter loads config, approval module scans vault, server scaffold starts via stdio. User story tool implementation can now begin.

---

## Phase 3: User Story 1 — Search Emails via Claude Code (Priority: P1) MVP

**Goal**: Users can search their Gmail inbox through Claude Code and receive results with sender, subject, snippet, date, and identifiers.

**Independent Test**: Ask Claude Code to search for a known email. Verify results appear in conversation with correct fields.

**Success Criteria**: SC-001 (results within 5 seconds), SC-007 (server starts within 3 seconds)

### Implementation for User Story 1

- [x] T007 [US1] Add `search_messages(query: str, max_results: int = 5) -> list[dict]` method to `GmailClient` in `backend/mcp_servers/gmail_client.py`. Call `users.messages.list(userId="me", q=query, maxResults=max_results)` then for each message call `users.messages.get(userId="me", id=msg_id, format="metadata", metadataHeaders=["From","To","Subject","Date"])` to extract `message_id`, `thread_id`, `from_address`, `to_address`, `subject`, `snippet`, `date`. Return list of dicts. Handle empty results (return `[]`).
- [x] T008 [US1] Implement `search_email` async MCP tool in `backend/mcp_servers/email_server.py` per `contracts/mcp-tools.md`. Register with `@mcp.tool()`, accept `query: str` and `max_results: int = 5` params. Call `await asyncio.to_thread(gmail_client.search_messages, query, max_results)`. Format results as numbered text list with From, Subject, Date, Snippet, Message ID, Thread ID. Return "No emails found matching: {query}" for empty results. Log audit entry with `action_type="search_email"`, redacted query. Wrap in try/except for `HttpError` with user-friendly error messages.
- [x] T009 [P] [US1] Write unit tests in `tests/test_gmail_client.py` for `GmailClient.search_messages()` with mocked Gmail API service: test successful search returning 3 results, test empty results, test HttpError 401 triggering token refresh retry. Write tests in `tests/test_email_server.py` for `search_email` tool: mock `GmailClient`, test formatted output, test empty results message.

**Checkpoint**: User Story 1 complete — `search_email` tool works end-to-end via MCP stdio. Can be tested independently.

---

## Phase 4: User Story 2 — Draft Email via Claude Code (Priority: P2)

**Goal**: Users can create email drafts through Claude Code that appear in their Gmail drafts folder for review before manual sending.

**Independent Test**: Ask Claude Code to draft an email and verify the draft appears in Gmail Drafts.

**Success Criteria**: SC-002 (drafts appear correctly in Gmail)

### Implementation for User Story 2

- [x] T010 [US2] Add `create_draft(to: str, subject: str, body: str) -> dict` method to `GmailClient` in `backend/mcp_servers/gmail_client.py`. Build `email.message.EmailMessage` with `set_content(body)`, set `To`, `Subject` headers. Encode with `base64.urlsafe_b64encode(message.as_bytes())`. Call `users.drafts.create(userId="me", body={"message": {"raw": encoded}})`. Return `{"draft_id": result["id"], "message_id": result["message"]["id"]}`.
- [x] T011 [US2] Implement `draft_email` async MCP tool in `backend/mcp_servers/email_server.py` per `contracts/mcp-tools.md`. Accept `to: str`, `subject: str`, `body: str`. Validate `to` is a plausible email format (contains `@`). Check DEV_MODE → if true, log to vault and return `"[DEV_MODE] Draft logged but not created..."` with redacted address. Otherwise call `await asyncio.to_thread(gmail_client.create_draft, to, subject, body)`. Return success message with draft ID. Log audit entry with `action_type="draft_email"`, redacted recipient and subject (max 50 chars).
- [x] T012 [P] [US2] Write unit tests in `tests/test_gmail_client.py` for `GmailClient.create_draft()`: test successful draft creation returning draft_id, test with special characters in body. Write tests in `tests/test_email_server.py` for `draft_email` tool: test success, test DEV_MODE log-only, test invalid email validation error.

**Checkpoint**: User Story 2 complete — `draft_email` tool creates Gmail drafts. Can be tested independently alongside US1.

---

## Phase 5: User Story 3 — Send Approved Email via Claude Code (Priority: P3)

**Goal**: Approved emails are sent via Gmail with full HITL safety (approval file required, rate limiting enforced, audit logged).

**Independent Test**: Create an approval file in `vault/Approved/` with matching `type: email_send` and `to` field, then invoke `send_email` and verify the email arrives and approval is consumed (moved to `vault/Done/`).

**Success Criteria**: SC-003 (approved emails sent + logged), SC-004 (unapproved blocked 100%), SC-005 (rate-limited with cooldown), SC-006 (audit log within 1s)

### Implementation for User Story 3

- [x] T013 [US3] Add `send_message(to: str, subject: str, body: str) -> dict` method to `GmailClient` in `backend/mcp_servers/gmail_client.py`. Build `email.message.EmailMessage`, encode with `base64.urlsafe_b64encode`, call `users.messages.send(userId="me", body={"raw": encoded})`. Return `{"message_id": result["id"], "thread_id": result["threadId"]}`.
- [x] T014 [US3] Implement `send_email` async MCP tool in `backend/mcp_servers/email_server.py` per `contracts/mcp-tools.md`. Flow: validate `to`/`subject`/`body` → check DEV_MODE (log-only if true) → call `find_approval(vault_path, "email_send", to=to)` from `approval.py` (reject if None with guidance message) → call `rate_limiter.check()` (reject if exceeded with cooldown time) → call `await asyncio.to_thread(gmail_client.send_message, to, subject, body)` → call `rate_limiter.record_send()` → call `consume_approval()` to move approval file to `vault/Done/` → log audit entry with correlation_id, `action_type="send_email"`, redacted target, duration_ms → return success with message_id and thread_id.
- [x] T015 [P] [US3] Write unit tests in `tests/test_rate_limiter.py` for `RateLimiter`: test under limit allows, test at limit rejects with seconds remaining, test window expiry allows again. Write tests in `tests/test_approval.py` for `find_approval()`: test matching file found, test no match returns None, test multiple matches returns most recent, test `consume_approval()` moves file to Done. Write tests in `tests/test_email_server.py` for `send_email` tool: test approved + under limit → success, test no approval → rejection, test rate limited → rejection with cooldown, test DEV_MODE → log only.

**Checkpoint**: User Story 3 complete — `send_email` tool works with full HITL approval, rate limiting, and audit logging. Can be tested independently.

---

## Phase 6: User Story 4 — Reply to Email Thread (Priority: P4)

**Goal**: Users can reply to existing email threads with correct Gmail threading (replies appear in same conversation).

**Independent Test**: Search for a thread via `search_email`, create an approval file for reply, invoke `reply_email`, verify reply appears threaded in Gmail.

**Success Criteria**: SC-008 (replies correctly threaded in Gmail)

### Implementation for User Story 4

- [x] T016 [US4] Add `get_message_headers(message_id: str) -> dict` and `reply_to_thread(thread_id: str, message_id: str, body: str) -> dict` methods to `GmailClient` in `backend/mcp_servers/gmail_client.py`. `get_message_headers` fetches `users.messages.get(userId="me", id=message_id, format="metadata", metadataHeaders=["Message-ID","References","Subject","From","To"])` and returns parsed headers dict. `reply_to_thread` calls `get_message_headers`, builds `EmailMessage` with `In-Reply-To` set to original `Message-ID`, `References` set to `"{original_references} {original_message_id}"`, `Subject` prefixed with `"Re: "` if not already, `To` set to original `From`. Sends via `users.messages.send(userId="me", body={"raw": encoded, "threadId": thread_id})`. Returns `{"message_id": result["id"], "thread_id": result["threadId"]}`.
- [x] T017 [US4] Implement `reply_email` async MCP tool in `backend/mcp_servers/email_server.py` per `contracts/mcp-tools.md`. Accept `thread_id: str`, `message_id: str`, `body: str`. Flow: validate params → check DEV_MODE (log-only) → call `find_approval(vault_path, "email_reply", thread_id=thread_id)` (reject if None) → call `rate_limiter.check()` (reject if exceeded) → call `await asyncio.to_thread(gmail_client.reply_to_thread, thread_id, message_id, body)` → `rate_limiter.record_send()` → `consume_approval()` → log audit entry → return success with message_id and thread_id. Handle `HttpError 404` with clear "thread not found" message.
- [x] T018 [P] [US4] Write unit tests in `tests/test_gmail_client.py` for `get_message_headers()` and `reply_to_thread()`: test headers extraction, test reply builds correct `In-Reply-To`/`References`/`Subject`, test send with threadId. Write tests in `tests/test_email_server.py` for `reply_email` tool: test approved reply succeeds with threading, test no approval rejected, test invalid thread_id returns error, test DEV_MODE log only.

**Checkpoint**: User Story 4 complete — All four MCP tools are functional. Full email workflow (search → draft → send → reply) works end-to-end.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Configuration, documentation, validation, and code quality across all user stories

- [x] T019 [P] Update `config/mcp.json`: set email server `enabled: true`, update `capabilities` to `["send_email", "draft_email", "reply_email", "search_email"]`, change command to `"uv"` with args `["run", "python", "-m", "backend.mcp_servers.email_server"]`
- [x] T020 [P] Create `skills/email-sender/SKILL.md` with skill metadata (name: "Email Sender", version: "1.0.0", triggers: email-related requests), required permissions (gmail.send, gmail.modify, gmail.readonly), decision tree (search=always, draft=no approval, send/reply=requires approval), tool reference for all 4 MCP tools, and safety notes (DEV_MODE, rate limits, HITL)
- [x] T021 Run `ruff check backend/mcp_servers/ tests/test_email_server.py tests/test_gmail_client.py tests/test_approval.py tests/test_rate_limiter.py` and `ruff format` to fix all linting and formatting issues
- [x] T022 Run full test suite `uv run pytest tests/ -v` and verify all tests pass with no failures
- [x] T023 Validate quickstart flow: verify `uv run python -m backend.mcp_servers.email_server` starts without error, verify `--auth-only` flag works, check audit log entry appears in `vault/Logs/actions/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **User Stories (Phases 3–6)**: All depend on Phase 2 completion
  - US1 (search) can proceed independently
  - US2 (draft) can proceed independently, parallel with US1
  - US3 (send) can proceed independently, parallel with US1/US2
  - US4 (reply) can proceed independently, but logically benefits from US1 (search for thread IDs) and US3 (shared send patterns)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1 — Search)**: Phase 2 only. No cross-story dependencies. **MVP scope.**
- **US2 (P2 — Draft)**: Phase 2 only. No cross-story dependencies.
- **US3 (P3 — Send)**: Phase 2 only. Uses `approval.py` and `rate_limiter.py` from Phase 2.
- **US4 (P4 — Reply)**: Phase 2 only. Uses `approval.py` and `rate_limiter.py` from Phase 2. Shares `send` pattern with US3 but is independently implementable.

### Within Each User Story

1. GmailClient method (data layer) before MCP tool (server layer)
2. MCP tool implementation before tests
3. Tests verify the complete story works

### Parallel Opportunities

- T004 and T005 can run in parallel (different files: `rate_limiter.py` vs `approval.py`)
- T009, T012, T015, T018 (test tasks) are each parallelizable within their story
- Once Phase 2 completes, US1–US4 can all start in parallel
- T019 and T020 (config + skill) can run in parallel in Phase 7

---

## Parallel Example: Phase 2 Foundational

```text
# Sequential (depends on T003):
Task T003: GmailClient in gmail_client.py (other modules depend on its interface)

# Parallel after T003:
Task T004: RateLimiter in rate_limiter.py (independent file)
Task T005: Approval module in approval.py (independent file)
Task T006: Server scaffold in email_server.py (imports from T003/T004/T005)
```

## Parallel Example: User Stories after Phase 2

```text
# All can start simultaneously (different tool implementations):
Task T007-T009: US1 Search (gmail_client.search_messages + search_email tool)
Task T010-T012: US2 Draft (gmail_client.create_draft + draft_email tool)
Task T013-T015: US3 Send (gmail_client.send_message + send_email tool)
Task T016-T018: US4 Reply (gmail_client.reply_to_thread + reply_email tool)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T002)
2. Complete Phase 2: Foundational (T003–T006)
3. Complete Phase 3: User Story 1 — Search (T007–T009)
4. **STOP and VALIDATE**: Test `search_email` tool via Claude Code
5. Delivers immediate value — email search from terminal

### Incremental Delivery

1. Setup + Foundational → Foundation ready (T001–T006)
2. Add US1 Search → Test independently → **MVP!** (T007–T009)
3. Add US2 Draft → Test independently → Draft capability (T010–T012)
4. Add US3 Send → Test independently → Full send with HITL (T013–T015)
5. Add US4 Reply → Test independently → Complete email workflow (T016–T018)
6. Polish → Production-ready (T019–T023)
7. Each story adds value without breaking previous stories

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All GmailClient methods are synchronous (wrapped with `asyncio.to_thread()` in MCP tools)
- All MCP tools log audit entries via `backend.utils.logging_utils.log_action()`
- DEV_MODE check is the FIRST gate in every write tool (send, draft, reply)
