"""Gmail watcher - monitors inbox for important emails and creates vault action files.

This is a PERCEPTION layer component. It observes Gmail and writes action files
to the vault. It never sends, modifies, or deletes emails.

Usage:
    # Continuous polling
    uv run python backend/watchers/gmail_watcher.py

    # Single check
    uv run python backend/watchers/gmail_watcher.py --once

    # Auth only (first-time setup)
    uv run python backend/watchers/gmail_watcher.py --auth-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.utils.frontmatter import create_file_with_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import format_filename_timestamp, now_iso
from backend.utils.uuid_utils import correlation_id, short_id
from backend.watchers.base_watcher import BaseWatcher

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

DEFAULT_QUERY = "is:unread (is:important OR urgent OR invoice OR payment OR asap OR help OR deadline)"

MAX_BACKOFF_SECONDS = 60.0
MAX_RETRIES = 3


def _slugify(text: str, max_length: int = 50) -> str:
    """Convert text to a filename-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_length].rstrip("-")


def _load_gmail_config(config_path: str = "config/gmail_config.json") -> dict[str, Any]:
    """Load Gmail configuration from JSON file."""
    path = Path(config_path)
    if not path.exists():
        logger.warning("Gmail config not found at %s, using defaults", config_path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _get_header(headers: list[dict[str, str]], name: str) -> str:
    """Extract a header value from Gmail API message headers."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


class GmailWatcher(BaseWatcher):
    """Watches Gmail for important unread emails and creates vault action files."""

    def __init__(
        self,
        vault_path: str,
        credentials_path: str = "config/credentials.json",
        token_path: str = "config/token.json",
        check_interval: int = 120,
        gmail_config: dict[str, Any] | None = None,
        dry_run: bool = True,
        dev_mode: bool = True,
    ):
        super().__init__(vault_path, check_interval)
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.gmail_config = gmail_config or {}
        self.dry_run = dry_run
        self.dev_mode = dev_mode
        self.service: Any = None
        self.processed_ids_path = self.logs_path / "processed_emails.json"
        self._processed_ids: dict[str, str] = {}
        self._last_cleanup: str | None = None
        self._consecutive_errors = 0
        self._backoff_delay = 1.0

    # ── Authentication ──────────────────────────────────────────────

    def _authenticate(self) -> None:
        """Load or refresh OAuth credentials and build the Gmail API service.

        Raises:
            FileNotFoundError: If token file doesn't exist and can't authenticate.
            RuntimeError: If authentication fails after token refresh.
        """
        creds: Credentials | None = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            self.logger.info("Refreshing expired Gmail token")
            creds.refresh(Request())
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        if not creds or not creds.valid:
            msg = (
                f"No valid Gmail token at {self.token_path}. "
                "Run: uv run python skills/gmail-watcher/scripts/setup_gmail_oauth.py"
            )
            raise FileNotFoundError(msg)

        self.service = build("gmail", "v1", credentials=creds)
        self.logger.info("Gmail API authenticated successfully")

    # ── Processed IDs ───────────────────────────────────────────────

    def _load_processed_ids(self) -> None:
        """Load processed email IDs from disk."""
        if not self.processed_ids_path.exists():
            self._processed_ids = {}
            self._last_cleanup = None
            return

        try:
            data = json.loads(self.processed_ids_path.read_text(encoding="utf-8"))
            self._processed_ids = data.get("processed_ids", {})
            self._last_cleanup = data.get("last_cleanup")
        except (json.JSONDecodeError, KeyError):
            self.logger.warning("Corrupted processed_emails.json, starting fresh")
            self._processed_ids = {}
            self._last_cleanup = None

    def _save_processed_ids(self) -> None:
        """Save processed email IDs to disk."""
        self.processed_ids_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "processed_ids": self._processed_ids,
            "last_cleanup": self._last_cleanup or now_iso(),
        }
        self.processed_ids_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _cleanup_old_ids(self) -> None:
        """Remove processed IDs older than retention period."""
        retention_days = self.gmail_config.get("processed_ids_retention_days", 30)
        now = now_iso()

        # Only clean up once per day
        if self._last_cleanup:
            from backend.utils.timestamps import is_within_hours

            if is_within_hours(self._last_cleanup, 24):
                return

        cutoff_ids = []
        for msg_id, processed_at in self._processed_ids.items():
            try:
                from backend.utils.timestamps import is_within_hours

                if not is_within_hours(processed_at, retention_days * 24):
                    cutoff_ids.append(msg_id)
            except (ValueError, TypeError):
                cutoff_ids.append(msg_id)

        for msg_id in cutoff_ids:
            del self._processed_ids[msg_id]

        self._last_cleanup = now
        if cutoff_ids:
            self.logger.info("Cleaned up %d old processed email IDs", len(cutoff_ids))

    # ── Email Fetching ──────────────────────────────────────────────

    def _fetch_messages(self) -> list[dict[str, Any]]:
        """Fetch unread messages from Gmail API (synchronous).

        Returns:
            List of parsed email dicts ready for action file creation.
        """
        if self.service is None:
            self._authenticate()

        query = self.gmail_config.get("query", DEFAULT_QUERY)
        max_results = self.gmail_config.get("max_results", 10)
        print(f"[DEBUG] Gmail query: {query!r}  max_results={max_results}")
        exclude_senders = self.gmail_config.get("exclude_senders", [])
        snippet_max_length = self.gmail_config.get("snippet_max_length", 1000)

        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        messages = results.get("messages", [])
        if not messages:
            self.logger.debug("No matching messages found")
            return []

        parsed: list[dict[str, Any]] = []

        for msg_ref in messages:
            msg_id = msg_ref["id"]

            if msg_id in self._processed_ids:
                continue

            msg = (
                self.service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            )

            headers = msg.get("payload", {}).get("headers", [])
            from_addr = _get_header(headers, "From")
            subject = _get_header(headers, "Subject")
            to_addr = _get_header(headers, "To")
            date = _get_header(headers, "Date")

            # Filter excluded senders
            if self._is_excluded_sender(from_addr, exclude_senders):
                self.logger.debug("Skipping excluded sender: %s", from_addr)
                continue

            snippet = msg.get("snippet", "")[:snippet_max_length]
            labels = msg.get("labelIds", [])
            thread_id = msg.get("threadId", "")

            priority = self._classify_priority(subject, snippet)

            parsed.append(
                {
                    "message_id": msg_id,
                    "thread_id": thread_id,
                    "from": from_addr,
                    "to": to_addr,
                    "subject": subject,
                    "received": date,
                    "snippet": snippet,
                    "labels": labels,
                    "priority": priority,
                }
            )

        return parsed

    async def check_for_updates(self) -> list[dict[str, Any]]:
        """Poll Gmail for new unread important messages.

        Returns:
            List of email dicts that need action files created.
        """
        print(f"[DEBUG] check_for_updates: DRY_RUN={self.dry_run}, DEV_MODE={self.dev_mode}, vault={self.vault_path}")
        self._load_processed_ids()
        self._cleanup_old_ids()

        try:
            items = await asyncio.to_thread(self._fetch_messages_with_retry)
            self._consecutive_errors = 0
            self._backoff_delay = 1.0
            return items
        except FileNotFoundError:
            raise
        except Exception:
            self._consecutive_errors += 1
            self.logger.exception(
                "Error fetching Gmail messages (consecutive errors: %d)",
                self._consecutive_errors,
            )
            self._log_error("gmail_api", "fetch_failed")
            return []

    def _fetch_messages_with_retry(self) -> list[dict[str, Any]]:
        """Fetch messages with retry logic for transient errors."""
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                return self._fetch_messages()
            except HttpError as e:
                last_error = e
                status = e.resp.status if hasattr(e, "resp") else 0

                if status == 401:
                    self.logger.warning("Auth error, refreshing token")
                    self.service = None
                    self._authenticate()
                    continue

                if status == 429:
                    delay = min(self._backoff_delay * (2**attempt), MAX_BACKOFF_SECONDS)
                    self.logger.warning("Rate limited, backing off %.1fs", delay)
                    import time

                    time.sleep(delay)
                    continue

                if status == 403:
                    self.logger.error("Permission denied: %s", e)
                    raise

                self.logger.warning("Gmail API error (attempt %d): %s", attempt + 1, e)
                import time

                time.sleep(self._backoff_delay * (2**attempt))

            except (ConnectionError, TimeoutError) as e:
                last_error = e
                self.logger.warning("Network error (attempt %d): %s", attempt + 1, e)
                import time

                time.sleep(self._backoff_delay * (2**attempt))

        if last_error:
            raise last_error
        return []

    # ── Priority Classification ─────────────────────────────────────

    def _classify_priority(self, subject: str, snippet: str) -> str:
        """Classify email priority based on keywords in subject and snippet."""
        text = f"{subject} {snippet}".lower()
        priority_keywords = self.gmail_config.get("priority_keywords", {})

        for kw in priority_keywords.get("high", []):
            if kw in text:
                return "high"
        for kw in priority_keywords.get("medium", []):
            if kw in text:
                return "medium"
        return "low"

    # ── Sender Filtering ────────────────────────────────────────────

    @staticmethod
    def _is_excluded_sender(from_addr: str, exclude_patterns: list[str]) -> bool:
        """Check if a sender matches any exclusion pattern."""
        from_lower = from_addr.lower()
        return any(pattern.lower() in from_lower for pattern in exclude_patterns)

    # ── Action File Creation ────────────────────────────────────────

    async def create_action_file(self, item: dict[str, Any]) -> Path | None:
        """Create a markdown action file in Needs_Action for a new email.

        Args:
            item: Parsed email dict from check_for_updates.

        Returns:
            Path to created file, or None if dry_run.
        """
        subject_slug = _slugify(item.get("subject", "no-subject"))
        timestamp = format_filename_timestamp()
        filename = f"email-{subject_slug}-{timestamp}.md"
        file_path = self.needs_action / filename

        email_id = f"EMAIL_{short_id()}_{timestamp}"

        frontmatter: dict[str, Any] = {
            "type": "email",
            "id": email_id,
            "source": "gmail_watcher",
            "from": item["from"],
            "subject": item["subject"],
            "received": item["received"],
            "priority": item["priority"],
            "status": "pending",
            "message_id": item["message_id"],
            "thread_id": item["thread_id"],
        }

        labels_str = ", ".join(item.get("labels", []))
        body = f"""
## Email Content

{item.get("snippet", "(no preview available)")}

## Metadata

- **From:** {item["from"]}
- **Date:** {item["received"]}
- **Labels:** {labels_str}

## Suggested Actions

- [ ] Reply to sender
- [ ] Forward to relevant party
- [ ] Mark as processed
- [ ] Archive after review
"""

        cid = correlation_id()

        if self.dry_run:
            self.logger.info(
                "[DRY RUN] Would create action file: %s (priority: %s, from: %s)",
                filename,
                item["priority"],
                item["from"],
            )
            log_action(
                self.logs_path / "actions",
                {
                    "timestamp": now_iso(),
                    "correlation_id": cid,
                    "actor": "gmail_watcher",
                    "action_type": "email_detected",
                    "target": filename,
                    "result": "dry_run",
                    "parameters": {
                        "message_id": item["message_id"],
                        "subject": item["subject"],
                        "priority": item["priority"],
                        "dry_run": True,
                        "dev_mode": self.dev_mode,
                    },
                },
            )
            return None

        self.needs_action.mkdir(parents=True, exist_ok=True)
        create_file_with_frontmatter(file_path, frontmatter, body)

        # Track as processed
        self._processed_ids[item["message_id"]] = now_iso()
        self._save_processed_ids()

        log_action(
            self.logs_path / "actions",
            {
                "timestamp": now_iso(),
                "correlation_id": cid,
                "actor": "gmail_watcher",
                "action_type": "email_processed",
                "target": filename,
                "result": "success",
                "parameters": {
                    "message_id": item["message_id"],
                    "subject": item["subject"],
                    "priority": item["priority"],
                    "dry_run": False,
                    "dev_mode": self.dev_mode,
                },
            },
        )

        self.logger.info("Created action file: %s (priority: %s)", filename, item["priority"])
        return file_path

    # ── Error Logging ───────────────────────────────────────────────

    def _log_error(self, target: str, error_msg: str) -> None:
        """Log an error to the vault error logs."""
        try:
            log_action(
                self.logs_path / "errors",
                {
                    "timestamp": now_iso(),
                    "correlation_id": correlation_id(),
                    "actor": "gmail_watcher",
                    "action_type": "error",
                    "target": target,
                    "error": error_msg,
                    "details": {
                        "consecutive_errors": self._consecutive_errors,
                        "dev_mode": self.dev_mode,
                    },
                    "result": "failure",
                },
            )
        except Exception:
            self.logger.exception("Failed to write error log")


# ── CLI Entry Point ─────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gmail Watcher - AI Employee Perception Layer")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check and exit",
    )
    parser.add_argument(
        "--auth-only",
        action="store_true",
        help="Only authenticate and save token, then exit",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entry point for the Gmail watcher."""
    # Resolve project root (this file is at backend/watchers/gmail_watcher.py)
    _project_root = Path(__file__).parents[2]
    _env_path = _project_root / "config" / ".env"
    loaded = load_dotenv(dotenv_path=_env_path, override=True)
    print(f"[DEBUG] .env path: {_env_path} | loaded: {loaded}")
    args = _parse_args(argv)

    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    vault_path = os.getenv("VAULT_PATH", "./vault")
    credentials_path = os.getenv("GMAIL_CREDENTIALS_PATH", "config/credentials.json")
    token_path = os.getenv("GMAIL_TOKEN_PATH", "config/token.json")
    check_interval = int(os.getenv("GMAIL_CHECK_INTERVAL", "120"))
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    dev_mode = os.getenv("DEV_MODE", "true").lower() == "true"
    print(f"[DEBUG] DRY_RUN env='{os.getenv('DRY_RUN')}' -> dry_run={dry_run}")
    print(f"[DEBUG] DEV_MODE env='{os.getenv('DEV_MODE')}' -> dev_mode={dev_mode}")
    print(f"[DEBUG] VAULT_PATH={vault_path}")

    gmail_config = _load_gmail_config()

    # Override config with env keywords if set
    keywords_env = os.getenv("GMAIL_KEYWORDS")
    if keywords_env:
        keywords = [k.strip() for k in keywords_env.split(",") if k.strip()]
        gmail_config.setdefault("priority_keywords", {})
        gmail_config["priority_keywords"]["high"] = keywords

    watcher = GmailWatcher(
        vault_path=vault_path,
        credentials_path=credentials_path,
        token_path=token_path,
        check_interval=check_interval,
        gmail_config=gmail_config,
        dry_run=dry_run,
        dev_mode=dev_mode,
    )

    if args.auth_only:
        logger.info("Authenticating Gmail API...")
        watcher._authenticate()
        logger.info("Authentication successful. Token saved to %s", token_path)
        return

    if args.once:
        logger.info("Running single Gmail check...")

        async def single_check() -> None:
            items = await watcher.check_for_updates()
            for item in items:
                await watcher.create_action_file(item)
            logger.info("Check complete. Found %d new emails.", len(items))

        asyncio.run(single_check())
        return

    logger.info("Starting Gmail watcher (interval: %ds, dry_run: %s)", check_interval, dry_run)
    asyncio.run(watcher.run())


if __name__ == "__main__":
    main()
