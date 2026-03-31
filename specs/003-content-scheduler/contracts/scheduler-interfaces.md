# Contracts: Scheduler Interfaces

**Branch**: `003-content-scheduler` | **Date**: 2026-02-20

---

## Module: `backend/scheduler/content_scheduler.py`

### `ContentScheduler`

```python
class ContentScheduler:
    def __init__(
        self,
        vault_path: str | Path,
        dev_mode: bool = True,
        dry_run: bool = False,
    ) -> None: ...

    def run_if_due(self) -> RunResult:
        """Check schedule and generate draft if a post is due today.

        Idempotent: safe to call multiple times on the same day.

        Returns:
            RunResult with status and draft_path.

        Raises:
            ContentStrategyError: if Content_Strategy.md is missing or unparseable.
        """

    def generate_now(self) -> RunResult:
        """Force-generate a draft, ignoring schedule and idempotency check.

        Still respects DEV_MODE (logs action but saves file in both modes).
        """

    def preview(self) -> PreviewResult:
        """Generate post content and return it without writing any files.

        Returns:
            PreviewResult with topic, post_text, character_count, template_id.
        """

    def status(self) -> StatusResult:
        """Return current schedule state for display.

        Returns:
            StatusResult with last_post_date, last_topic, next_topic,
            is_due_today, posts_today.
        """
```

**Return types**:

```python
@dataclass
class RunResult:
    status: Literal["generated", "skipped", "error"]
    draft_path: str | None    # Path if generated, None otherwise
    topic: str | None
    reason: str               # Human-readable explanation

@dataclass
class PreviewResult:
    topic: str
    post_text: str
    character_count: int
    template_id: str

@dataclass
class StatusResult:
    last_post_date: str | None       # YYYY-MM-DD
    last_topic: str | None
    next_topic: str | None
    is_due_today: bool
    posts_today: int
    next_run_time: str               # HH:MM local time (from strategy)
```

**Errors**:

```python
class ContentStrategyError(Exception):
    """Raised when vault/Content_Strategy.md is missing or unparseable."""

class TemplateGenerationError(Exception):
    """Raised when no template can produce a post within character limits."""
```

---

## Module: `backend/scheduler/schedule_manager.py`

### `ScheduleManager`

```python
class ScheduleManager:
    def __init__(
        self,
        vault_path: str | Path,
        timezone: str = "Asia/Karachi",
        skip_weekends: bool = False,
    ) -> None: ...

    def load_state(self) -> ScheduleState:
        """Load ScheduleState from posting_schedule.json.

        Creates default state if file is missing.
        Resets to default if file is corrupt JSON.
        """

    def save_state(self, state: ScheduleState) -> None:
        """Atomically save ScheduleState to posting_schedule.json."""

    def is_post_due(self, state: ScheduleState, strategy: ContentStrategy) -> bool:
        """Return True if a new post should be generated today.

        Rules:
        - False if posts_today > 0 and skip_already_generated=True
        - False if today is weekend and skip_weekends=True
        - False if frequency == "weekdays_only" and today is weekend
        - True if last_run_date != today
        """

    def get_next_topic_index(
        self, state: ScheduleState, num_topics: int
    ) -> int:
        """Return the next 0-based topic index, wrapping around.

        Guarantees: result != state.last_topic_index (avoids consecutive repeat).
        If only 1 topic exists, returns 0.
        """

    def draft_exists_today(self, vault_path: Path, date_str: str) -> bool:
        """Check if LINKEDIN_POST_{date_str}.md exists in Pending_Approval or Approved."""

    def load_history(self) -> PostingHistory:
        """Load PostingHistory from posted_topics.json."""

    def save_history(self, history: PostingHistory) -> None:
        """Atomically save PostingHistory to posted_topics.json."""
```

---

## Module: `backend/scheduler/post_generator.py`

### `PostGenerator`

```python
class PostGenerator:
    def __init__(
        self,
        max_hashtags: int = 5,
        max_characters: int = 1300,
    ) -> None: ...

    def generate(
        self,
        topic: Topic,
        strategy: ContentStrategy,
        context: PostContext,
        exclude_template_ids: list[str] | None = None,
    ) -> GeneratedPost:
        """Generate a post for the given topic.

        Selects a random template for the topic, fills placeholders, validates length.
        Retries with a different template if character limit exceeded (max 3 attempts).

        Args:
            topic: The selected Topic to generate content for.
            strategy: Full ContentStrategy for rules/tone.
            context: Optional context from Business_Goals/Company_Handbook.
            exclude_template_ids: Previously used templates to avoid (optional).

        Returns:
            GeneratedPost with body text, hashtags, template_id, character_count.

        Raises:
            TemplateGenerationError: if all templates exceed character limit.
        """

    def get_templates_for_topic(self, topic_key: str) -> list[PostTemplate]:
        """Return all templates for a given topic key."""

    def validate_post(self, post_text: str) -> ValidationResult:
        """Check character count, hashtag count, question presence."""
```

**Return types**:

```python
@dataclass
class PostContext:
    business_goals: str | None    # Contents of vault/Business_Goals.md (optional)
    company_handbook: str | None  # Contents of vault/Company_Handbook.md (optional)

@dataclass
class GeneratedPost:
    body: str               # Full post text including hashtags
    hashtags: list[str]     # Extracted hashtag list
    template_id: str
    character_count: int    # len(body)
    topic_key: str

@dataclass
class ValidationResult:
    valid: bool
    character_count: int
    hashtag_count: int
    has_question: bool
    errors: list[str]
```

---

## CLI Contract: `content_scheduler.py --cli`

```
Usage: python -m backend.scheduler.content_scheduler [OPTIONS]

Options:
  --generate-now    Force generate a post immediately, skip schedule check
  --preview         Print generated post to stdout, no file written
  --status          Show current schedule status and exit
  --vault-path STR  Override vault path (default: from VAULT_PATH env)
  --dry-run         Log actions but do not write draft files
  --help            Show this message and exit

Exit codes:
  0   Success or skip (no error)
  1   ContentStrategyError (missing or corrupt Content_Strategy.md)
  2   TemplateGenerationError (all templates exceed character limit)
  3   File I/O error
```

---

## Orchestrator Integration Contract

**Method added to `Orchestrator`**:

```python
async def _check_content_schedule(self) -> None:
    """One-shot content schedule check on startup.

    Called once after _ensure_vault_dirs(), before _start_watchers().
    Must not raise — all errors logged as warnings.
    """
```

**Invariants**:
- If `ContentScheduler.run_if_due()` raises any exception, the orchestrator logs a WARNING and continues startup normally.
- If a draft is generated, it is logged at INFO level: `"Content scheduler: draft generated → {path}"`
- If skipped (already exists today), it is logged at DEBUG level.

---

## Action Executor Integration Contract

**Method replacement in `ActionExecutor`**:

```python
async def _handle_linkedin_post(
    self, file_path: Path, fm: dict[str, Any], cid: str
) -> None:
    """Post approved LinkedIn content via LinkedInPoster.

    Replaces the NotImplementedError placeholder.
    """
```

**Invariants**:
- Reads `vault_path`, `dev_mode`, `dry_run` from `self.config`.
- Creates `LinkedInPoster(vault_path=..., dev_mode=..., dry_run=...)`.
- Calls `await poster.process_approved_posts()`.
- If `poster.process_approved_posts()` returns 0, raises `RuntimeError("No posts processed")` so the caller logs the failure but does NOT move the file to Done (leaves it in Approved for retry).
- DEV_MODE is already handled inside `LinkedInPoster.publish_post()`.

---

## Vault File Contract: Generated Draft

Every file written to `vault/Pending_Approval/LINKEDIN_POST_{YYYY-MM-DD}.md` MUST have:

```yaml
---
type: linkedin_post
status: pending_approval
topic: "AI and Automation"
topic_index: 0
template_id: ai_automation_tip_01
generated_at: "2026-02-20T09:00:00+05:00"
scheduled_date: "2026-02-20"
character_count: 847
---

# Post Content

[post text here — max 1300 characters including hashtags]
```

**Required fields**: `type`, `status`, `topic`, `generated_at`, `scheduled_date`, `character_count`
**Optional fields**: `topic_index`, `template_id`
