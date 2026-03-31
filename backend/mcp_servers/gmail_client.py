"""Gmail API client for the Email MCP server.

Synchronous wrapper around google-api-python-client. All methods are
designed to be called via ``asyncio.to_thread()`` from async MCP tools.

Reuses the OAuth pattern established in ``backend/watchers/gmail_watcher.py``.
"""

from __future__ import annotations

import base64
import logging
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 503}


def _get_header(headers: list[dict[str, str]], name: str) -> str:
    """Extract a header value from Gmail API message headers."""
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


class GmailClient:
    """Synchronous Gmail API client with authentication and retry logic."""

    def __init__(
        self,
        credentials_path: str = "config/credentials.json",
        token_path: str = "config/token.json",
    ) -> None:
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.service: Any = None

    def authenticate(self) -> None:
        """Load or refresh OAuth credentials and build the Gmail API service.

        Raises:
            FileNotFoundError: If no valid token exists and credentials file is missing.
            RuntimeError: If authentication fails.
        """
        creds: Credentials | None = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Gmail token")
            creds.refresh(Request())
            self.token_path.write_text(creds.to_json(), encoding="utf-8")

        if not creds or not creds.valid:
            msg = (
                f"No valid Gmail token at {self.token_path}. Run with --auth-only to re-authorize."
            )
            raise FileNotFoundError(msg)

        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API authenticated successfully")

    def authorize_interactive(self) -> None:
        """Run interactive OAuth flow to obtain new credentials.

        Use this when the token is missing or needs scope expansion (e.g.
        adding ``gmail.send``).
        """
        if not self.credentials_path.exists():
            msg = f"No credentials file at {self.credentials_path}"
            raise FileNotFoundError(msg)

        flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        self.service = build("gmail", "v1", credentials=creds)
        logger.info("Gmail API authorized and token saved to %s", self.token_path)

    def _ensure_service(self) -> None:
        """Authenticate if service is not yet initialized."""
        if self.service is None:
            self.authenticate()

    def _execute_with_retry(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute a callable with exponential backoff retry for transient errors.

        Retries on HTTP 401 (with re-auth), 429, 500, 503.

        Args:
            fn: Callable to execute.
            *args: Positional arguments for the callable.
            **kwargs: Keyword arguments for the callable.

        Returns:
            The result of the callable.

        Raises:
            HttpError: If all retries are exhausted.
        """
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except HttpError as exc:
                last_error = exc
                status = exc.resp.status if hasattr(exc, "resp") else 0

                if status == 401:
                    logger.warning("Auth error (attempt %d), refreshing token", attempt + 1)
                    self.service = None
                    self.authenticate()
                    continue

                if status in RETRYABLE_STATUS_CODES:
                    delay = INITIAL_BACKOFF * (2**attempt)
                    logger.warning(
                        "Retryable error %d (attempt %d), backing off %.1fs",
                        status,
                        attempt + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                # Non-retryable error
                raise

            except (ConnectionError, TimeoutError) as exc:
                last_error = exc
                delay = INITIAL_BACKOFF * (2**attempt)
                logger.warning("Network error (attempt %d): %s", attempt + 1, exc)
                time.sleep(delay)

        if last_error:
            raise last_error
        return None  # pragma: no cover

    # ── Search ──────────────────────────────────────────────────────

    def search_messages(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Search Gmail messages matching a query.

        Args:
            query: Gmail search query string.
            max_results: Maximum number of results to return.

        Returns:
            List of dicts with message_id, thread_id, from_address,
            to_address, subject, snippet, date.
        """
        self._ensure_service()

        def _search() -> list[dict[str, Any]]:
            response = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            messages = response.get("messages", [])
            if not messages:
                return []

            results: list[dict[str, Any]] = []
            for msg_ref in messages:
                msg = (
                    self.service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_ref["id"],
                        format="metadata",
                        metadataHeaders=["From", "To", "Subject", "Date"],
                    )
                    .execute()
                )
                headers = msg.get("payload", {}).get("headers", [])
                results.append(
                    {
                        "message_id": msg["id"],
                        "thread_id": msg.get("threadId", ""),
                        "from_address": _get_header(headers, "From"),
                        "to_address": _get_header(headers, "To"),
                        "subject": _get_header(headers, "Subject"),
                        "snippet": msg.get("snippet", ""),
                        "date": _get_header(headers, "Date"),
                    }
                )
            return results

        return self._execute_with_retry(_search)

    # ── Draft ───────────────────────────────────────────────────────

    def create_draft(self, to: str, subject: str, body: str) -> dict[str, str]:
        """Create a draft email in Gmail.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain text email body.

        Returns:
            Dict with draft_id and message_id.
        """
        self._ensure_service()

        def _create() -> dict[str, str]:
            message = EmailMessage()
            message.set_content(body)
            message["To"] = to
            message["Subject"] = subject

            encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
            result = (
                self.service.users()
                .drafts()
                .create(userId="me", body={"message": {"raw": encoded}})
                .execute()
            )
            return {
                "draft_id": result["id"],
                "message_id": result["message"]["id"],
            }

        return self._execute_with_retry(_create)

    # ── Send ────────────────────────────────────────────────────────

    def send_message(self, to: str, subject: str, body: str) -> dict[str, str]:
        """Send an email via Gmail.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain text email body.

        Returns:
            Dict with message_id and thread_id.
        """
        self._ensure_service()

        def _send() -> dict[str, str]:
            message = EmailMessage()
            message.set_content(body)
            message["To"] = to
            message["Subject"] = subject

            encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
            result = (
                self.service.users().messages().send(userId="me", body={"raw": encoded}).execute()
            )
            return {
                "message_id": result["id"],
                "thread_id": result.get("threadId", ""),
            }

        return self._execute_with_retry(_send)

    # ── Reply ───────────────────────────────────────────────────────

    def get_message_headers(self, message_id: str) -> dict[str, str]:
        """Fetch headers from a specific Gmail message.

        Args:
            message_id: Gmail message ID.

        Returns:
            Dict with Message-ID, References, Subject, From, To headers.
        """
        self._ensure_service()

        def _fetch() -> dict[str, str]:
            msg = (
                self.service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=[
                        "Message-ID",
                        "References",
                        "Subject",
                        "From",
                        "To",
                    ],
                )
                .execute()
            )
            headers = msg.get("payload", {}).get("headers", [])
            return {
                "message_id_header": _get_header(headers, "Message-ID"),
                "references": _get_header(headers, "References"),
                "subject": _get_header(headers, "Subject"),
                "from": _get_header(headers, "From"),
                "to": _get_header(headers, "To"),
            }

        return self._execute_with_retry(_fetch)

    def reply_to_thread(
        self,
        thread_id: str,
        message_id: str,
        body: str,
    ) -> dict[str, str]:
        """Reply to an existing email thread.

        Correctly sets In-Reply-To, References, and Subject headers for
        Gmail to thread the reply.

        Args:
            thread_id: Gmail thread ID.
            message_id: Gmail message ID of the message being replied to.
            body: Plain text reply body.

        Returns:
            Dict with message_id and thread_id of the sent reply.
        """
        self._ensure_service()
        original_headers = self.get_message_headers(message_id)

        def _reply() -> dict[str, str]:
            message = EmailMessage()
            message.set_content(body)

            # Set reply-to address
            message["To"] = original_headers["from"]

            # Thread the subject
            subject = original_headers["subject"]
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"
            message["Subject"] = subject

            # Set threading headers
            mime_message_id = original_headers["message_id_header"]
            references = original_headers["references"]
            if mime_message_id:
                message["In-Reply-To"] = mime_message_id
                message["References"] = f"{references} {mime_message_id}".strip()

            encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
            result = (
                self.service.users()
                .messages()
                .send(
                    userId="me",
                    body={"raw": encoded, "threadId": thread_id},
                )
                .execute()
            )
            return {
                "message_id": result["id"],
                "thread_id": result.get("threadId", ""),
            }

        return self._execute_with_retry(_reply)
