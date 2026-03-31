# Vault File Contracts: Meta Social Integration (004)

**Date**: 2026-02-21
**Note**: This system uses file-based contracts (vault markdown files) rather than REST APIs. The contracts below define the exact frontmatter schemas and body formats for each file type exchanged between system components.

---

## Contract 1: FacebookWatcher → Vault (FACEBOOK Notification File)

**File pattern**: `vault/Needs_Action/FACEBOOK_{sender_slug}_{YYYYMMDD_HHMMSS}.md`
**Producer**: `backend/watchers/facebook_watcher.py`
**Consumer**: Operator (reads in Obsidian), ActionExecutor (skips — `status: pending`)

### Required Frontmatter

```yaml
type: "facebook"
id: "FACEBOOK_{7-char-id}_{YYYYMMDD_HHMMSS}"
source: "facebook_watcher"
item_type: "notification" | "message"
sender: <string, max 100 chars>
preview: <string, max 200 chars>
received: <ISO 8601 UTC>
priority: "high" | "medium" | "low"
status: "pending"
```

### Optional Frontmatter

```yaml
matched_keyword: <string>     # keyword that triggered capture
needs_reply: true             # only for Messenger messages
```

### Invariants

- `type` MUST be exactly `"facebook"` (not `"facebook_post"` — that's a different type)
- `id` MUST be unique across all vault files
- `preview` MUST be ≤ 200 characters
- `status` MUST be `"pending"` on creation

---

## Contract 2: InstagramWatcher → Vault (INSTAGRAM Notification File)

**File pattern**: `vault/Needs_Action/INSTAGRAM_{sender_slug}_{YYYYMMDD_HHMMSS}.md`
**Producer**: `backend/watchers/instagram_watcher.py`

### Required Frontmatter

```yaml
type: "instagram"
id: "INSTAGRAM_{7-char-id}_{YYYYMMDD_HHMMSS}"
source: "instagram_watcher"
item_type: "notification" | "direct_message"
sender: <string, max 100 chars>
preview: <string, max 200 chars>
received: <ISO 8601 UTC>
priority: "high" | "medium" | "low"
status: "pending"
```

### Optional Frontmatter

```yaml
matched_keyword: <string>
needs_reply: true
```

---

## Contract 3: ContentScheduler → Vault (FACEBOOK_POST Draft File)

**File pattern**: `vault/Pending_Approval/FACEBOOK_POST_{YYYYMMDD}.md`
**Producer**: `backend/scheduler/content_scheduler.py` (via PostGenerator)
**Consumer**: Operator approval → ActionExecutor → FacebookPoster

### Required Frontmatter

```yaml
type: "facebook_post"
status: "pending_approval"
platform: "facebook"
character_count: <integer, 1..63206>
generated_at: <ISO 8601 UTC>
```

### Optional Frontmatter

```yaml
topic: <string>           # source topic slug
scheduled_for: <date>     # YYYY-MM-DD
image_path: <string>      # path to image file (absolute or project-relative)
```

### After Human Approval

Operator changes `status: pending_approval` → `status: approved` and moves file to `vault/Approved/`.

### ActionExecutor Pickup Condition

```python
fm.get("type") == "facebook_post" AND fm.get("status") == "approved"
```

---

## Contract 4: ContentScheduler → Vault (INSTAGRAM_POST Draft File)

**File pattern**: `vault/Pending_Approval/INSTAGRAM_POST_{YYYYMMDD}.md`

### Required Frontmatter

```yaml
type: "instagram_post"
status: "pending_approval"
platform: "instagram"
character_count: <integer, 1..2200>
generated_at: <ISO 8601 UTC>
```

Same optional fields and approval flow as Contract 3.

---

## Contract 5: FacebookPoster / InstagramPoster → Vault (Done / Rejected)

**On success**: File moved from `vault/Approved/` → `vault/Done/` with updated frontmatter:
```yaml
status: "done"
published_at: <ISO 8601 UTC>
```

**On validation failure**: File moved to `vault/Rejected/` with:
```yaml
status: "rejected"
rejected_at: <ISO 8601 UTC>
rejection_reason: "character_count_exceeded" | "empty_body" | "image_file_not_found" | "publish_failed"
```

---

## Contract 6: Python Module Interface — FacebookWatcher

```python
class FacebookWatcher(BaseWatcher):
    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/meta_session",
        check_interval: int = 120,
        keywords: list[str] | None = None,
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ) -> None: ...

    async def check_for_updates(self) -> list[dict[str, Any]]:
        """Return list of new Facebook notification dicts.
        Never raises — returns [] on any error.
        """

    async def create_action_file(self, item: dict[str, Any]) -> Path | None:
        """Create vault/Needs_Action/FACEBOOK_*.md. Returns None on dry_run."""

    async def setup_session(self) -> bool:
        """Interactive headed-browser Facebook login. Returns True on success."""
```

---

## Contract 7: Python Module Interface — InstagramWatcher

```python
class InstagramWatcher(BaseWatcher):
    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/meta_session",
        check_interval: int = 60,
        keywords: list[str] | None = None,
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ) -> None: ...

    async def check_for_updates(self) -> list[dict[str, Any]]: ...
    async def create_action_file(self, item: dict[str, Any]) -> Path | None: ...
    async def setup_session(self) -> bool: ...
```

---

## Contract 8: Python Module Interface — FacebookPoster

```python
class FacebookPoster:
    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/meta_session",
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ) -> None: ...

    async def process_approved_posts(self) -> int:
        """Process all approved facebook_post files. Returns count of processed posts."""

    async def _close_browser(self) -> None: ...
```

---

## Contract 9: Python Module Interface — InstagramPoster

```python
class InstagramPoster:
    def __init__(
        self,
        vault_path: str,
        session_path: str = "config/meta_session",
        headless: bool = True,
        dry_run: bool = True,
        dev_mode: bool = True,
    ) -> None: ...

    async def process_approved_posts(self) -> int: ...
    async def _close_browser(self) -> None: ...
```

---

## Contract 10: ActionExecutor Handler Extension

The `ActionExecutor.HANDLERS` dict is extended to:

```python
HANDLERS: dict[str, str] = {
    "email_send": "_handle_email_send",
    "email_reply": "_handle_email_reply",
    "linkedin_post": "_handle_linkedin_post",
    "facebook_post": "_handle_facebook_post",   # NEW
    "instagram_post": "_handle_instagram_post",  # NEW
}
```

Handler signatures (match existing pattern):

```python
async def _handle_facebook_post(
    self, file_path: Path, _fm: dict[str, Any], _cid: str
) -> None: ...

async def _handle_instagram_post(
    self, file_path: Path, _fm: dict[str, Any], _cid: str
) -> None: ...
```

---

## Contract 11: PostGenerator Platform Extension

```python
# Extended generate() behavior:
# topic.get("platform", "linkedin") determines the type: field in frontmatter

# topic = {"name": "Behind the Scenes", "platform": "facebook", ...}
# → frontmatter["type"] = "facebook_post"

# topic = {"name": "Visual Story", "platform": "instagram", ...}
# → frontmatter["type"] = "instagram_post"

# topic = {"name": "AI in Business"}  # no platform field
# → frontmatter["type"] = "linkedin_post"  (unchanged from feature 003)
```
