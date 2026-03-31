---
feature: gmail-watcher
type: implementation-plan
status: draft
created: 2026-02-08
---

# Gmail Watcher - Technical Implementation Plan

## Scope

### In Scope
- `backend/watchers/__init__.py` - Package initialization
- `backend/watchers/base_watcher.py` - Abstract base class for all watchers
- `backend/watchers/gmail_watcher.py` - Gmail API polling, filtering, action file creation
- `skills/gmail-watcher/scripts/setup_gmail_oauth.py` - One-time OAuth token generation
- `skills/gmail-watcher/references/gmail_api_quickstart.md` - Setup documentation
- `tests/test_gmail_watcher.py` - Unit and integration tests
- `.env.example` updates for new Gmail-specific variables

### Out of Scope
- Sending/modifying emails (read-only watcher)
- WhatsApp, Calendar, LinkedIn watchers (future tiers)
- MCP server integration
- Dashboard auto-update logic
- Cloud deployment

### External Dependencies
- Google Gmail API (`google-api-python-client` - already in pyproject.toml)
- Google OAuth2 (`google-auth-oauthlib` - already in pyproject.toml)
- `python-dotenv` (already in pyproject.toml)
- Existing `backend/utils/` (frontmatter, logging, timestamps, uuid)

---

## Implementation Steps

### Step 1: Create `backend/watchers/__init__.py`

**File:** `backend/watchers/__init__.py`

Package init that exports the watcher classes.

```python
"""Watcher modules for the AI Employee perception layer."""

from backend.watchers.base_watcher import BaseWatcher

__all__ = ["BaseWatcher"]
```

After `gmail_watcher.py` is created, add `GmailWatcher` to exports.

---

### Step 2: Create `backend/watchers/base_watcher.py`

**File:** `backend/watchers/base_watcher.py`

Abstract base class that all watchers inherit from. Follows the pattern from the spec.

```python
"""Abstract base class for all perception layer watchers."""

from abc import ABC, abstractmethod
from pathlib import Path
import asyncio
import logging


class BaseWatcher(ABC):
    """Base class for watchers that poll external sources and create vault action files.

    Subclasses must implement:
        - check_for_updates() -> list of new items
        - create_action_file(item) -> Path to created file
    """

    def __init__(self, vault_path: str, check_interval: int = 60):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / "Needs_Action"
        self.logs_path = self.vault_path / "Logs"
        self.check_interval = check_interval
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    async def check_for_updates(self) -> list:
        """Return list of new items to process."""
        pass

    @abstractmethod
    async def create_action_file(self, item: dict) -> Path:
        """Create .md file in Needs_Action folder. Returns the file path."""
        pass

    async def run(self) -> None:
        """Main polling loop. Override for custom behavior."""
        self.logger.info(f"Starting {self.__class__.__name__}")
        while True:
            try:
                items = await self.check_for_updates()
                for item in items:
                    await self.create_action_file(item)
            except Exception as e:
                self.logger.error(f"Error in {self.__class__.__name__}: {e}")
            await asyncio.sleep(self.check_interval)
```

**Key decisions:**
- `vault_path`, `needs_action`, `logs_path` as Path objects for cross-platform support
- `check_interval` configurable per watcher instance
- `run()` is non-abstract so subclasses can use it as-is or override
- Logger named after the concrete class for clear log attribution
- Broad exception catch in `run()` to keep the loop alive; subclasses handle specific errors

---

### Step 3: Create `backend/watchers/gmail_watcher.py`

**File:** `backend/watchers/gmail_watcher.py`

This is the core implementation. It breaks down into these internal responsibilities:

#### 3a. Imports and Configuration Loading

```python
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.utils.frontmatter import create_file_with_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import format_filename_timestamp, now_iso
from backend.utils.uuid_utils import correlation_id
from backend.watchers.base_watcher import BaseWatcher
```

Load config from `config/gmail_config.json` and `.env`:

- `GMAIL_CREDENTIALS_PATH` (default: `config/credentials.json`)
- `GMAIL_TOKEN_PATH` (default: `config/token.json`)
- `GMAIL_CHECK_INTERVAL` (default: `120`)
- `GMAIL_KEYWORDS` (default: `urgent,invoice,payment,asap,help,deadline`)
- `DEV_MODE` (default: `true`)
- `DRY_RUN` (default: `true`)
- `VAULT_PATH` (default: `./vault`)

Config merging priority: `.env` values override `gmail_config.json` defaults.

#### 3b. GmailWatcher Class Definition

```python
class GmailWatcher(BaseWatcher):
    def __init__(
        self,
        vault_path: str,
        credentials_path: str,
        token_path: str,
        check_interval: int = 120,
        gmail_config: dict | None = None,
        dry_run: bool = True,
        dev_mode: bool = True,
    ):
        super().__init__(vault_path, check_interval)
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.gmail_config = gmail_config or {}
        self.dry_run = dry_run
        self.dev_mode = dev_mode
        self.service = None  # Gmail API service, initialized lazily
        self.processed_ids_path = self.logs_path / "processed_emails.json"
        self._processed_ids: dict[str, str] = {}
        self._consecutive_errors = 0
        self._backoff_delay = 1.0
```

#### 3c. Authentication (`_authenticate` method)

- Load existing token from `self.token_path` if it exists
- If token expired, refresh using `creds.refresh(Request())`
- If no valid token, raise error directing user to run `setup_gmail_oauth.py`
- Build the Gmail API service: `build("gmail", "v1", credentials=creds)`
- Save refreshed token back to `self.token_path`

This method is synchronous (Google API client is sync) and called from async context via `asyncio.to_thread()`.

#### 3d. Email Fetching (`check_for_updates` method)

1. Authenticate if `self.service` is None
2. Load processed IDs from `self.processed_ids_path`
3. Build query string from `gmail_config["query"]` (default: `is:unread (is:important OR subject:(urgent OR invoice OR payment))`)
4. Call Gmail API: `service.users().messages().list(userId="me", q=query, maxResults=max_results)`
5. For each message ID in results:
   - Skip if already in `self._processed_ids`
   - Fetch full message: `service.users().messages().get(userId="me", id=msg_id, format="full")`
   - Check against `exclude_senders` list
   - Extract headers: From, To, Subject, Date
   - Extract snippet/body
   - Classify priority based on `priority_keywords`
   - Extract labels
   - Return as structured dict
6. Handle pagination if needed (but respect `max_results`)
7. Wrap Gmail API calls in `asyncio.to_thread()` since the Google client is synchronous

**Error handling in this method:**
- `HttpError` with status 429: exponential backoff (1s, 2s, 4s, 8s... max 60s)
- `HttpError` with status 401: call `_authenticate()` to refresh token, retry once
- `HttpError` with status 403: log and raise (permissions issue)
- Network errors (`ConnectionError`, `TimeoutError`): retry up to 3 times, then log and return empty list
- Reset `_consecutive_errors` on success; increment on failure

#### 3e. Priority Classification (`_classify_priority` method)

```python
def _classify_priority(self, subject: str, snippet: str) -> str:
    text = f"{subject} {snippet}".lower()
    high_keywords = self.gmail_config.get("priority_keywords", {}).get("high", [])
    medium_keywords = self.gmail_config.get("priority_keywords", {}).get("medium", [])

    for kw in high_keywords:
        if kw in text:
            return "high"
    for kw in medium_keywords:
        if kw in text:
            return "medium"
    return "low"
```

#### 3f. Action File Creation (`create_action_file` method)

1. Generate filename: `email-{slugified_subject}-{timestamp}.md`
   - Slugify: lowercase, replace non-alphanumeric with `-`, truncate to 50 chars
2. Build frontmatter dict matching the spec schema:
   ```python
   frontmatter = {
       "type": "email",
       "id": f"EMAIL_{short_id}_{format_filename_timestamp()}",
       "source": "gmail_watcher",
       "from": item["from"],
       "subject": item["subject"],
       "received": item["received"],
       "priority": item["priority"],
       "status": "pending",
       "message_id": item["message_id"],
       "thread_id": item["thread_id"],
   }
   ```
3. Build markdown body:
   - `## Email Content` section with snippet
   - `## Metadata` section with From, Date, Labels
   - `## Suggested Actions` section with checkbox items
4. If `self.dry_run`:
   - Log what would be created (filename, frontmatter summary)
   - Do NOT write the file
   - Do NOT add to processed IDs
   - Return None
5. If not dry run:
   - Call `create_file_with_frontmatter(file_path, frontmatter, body)`
   - Add message_id to processed IDs with current timestamp
   - Save processed IDs to disk
   - Log action via `log_action()`
   - Return file path

#### 3g. Processed IDs Management

**`_load_processed_ids` method:**
- Read `vault/Logs/processed_emails.json`
- Parse JSON into `self._processed_ids` dict
- If file doesn't exist, initialize empty dict

**`_save_processed_ids` method:**
- Write `self._processed_ids` to `vault/Logs/processed_emails.json`
- Include `last_cleanup` timestamp

**`_cleanup_old_ids` method:**
- Remove entries older than `processed_ids_retention_days` (default 30)
- Update `last_cleanup` timestamp
- Called once per day (check `last_cleanup` timestamp)

#### 3h. Logging Integration

All operations log to `vault/Logs/actions/YYYY-MM-DD.json` using the existing `log_action()` utility:

```python
log_action(self.logs_path / "actions", {
    "timestamp": now_iso(),
    "correlation_id": correlation_id(),
    "actor": "gmail_watcher",
    "action_type": "email_processed",
    "target": filename,
    "result": "success",
    "parameters": {
        "message_id": msg_id,
        "subject": subject,
        "priority": priority,
        "dry_run": self.dry_run,
        "dev_mode": self.dev_mode,
    },
})
```

Errors log to `vault/Logs/errors/YYYY-MM-DD.json`:

```python
log_action(self.logs_path / "errors", {
    "timestamp": now_iso(),
    "correlation_id": correlation_id(),
    "actor": "gmail_watcher",
    "action_type": "error",
    "target": "gmail_api",
    "error": str(e),
    "details": {"retry_count": self._consecutive_errors},
    "result": "failure",
})
```

#### 3i. CLI Entry Point

At the bottom of `gmail_watcher.py`, add an `if __name__ == "__main__":` block:

```python
def main() -> None:
    load_dotenv()
    # Parse args: --once, --auth-only
    # Load config from gmail_config.json
    # Instantiate GmailWatcher
    # Run: asyncio.run(watcher.run()) or single check for --once
```

CLI flags:
- `--once`: Run a single check and exit
- `--auth-only`: Only authenticate and save token, then exit
- No flags: Run the polling loop

Use `argparse` for argument parsing.

---

### Step 4: Create `skills/gmail-watcher/scripts/setup_gmail_oauth.py`

**File:** `skills/gmail-watcher/scripts/setup_gmail_oauth.py`

Standalone script for first-time OAuth setup:

1. Load `.env` for `GMAIL_CREDENTIALS_PATH` and `GMAIL_TOKEN_PATH`
2. Check `credentials.json` exists; error with instructions if not
3. Run `InstalledAppFlow.from_client_secrets_file()` with scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.modify`
4. Open browser for consent
5. Save token to `GMAIL_TOKEN_PATH`
6. Print success message with next steps

```python
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

def setup_oauth():
    load_dotenv()
    creds_path = Path(os.getenv("GMAIL_CREDENTIALS_PATH", "config/credentials.json"))
    token_path = Path(os.getenv("GMAIL_TOKEN_PATH", "config/token.json"))

    if not creds_path.exists():
        print(f"ERROR: {creds_path} not found.")
        print("Download from Google Cloud Console → APIs & Services → Credentials")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    print(f"Token saved to {token_path}")
    print("Gmail watcher is ready. Run: uv run python backend/watchers/gmail_watcher.py")
```

---

### Step 5: Update `config/.env.example`

Add the missing Gmail-specific variables referenced by the implementation:

```bash
# Gmail Watcher - Credential Paths
GMAIL_CREDENTIALS_PATH=config/credentials.json
GMAIL_TOKEN_PATH=config/token.json

# Gmail Watcher - Polling
GMAIL_CHECK_INTERVAL=120
GMAIL_KEYWORDS=urgent,invoice,payment,asap,help,deadline
```

These supplement the existing `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_TOKEN_PATH`, and `GMAIL_USER_EMAIL` entries.

---

### Step 6: Create `skills/gmail-watcher/references/gmail_api_quickstart.md`

**File:** `skills/gmail-watcher/references/gmail_api_quickstart.md`

Setup documentation covering:
1. Google Cloud Console project creation
2. Gmail API enabling
3. OAuth consent screen configuration
4. Credentials download
5. Running `setup_gmail_oauth.py`
6. Verifying the token works
7. Troubleshooting common issues

---

### Step 7: Create `tests/test_gmail_watcher.py`

**File:** `tests/test_gmail_watcher.py`

#### 7a. Unit Tests

**Test email parsing/extraction:**
- `test_parse_email_headers` - Extract From, To, Subject, Date from Gmail API message format
- `test_parse_email_missing_headers` - Handle messages with missing headers gracefully
- `test_classify_priority_high` - Subject containing "urgent" → high
- `test_classify_priority_medium` - Subject containing "review" → medium
- `test_classify_priority_low` - No matching keywords → low
- `test_classify_priority_case_insensitive` - "URGENT" matches "urgent"
- `test_slugify_subject` - "RE: Invoice #123!" → "re-invoice-123"
- `test_slugify_long_subject` - Truncates to 50 chars

**Test action file creation:**
- `test_create_action_file_content` - Verify frontmatter fields and body structure
- `test_create_action_file_dry_run` - DRY_RUN=true writes no files
- `test_create_action_file_writes_to_needs_action` - File appears in correct directory
- `test_action_file_frontmatter_schema` - All required fields present

**Test processed IDs:**
- `test_load_processed_ids_empty` - First run returns empty dict
- `test_load_processed_ids_existing` - Loads from JSON file
- `test_save_processed_ids` - Writes valid JSON
- `test_skip_already_processed` - Known IDs are filtered out
- `test_cleanup_old_ids` - IDs older than 30 days removed

**Test sender filtering:**
- `test_exclude_noreply_senders` - noreply@ emails filtered out
- `test_include_regular_senders` - Normal senders pass through

#### 7b. Integration Tests (with mock Gmail API)

- `test_check_for_updates_with_mock_api` - Mock `googleapiclient` to return sample messages, verify action files created
- `test_check_for_updates_empty_inbox` - No unread messages → no action files
- `test_check_for_updates_all_processed` - All messages already in processed IDs → no new files
- `test_error_handling_rate_limit` - Mock 429 response → verify backoff behavior
- `test_error_handling_auth_failure` - Mock 401 response → verify re-auth attempt
- `test_full_cycle_dry_run` - End-to-end with DRY_RUN=true → verify logging but no files

**Mocking strategy:**
- Use `unittest.mock.patch` to mock `googleapiclient.discovery.build`
- Create fixture with sample Gmail API response payloads
- Use `tmp_path` pytest fixture for vault directory isolation

---

## File Creation Order

This is the recommended implementation sequence:

| Order | File | Depends On |
|-------|------|-----------|
| 1 | `backend/watchers/__init__.py` | Nothing |
| 2 | `backend/watchers/base_watcher.py` | Nothing |
| 3 | `backend/watchers/gmail_watcher.py` | Steps 1-2, `backend/utils/*` |
| 4 | `skills/gmail-watcher/scripts/setup_gmail_oauth.py` | Nothing |
| 5 | Update `config/.env.example` | Nothing |
| 6 | `skills/gmail-watcher/references/gmail_api_quickstart.md` | Step 4 |
| 7 | `tests/test_gmail_watcher.py` | Steps 1-3 |
| 8 | Update `backend/watchers/__init__.py` | Step 3 (add GmailWatcher export) |

---

## Key Design Decisions

### 1. Sync Gmail API wrapped in `asyncio.to_thread()`
The `google-api-python-client` is synchronous. Rather than using an async HTTP client and reimplementing the Gmail API, we wrap sync calls in `asyncio.to_thread()` to maintain the async interface required by `BaseWatcher`. This is simpler and uses the official, well-tested Google client.

### 2. Processed IDs as flat JSON file (not SQLite)
A JSON file at `vault/Logs/processed_emails.json` is sufficient for the expected volume (tens of emails per day). It keeps the vault self-contained, is human-readable, and requires no additional dependencies.

### 3. Config merging: .env overrides gmail_config.json
`gmail_config.json` holds the detailed filter config (query, keywords, excluded senders). `.env` holds secrets and operational overrides (paths, intervals, dry_run). `.env` values take precedence for overlapping settings like `poll_interval_seconds`.

### 4. DRY_RUN separate from DEV_MODE
- `DEV_MODE=true`: Gmail API is still called (read-only is safe), but action file metadata includes `"dev_mode": true`
- `DRY_RUN=true`: Logs what would happen but creates no action files and doesn't mark emails as processed
- Both default to `true` for safety

### 5. No email body logging in production
Snippets are truncated to `snippet_max_length` (default 1000 chars). Full email bodies are never stored in logs. Action files contain snippets only, as specified.

---

## Error Handling Summary

| Error | Detection | Response |
|-------|-----------|----------|
| 429 Rate Limit | `HttpError` status 429 | Exponential backoff: 1s → 2s → 4s → 8s → max 60s |
| 401 Unauthorized | `HttpError` status 401 | Refresh token, retry once. If still fails, log critical and stop. |
| 403 Forbidden | `HttpError` status 403 | Log error, do not retry (permissions issue) |
| Network error | `ConnectionError`, `TimeoutError` | Retry 3 times with backoff, then log and continue to next poll |
| Token file missing | `FileNotFoundError` on token load | Log error, direct user to run `setup_gmail_oauth.py` |
| Malformed API response | `KeyError`, `TypeError` | Log error, skip that message, continue processing others |
| Disk write failure | `OSError` on file write | Log error, skip that action file, continue |

All errors logged to `vault/Logs/errors/YYYY-MM-DD.json` with correlation IDs.

---

## Security Checklist

- [x] `credentials.json` and `token.json` already in `.gitignore`
- [x] No secrets in code; all via `.env`
- [x] Email snippets only, never full bodies in logs
- [x] Rate limiting: respects `config/rate_limits.json` (50 Gmail API calls/minute)
- [x] OAuth scopes: `gmail.readonly` + `gmail.modify` (modify only for mark-as-read, which is disabled by default)
- [x] DEV_MODE and DRY_RUN default to `true`

---

## Risks and Mitigations

1. **Google OAuth token expiry during long runs** — Mitigated by automatic token refresh in `_authenticate()`. If refresh token itself expires (rare, ~6 months for testing apps), user must re-run `setup_gmail_oauth.py`.

2. **Gmail API quota exhaustion** — Mitigated by configurable `poll_interval_seconds` (default 120s = 30 calls/hour, well under quota) and exponential backoff on 429 errors.

3. **Processed IDs file corruption** — Mitigated by writing valid JSON atomically. If file is corrupted, watcher falls back to empty dict (may reprocess some emails, which is safe since action files have unique timestamps).
