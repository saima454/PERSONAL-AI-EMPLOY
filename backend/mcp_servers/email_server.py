"""Email MCP Server — exposes Gmail tools via Model Context Protocol.

This is the ACTION layer entry point. It registers four tools
(search_email, draft_email, send_email, reply_email) and communicates
via stdio transport.

Usage:
    uv run python -m backend.mcp_servers.email_server
    uv run python -m backend.mcp_servers.email_server --auth-only
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from googleapiclient.errors import HttpError
from mcp.server.fastmcp import FastMCP

from backend.mcp_servers.approval import consume_approval, find_approval
from backend.mcp_servers.gmail_client import GmailClient
from backend.mcp_servers.rate_limiter import RateLimiter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso
from backend.utils.uuid_utils import correlation_id

# ── Configuration ───────────────────────────────────────────────────

load_dotenv()

DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
VAULT_PATH = os.getenv("VAULT_PATH", "./vault")
CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "config/credentials.json")
TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "config/token.json")

# Logging MUST go to stderr (stdout is reserved for MCP JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────


def redact_email(address: str) -> str:
    """Redact an email address for logging: ``john@example.com`` → ``j***@example.com``."""
    match = re.match(r"^([^@])", address)
    if match and "@" in address:
        local, domain = address.split("@", 1)
        return f"{local[0]}***@{domain}"
    return "***"


def _log_tool_action(
    action_type: str,
    target: str,
    result: str,
    cid: str,
    duration_ms: int = 0,
    parameters: dict[str, Any] | None = None,
) -> None:
    """Write an audit log entry to vault/Logs/actions/."""
    log_dir = Path(VAULT_PATH) / "Logs" / "actions"
    try:
        log_action(
            log_dir,
            {
                "timestamp": now_iso(),
                "correlation_id": cid,
                "actor": "email_mcp",
                "action_type": action_type,
                "target": target,
                "result": result,
                "duration_ms": duration_ms,
                "parameters": parameters or {},
            },
        )
    except OSError:
        logger.exception("Failed to write audit log")


# ── Lifespan ────────────────────────────────────────────────────────


@dataclass
class AppContext:
    """Shared state injected into MCP tool handlers."""

    gmail: GmailClient
    rate_limiter: RateLimiter


@asynccontextmanager
async def app_lifespan(_server: FastMCP) -> AsyncIterator[AppContext]:
    """Initialize Gmail client and rate limiter on server startup."""
    gmail = GmailClient(
        credentials_path=CREDENTIALS_PATH,
        token_path=TOKEN_PATH,
    )
    # Authenticate eagerly so startup failures are caught early
    if not DEV_MODE:
        await asyncio.to_thread(gmail.authenticate)
    else:
        logger.info("[DEV_MODE] Skipping Gmail authentication")

    rate_limiter = RateLimiter()
    logger.info(
        "Email MCP server started (DEV_MODE=%s, vault=%s)",
        DEV_MODE,
        VAULT_PATH,
    )
    try:
        yield AppContext(gmail=gmail, rate_limiter=rate_limiter)
    finally:
        logger.info("Email MCP server shutting down")


# ── Server ──────────────────────────────────────────────────────────

mcp = FastMCP(
    "email-mcp-server",
    instructions=(
        "Email tools for Gmail. search_email is always available. "
        "draft_email creates drafts (no approval needed). "
        "send_email and reply_email require an approval file in vault/Approved/."
    ),
    lifespan=app_lifespan,
)


# ── Tool: search_email ──────────────────────────────────────────────


@mcp.tool()
async def search_email(query: str, max_results: int = 5) -> str:
    """Search Gmail for emails matching a query.

    Uses Gmail search syntax (e.g. 'from:user@example.com subject:invoice').

    Args:
        query: Gmail search query string.
        max_results: Maximum number of results (1-50, default 5).
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    try:
        max_results = max(1, min(50, max_results))
        results = await asyncio.to_thread(app.gmail.search_messages, query, max_results)
        duration_ms = int((time.time() - start) * 1000)

        _log_tool_action(
            "search_email",
            f"query={query[:50]}",
            "success",
            cid,
            duration_ms,
            {"query": query[:50], "max_results": max_results, "count": len(results)},
        )

        if not results:
            return f"No emails found matching: {query}"

        lines = [f'Found {len(results)} email(s) matching "{query}":\n']
        for i, msg in enumerate(results, 1):
            lines.append(
                f"{i}. From: {msg['from_address']} | "
                f"Subject: {msg['subject']} | "
                f"Date: {msg['date']}"
            )
            lines.append(f"   Snippet: {msg['snippet'][:200]}")
            lines.append(f"   Message ID: {msg['message_id']} | Thread ID: {msg['thread_id']}")
            lines.append("")
        return "\n".join(lines)

    except HttpError as exc:
        duration_ms = int((time.time() - start) * 1000)
        _log_tool_action("search_email", f"query={query[:50]}", "error", cid, duration_ms)
        return f"Error searching emails: {exc}"
    except FileNotFoundError as exc:
        return f"Authentication error: {exc}"


# ── Tool: draft_email ───────────────────────────────────────────────


@mcp.tool()
async def draft_email(to: str, subject: str, body: str) -> str:
    """Create an email draft in Gmail (does not send).

    The draft appears in the user's Gmail Drafts folder for review.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain text email body.
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()
    redacted = redact_email(to)

    # Validate
    if "@" not in to:
        _log_tool_action(
            "draft_email", redacted, "error", cid, parameters={"error": "invalid_email"}
        )
        return f"Error: Invalid email address format: {to}"

    # DEV_MODE check
    if DEV_MODE:
        _log_tool_action(
            "draft_email",
            redacted,
            "dev_mode",
            cid,
            parameters={"subject": subject[:50]},
        )
        return f"[DEV_MODE] Draft logged but not created. To: {redacted}, Subject: {subject[:50]}"

    try:
        result = await asyncio.to_thread(app.gmail.create_draft, to, subject, body)
        duration_ms = int((time.time() - start) * 1000)

        _log_tool_action(
            "draft_email",
            redacted,
            "success",
            cid,
            duration_ms,
            {"subject": subject[:50], "draft_id": result["draft_id"]},
        )
        return (
            f"Draft created successfully. Draft ID: {result['draft_id']}. "
            f"Review it in your Gmail drafts folder."
        )

    except HttpError as exc:
        duration_ms = int((time.time() - start) * 1000)
        _log_tool_action("draft_email", redacted, "error", cid, duration_ms)
        return f"Error creating draft: {exc}"
    except FileNotFoundError as exc:
        return f"Authentication error: {exc}"


# ── Tool: send_email ────────────────────────────────────────────────


@mcp.tool()
async def send_email(to: str, subject: str, body: str) -> str:
    """Send an email via Gmail. Requires an approval file in vault/Approved/.

    The approval file must have type: email_send, status: approved,
    and a matching 'to' field. Rate limited to 10 emails per hour.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Plain text email body.
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()
    redacted = redact_email(to)

    # Validate
    if "@" not in to:
        _log_tool_action(
            "send_email", redacted, "error", cid, parameters={"error": "invalid_email"}
        )
        return f"Error: Invalid email address format: {to}"

    # DEV_MODE check
    if DEV_MODE:
        _log_tool_action(
            "send_email",
            redacted,
            "dev_mode",
            cid,
            parameters={"subject": subject[:50]},
        )
        return f"[DEV_MODE] Send logged but not executed. To: {redacted}, Subject: {subject[:50]}"

    # Approval check
    approval = find_approval(VAULT_PATH, "email_send", to=to)
    if approval is None:
        _log_tool_action(
            "send_email", redacted, "rejected", cid, parameters={"reason": "no_approval"}
        )
        return (
            f"Rejected: No matching approval file found in vault/Approved/ "
            f"for sending to {redacted}. Create an approval file with "
            f"type: email_send and move it to vault/Approved/."
        )

    # Rate limit check
    allowed, wait_seconds = app.rate_limiter.check()
    if not allowed:
        _log_tool_action(
            "send_email",
            redacted,
            "rate_limited",
            cid,
            parameters={"wait_seconds": wait_seconds},
        )
        return (
            f"Rejected: Rate limit exceeded ({app.rate_limiter.max_sends} emails/hour). "
            f"Next send available in {wait_seconds} seconds."
        )

    # Send
    try:
        result = await asyncio.to_thread(app.gmail.send_message, to, subject, body)
        duration_ms = int((time.time() - start) * 1000)

        # Record send and consume approval
        app.rate_limiter.record_send()
        consume_approval(approval["path"], VAULT_PATH)

        _log_tool_action(
            "send_email",
            redacted,
            "success",
            cid,
            duration_ms,
            {
                "subject": subject[:50],
                "message_id": result["message_id"],
                "thread_id": result["thread_id"],
            },
        )
        return (
            f"Email sent successfully. "
            f"Message ID: {result['message_id']} "
            f"Thread ID: {result['thread_id']}"
        )

    except HttpError as exc:
        duration_ms = int((time.time() - start) * 1000)
        _log_tool_action("send_email", redacted, "error", cid, duration_ms)
        return f"Error sending email: {exc}"
    except FileNotFoundError as exc:
        return f"Authentication error: {exc}"


# ── Tool: reply_email ───────────────────────────────────────────────


@mcp.tool()
async def reply_email(thread_id: str, message_id: str, body: str) -> str:
    """Reply to an existing email thread in Gmail.

    Correctly threads the reply using In-Reply-To and References headers.
    Requires an approval file in vault/Approved/ with type: email_reply.

    Args:
        thread_id: Gmail thread ID to reply to.
        message_id: Gmail message ID to reply to (for threading headers).
        body: Plain text reply body.
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    # Validate
    if not thread_id or not message_id:
        _log_tool_action("reply_email", thread_id or "unknown", "error", cid)
        return "Error: thread_id and message_id are required."

    # DEV_MODE check
    if DEV_MODE:
        _log_tool_action(
            "reply_email",
            f"thread={thread_id}",
            "dev_mode",
            cid,
            parameters={"body_length": len(body)},
        )
        return (
            f"[DEV_MODE] Reply logged but not executed. "
            f"Thread: {thread_id}, Body length: {len(body)} chars"
        )

    # Approval check
    approval = find_approval(VAULT_PATH, "email_reply", thread_id=thread_id)
    if approval is None:
        _log_tool_action(
            "reply_email",
            f"thread={thread_id}",
            "rejected",
            cid,
            parameters={"reason": "no_approval"},
        )
        return (
            f"Rejected: No matching approval file found in vault/Approved/ "
            f"for replying to thread {thread_id}. Create an approval file with "
            f"type: email_reply and move it to vault/Approved/."
        )

    # Rate limit check
    allowed, wait_seconds = app.rate_limiter.check()
    if not allowed:
        _log_tool_action(
            "reply_email",
            f"thread={thread_id}",
            "rate_limited",
            cid,
            parameters={"wait_seconds": wait_seconds},
        )
        return (
            f"Rejected: Rate limit exceeded ({app.rate_limiter.max_sends} emails/hour). "
            f"Next send available in {wait_seconds} seconds."
        )

    # Reply
    try:
        result = await asyncio.to_thread(app.gmail.reply_to_thread, thread_id, message_id, body)
        duration_ms = int((time.time() - start) * 1000)

        # Record send and consume approval
        app.rate_limiter.record_send()
        consume_approval(approval["path"], VAULT_PATH)

        _log_tool_action(
            "reply_email",
            f"thread={thread_id}",
            "success",
            cid,
            duration_ms,
            {
                "message_id": result["message_id"],
                "thread_id": result["thread_id"],
            },
        )
        return (
            f"Reply sent successfully. "
            f"Message ID: {result['message_id']} "
            f"Thread ID: {result['thread_id']}"
        )

    except HttpError as exc:
        duration_ms = int((time.time() - start) * 1000)
        status = exc.resp.status if hasattr(exc, "resp") else 0
        if status == 404:
            _log_tool_action("reply_email", f"thread={thread_id}", "error", cid, duration_ms)
            return f"Error: Thread ID {thread_id} not found or no longer accessible."
        _log_tool_action("reply_email", f"thread={thread_id}", "error", cid, duration_ms)
        return f"Error replying to thread: {exc}"
    except FileNotFoundError as exc:
        return f"Authentication error: {exc}"


# ── Entry Point ─────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point for the email MCP server."""
    if "--auth-only" in sys.argv:
        gmail = GmailClient(
            credentials_path=CREDENTIALS_PATH,
            token_path=TOKEN_PATH,
        )
        gmail.authorize_interactive()
        logger.info("Authentication complete. Token saved.")
        return

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
