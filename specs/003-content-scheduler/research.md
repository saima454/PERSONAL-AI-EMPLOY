# Research: Smart Content Scheduler

**Branch**: `003-content-scheduler` | **Date**: 2026-02-20 | **Phase**: 0

---

## Research Questions & Decisions

### RQ-1: Frontmatter Field Name for Action Routing

**Question**: The spec uses `action_type: linkedin_post` in frontmatter, but does the existing action executor use `action_type` or `type`?

**Finding**: `backend/orchestrator/action_executor.py:81` reads `fm.get("type", "")` for routing — NOT `action_type`. `backend/actions/linkedin_poster.py:262` also checks `frontmatter.get("type") == "linkedin_post"`. Both are consistent.

**Decision**: Use `type: linkedin_post` in generated draft frontmatter — NOT `action_type`.

**Impact**: Spec mentions `action_type` (incorrect). Plan and implementation will use `type` to match existing code.

---

### RQ-2: LinkedIn Poster Integration Point in Action Executor

**Question**: The `_handle_linkedin_post` handler in `action_executor.py:167–170` is a placeholder that raises `NotImplementedError`. How should we wire in the real `LinkedInPoster`?

**Finding**:
- `LinkedInPoster` at `backend/actions/linkedin_poster.py` is a fully-implemented async class.
- It reads `type: linkedin_post` files from `vault/Approved/` directly (has its own vault scanning).
- The `action_executor._handle_linkedin_post` currently just raises `NotImplementedError`.

**Decision**: Replace the placeholder in `_handle_linkedin_post` with a direct call to `LinkedInPoster(config).process_approved_posts()`. Since `LinkedInPoster` is async, it can be directly `await`-ed. Pass `vault_path`, `dev_mode`, and `dry_run` from `OrchestratorConfig`.

**Rationale**: The `LinkedInPoster` already implements the full Playwright flow, DEV_MODE guard, logging, and file lifecycle. Reusing it avoids duplication.

---

### RQ-3: Orchestrator Startup Integration Pattern

**Question**: Where in `orchestrator.run()` should we call the content scheduler, and how do we prevent it from blocking startup?

**Finding**: The `run()` method in `backend/orchestrator/orchestrator.py:140–169` follows this sequence:
1. `acquire_lock()`
2. `_ensure_vault_dirs()`
3. `_log_event("orchestrator_start")`
4. `_start_watchers()`
5. `_start_action_executor()`
6. `_start_dashboard_loop()`
7. `_wait_forever()`

**Decision**: Add `await self._check_content_schedule()` as a new async method, called between steps 3 and 4 (after vault dirs are ensured, before watchers start). The method must:
- Import `ContentScheduler` lazily (matching the existing lazy-import pattern)
- Run it in a try/except — failure must NOT prevent orchestrator startup
- Use `asyncio.to_thread()` since `ContentScheduler.run_if_due()` will be synchronous (file I/O)

**Rationale**: Startup check is a one-shot operation (not a polling loop), so it doesn't need an asyncio.Task. `asyncio.to_thread()` avoids blocking the event loop during file parsing.

---

### RQ-4: Template Storage and Structure

**Question**: Where should the 25+ post templates live? External YAML files, a separate Python module, or inline data?

**Options Considered**:
| Option | Pros | Cons |
|--------|------|------|
| External YAML | Easy to edit without code changes | Adds file dependency, harder to test, deploy complexity |
| Separate Python data module | Pure Python, importable, testable, no external files | Slightly less "user editable" |
| Inline in `post_generator.py` | Simplest, no extra files | `post_generator.py` gets long |

**Decision**: Python dataclasses/named tuples in a `TEMPLATES` dict in `post_generator.py`. Each template is a `PostTemplate` dataclass with `topic`, `format_type`, `body_template`, and `hashtags` fields.

**Rationale**: Keeps the module self-contained for testing, avoids file dependencies, and matches the constitution's "smallest viable change" principle. Templates are code artifacts that benefit from linting and type checking.

---

### RQ-5: Schedule State Persistence and Race Condition Prevention

**Question**: How do we prevent concurrent scheduler runs from corrupting `posting_schedule.json`?

**Finding**: No file locking mechanism exists in the current codebase. However, the scheduler is a short-lived one-shot process (not a long-running daemon), so concurrent execution is unlikely. The orchestrator uses a PID lock file to prevent duplicate orchestrator instances.

**Decision**: Use an atomic write pattern — write to a `.tmp` file then rename — for `posting_schedule.json` and `posted_topics.json` updates. Python's `pathlib.Path.rename()` is atomic on POSIX and atomic on Windows (NTFS) for files on the same volume. No additional file locking needed for this use case.

**Rationale**: Atomic rename is sufficient for the single-user, single-machine scope. Adding a full file locking library would be over-engineering.

---

### RQ-6: Timezone Handling

**Question**: How to handle `Asia/Karachi` timezone for "is today a post day" determination?

**Finding**: Python 3.9+ includes `zoneinfo` in stdlib (`from zoneinfo import ZoneInfo`). The project targets Python 3.13+, so this is available without additional dependencies.

**Decision**: Use `datetime.now(ZoneInfo("Asia/Karachi"))` for all "today" calculations. Fall back to UTC if ZoneInfo is unavailable (unknown timezone string). The `CONTENT_TIMEZONE` env var overrides the default.

---

### RQ-7: Post Content Extraction for LinkedIn Poster

**Question**: The `LinkedInPoster._extract_post_content()` strips the leading `# Post Content` heading. What exact format should the generated draft body use?

**Finding**: `linkedin_poster.py:277–290` strips the first `# ` heading from the body. The remaining content is sent verbatim to LinkedIn.

**Decision**: Draft body format:
```markdown
---
[frontmatter]
---

# Post Content

[actual linkedin post text with hashtags]
```

The `# Post Content` heading is required as a section marker. The LinkedIn post text follows directly after it.

---

### RQ-8: Character Count Validation

**Question**: The 1300-character limit — does it include the `# Post Content` heading and frontmatter?

**Finding**: LinkedIn's character limit applies to the published text. The `LinkedInPoster` strips the heading before posting (lines 281–289). Frontmatter is never sent to LinkedIn.

**Decision**: Character count is calculated on the final post text only (after heading removal, excluding frontmatter). The `PostGenerator` validates `len(post_text) <= 1300` before saving.

---

## Integration Points Summary

| Component | File | Change Type | Details |
|-----------|------|-------------|---------|
| New module | `backend/scheduler/__init__.py` | Create | Package init |
| New module | `backend/scheduler/content_scheduler.py` | Create | Main CLI + orchestrator hook |
| New module | `backend/scheduler/post_generator.py` | Create | Template engine, 25+ templates |
| New module | `backend/scheduler/schedule_manager.py` | Create | Schedule state R/W |
| Modify | `backend/orchestrator/orchestrator.py` | Add method | `_check_content_schedule()` + call |
| Modify | `backend/orchestrator/action_executor.py` | Replace stub | `_handle_linkedin_post()` real impl |
| Modify | `config/.env.example` | Add vars | 4 new content scheduling vars |
| Create | `vault/Content_Strategy.md` | Create | User content strategy template |
| Create | `skills/content-scheduler/SKILL.md` | Create | Skill definition |
| Create | `tests/test_content_scheduler.py` | Create | Unit tests |
