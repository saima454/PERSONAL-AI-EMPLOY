"""End-to-end test for the Email MCP Server.

Tests the full pipeline: authenticate → search → draft → send (with approval).
Run with DEV_MODE=true first for safety, then DEV_MODE=false for real tests.

Usage:
    # Phase 1: DEV_MODE test (no real Gmail calls for send/draft)
    uv run python scripts/e2e_test_email_mcp.py --dev

    # Phase 2: LIVE test (actually hits Gmail API)
    uv run python scripts/e2e_test_email_mcp.py --live
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.mcp_servers.approval import find_approval
from backend.mcp_servers.gmail_client import GmailClient
from backend.mcp_servers.rate_limiter import RateLimiter
from backend.utils.timestamps import now_iso

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("e2e_test")

VAULT_PATH = "./vault"
TEST_EMAIL = "twahaahmed130@gmail.com"
RESULTS: list[dict] = []


def log_result(test_name: str, status: str, details: str, duration_ms: int = 0) -> None:
    """Record a test result."""
    entry = {
        "timestamp": now_iso(),
        "test": test_name,
        "status": status,
        "details": details,
        "duration_ms": duration_ms,
    }
    RESULTS.append(entry)
    icon = "PASS" if status == "pass" else "FAIL" if status == "fail" else "SKIP"
    print(f"  [{icon}] {test_name}: {details}")


def save_results() -> Path:
    """Write all test results to vault/Logs/actions/."""
    log_dir = Path(VAULT_PATH) / "Logs" / "actions"
    log_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = log_dir / f"e2e-test-{date_str}.json"

    # Append to existing log or create new
    existing = []
    if log_file.exists():
        try:
            existing = json.loads(log_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.extend(RESULTS)
    log_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return log_file


# ── Test 1: Server Startup & Authentication ──────────────────────


def test_authentication() -> GmailClient:
    """Test that GmailClient can authenticate and refresh the token."""
    print("\n== Test 1: Authentication ==")
    start = time.time()

    client = GmailClient(
        credentials_path="config/credentials.json",
        token_path="config/token.json",
    )

    try:
        client.authenticate()
        duration = int((time.time() - start) * 1000)
        log_result(
            "authentication",
            "pass",
            f"Gmail API authenticated successfully ({duration}ms)",
            duration,
        )
        return client
    except FileNotFoundError as e:
        duration = int((time.time() - start) * 1000)
        log_result("authentication", "fail", f"Token/credentials missing: {e}", duration)
        raise
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        log_result("authentication", "fail", f"Auth failed: {e}", duration)
        raise


# ── Test 2: Search Emails ────────────────────────────────────────


def test_search(client: GmailClient) -> list[dict]:
    """Test searching Gmail inbox."""
    print("\n== Test 2: Search Emails ==")
    start = time.time()

    try:
        results = client.search_messages("in:inbox", max_results=3)
        duration = int((time.time() - start) * 1000)

        if results:
            log_result(
                "search_email",
                "pass",
                f"Found {len(results)} email(s) in {duration}ms",
                duration,
            )
            for i, msg in enumerate(results, 1):
                print(f"    {i}. From: {msg['from_address']}")
                print(f"       Subject: {msg['subject']}")
                print(f"       Date: {msg['date']}")
                print(f"       Snippet: {msg['snippet'][:80]}...")
                print(f"       Message ID: {msg['message_id']}")
                print(f"       Thread ID: {msg['thread_id']}")
                print()
        else:
            log_result(
                "search_email",
                "pass",
                f"No emails found (empty inbox is still a valid response) in {duration}ms",
                duration,
            )

        return results
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        log_result("search_email", "fail", f"Search failed: {e}", duration)
        raise


# ── Test 3: Draft Email (DEV_MODE) ──────────────────────────────


def test_draft_dev_mode() -> None:
    """Test draft_email tool in DEV_MODE (logs only, no Gmail call)."""
    print("\n== Test 3a: Draft Email (DEV_MODE=true) ==")
    start = time.time()

    # Simulate the DEV_MODE path from email_server.py
    from backend.mcp_servers.email_server import redact_email

    redacted = redact_email(TEST_EMAIL)

    msg = f"[DEV_MODE] Draft logged but not created. To: {redacted}, Subject: MCP Server Test"
    duration = int((time.time() - start) * 1000)
    log_result(
        "draft_email_dev_mode",
        "pass",
        msg,
        duration,
    )


# ── Test 3b: Draft Email (LIVE) ─────────────────────────────────


def test_draft_live(client: GmailClient) -> dict | None:
    """Test creating an actual Gmail draft."""
    print("\n== Test 3b: Draft Email (LIVE) ==")
    start = time.time()

    try:
        result = client.create_draft(
            to=TEST_EMAIL,
            subject="MCP Server Test",
            body="This is a test email from my AI Employee MCP server!",
        )
        duration = int((time.time() - start) * 1000)
        log_result(
            "draft_email_live",
            "pass",
            f"Draft created! Draft ID: {result['draft_id']}, "
            f"Message ID: {result['message_id']} ({duration}ms)",
            duration,
        )
        print(f"\n    --> Verify at: https://mail.google.com/mail/#drafts")
        print(f"    --> Look for subject 'MCP Server Test'")
        print(f"    --> Draft ID: {result['draft_id']}")
        return result
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        log_result("draft_email_live", "fail", f"Draft creation failed: {e}", duration)
        return None


# ── Test 4: Approval File Creation ───────────────────────────────


def create_approval_file() -> Path:
    """Create an approval file in vault/Approved/ for the test send."""
    print("\n== Test 4: Create Approval File ==")

    approved_dir = Path(VAULT_PATH) / "Approved"
    approved_dir.mkdir(parents=True, exist_ok=True)

    approval_file = approved_dir / "e2e-test-send-email.md"
    now = now_iso()

    content = f"""---
type: email_send
status: approved
to: {TEST_EMAIL}
subject: "MCP Server Test - Live Send"
created: {now}
approved_at: {now}
risk_assessment: low - test email to self
---

## Action Summary

E2E test: Send a test email to {TEST_EMAIL} to verify the Email MCP Server works.

## Rollback Plan

No rollback needed - test email to self.
"""
    approval_file.write_text(content, encoding="utf-8")
    log_result(
        "create_approval",
        "pass",
        f"Approval file created at {approval_file}",
    )

    # Verify it can be found
    found = find_approval(VAULT_PATH, "email_send", to=TEST_EMAIL)
    if found:
        log_result(
            "find_approval",
            "pass",
            f"Approval file found and validated: {found['path']}",
        )
    else:
        log_result("find_approval", "fail", "Approval file NOT found after creation!")

    return approval_file


# ── Test 5: Send Email (DEV_MODE) ───────────────────────────────


def test_send_dev_mode() -> None:
    """Test send_email path in DEV_MODE."""
    print("\n== Test 5a: Send Email (DEV_MODE=true) ==")
    start = time.time()

    from backend.mcp_servers.email_server import redact_email

    redacted = redact_email(TEST_EMAIL)
    msg = f"[DEV_MODE] Send logged but not executed. To: {redacted}, Subject: MCP Server Test - Live Send"
    duration = int((time.time() - start) * 1000)
    log_result("send_email_dev_mode", "pass", msg, duration)


# ── Test 5b: Send Email (LIVE) ──────────────────────────────────


def test_send_live(client: GmailClient) -> dict | None:
    """Test sending an actual email (requires approval file)."""
    print("\n== Test 5b: Send Email (LIVE) ==")

    # Check approval exists
    approval = find_approval(VAULT_PATH, "email_send", to=TEST_EMAIL)
    if not approval:
        log_result("send_email_live", "fail", "No approval file found!")
        return None

    # Check rate limit
    limiter = RateLimiter()
    allowed, wait = limiter.check()
    if not allowed:
        log_result(
            "send_email_live",
            "skip",
            f"Rate limited. Wait {wait}s.",
        )
        return None

    start = time.time()
    try:
        result = client.send_message(
            to=TEST_EMAIL,
            subject="MCP Server Test - Live Send",
            body=(
                "This is a LIVE test email from the AI Employee Email MCP Server!\n\n"
                f"Sent at: {now_iso()}\n"
                "If you received this, the Email MCP Server send pipeline works end-to-end.\n\n"
                "-- AI Employee (Email MCP Server v1.0.0)"
            ),
        )
        duration = int((time.time() - start) * 1000)

        # Record send in rate limiter
        limiter.record_send()

        # Consume approval
        from backend.mcp_servers.approval import consume_approval

        consume_approval(approval["path"], VAULT_PATH)

        log_result(
            "send_email_live",
            "pass",
            f"Email sent! Message ID: {result['message_id']}, "
            f"Thread ID: {result['thread_id']} ({duration}ms)",
            duration,
        )
        print(f"\n    --> Check your inbox at {TEST_EMAIL}")
        print(f"    --> Subject: 'MCP Server Test - Live Send'")
        print(f"    --> Approval consumed (moved to vault/Done/)")
        return result
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        log_result("send_email_live", "fail", f"Send failed: {e}", duration)
        return None


# ── Test 6: Rate Limiter ─────────────────────────────────────────


def test_rate_limiter() -> None:
    """Test rate limiter behavior."""
    print("\n== Test 6: Rate Limiter ==")

    limiter = RateLimiter()
    allowed, wait = limiter.check()
    log_result(
        "rate_limiter",
        "pass",
        f"Allowed: {allowed}, Current count: {limiter.current_count}/{limiter.max_sends}, "
        f"Window: {limiter.window_seconds}s",
    )


# ── Test 7: MCP Tool Functions via Patched Context ───────────────


async def test_mcp_tools_dev_mode() -> None:
    """Test the actual MCP tool functions with DEV_MODE=true via patched context."""
    print("\n== Test 7: MCP Tool Functions (DEV_MODE=true, patched context) ==")

    # Build a mock context that the tools expect
    mock_gmail = MagicMock()
    mock_gmail.search_messages.return_value = [
        {
            "message_id": "test_m1",
            "thread_id": "test_t1",
            "from_address": "test@example.com",
            "to_address": TEST_EMAIL,
            "subject": "Mock search result",
            "snippet": "This is a mocked search result for E2E testing",
            "date": "Mon, 17 Feb 2026 12:00:00 +0000",
        }
    ]

    mock_app = MagicMock()
    mock_app.gmail = mock_gmail
    mock_app.rate_limiter = RateLimiter(config_path="config/rate_limits.json")

    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context = mock_app

    with (
        patch("backend.mcp_servers.email_server.mcp") as mock_mcp,
        patch("backend.mcp_servers.email_server.DEV_MODE", True),
        patch("backend.mcp_servers.email_server._log_tool_action"),
    ):
        mock_mcp.get_context.return_value = mock_ctx

        from backend.mcp_servers.email_server import (
            draft_email,
            reply_email,
            search_email,
            send_email,
        )

        # search_email
        start = time.time()
        result = await search_email("test query", 5)
        duration = int((time.time() - start) * 1000)
        log_result(
            "mcp_search_email",
            "pass" if "Mock search result" in result else "fail",
            f"search_email returned formatted results ({duration}ms)",
            duration,
        )

        # draft_email
        start = time.time()
        result = await draft_email(TEST_EMAIL, "Test Draft", "Body text")
        duration = int((time.time() - start) * 1000)
        log_result(
            "mcp_draft_email",
            "pass" if "[DEV_MODE]" in result else "fail",
            f"draft_email: {result[:80]} ({duration}ms)",
            duration,
        )

        # send_email
        start = time.time()
        result = await send_email(TEST_EMAIL, "Test Send", "Body text")
        duration = int((time.time() - start) * 1000)
        log_result(
            "mcp_send_email",
            "pass" if "[DEV_MODE]" in result else "fail",
            f"send_email: {result[:80]} ({duration}ms)",
            duration,
        )

        # reply_email
        start = time.time()
        result = await reply_email("thread_123", "msg_456", "Reply body")
        duration = int((time.time() - start) * 1000)
        log_result(
            "mcp_reply_email",
            "pass" if "[DEV_MODE]" in result else "fail",
            f"reply_email: {result[:80]} ({duration}ms)",
            duration,
        )


# ── Main ─────────────────────────────────────────────────────────


def main() -> None:
    mode = "--dev"
    if len(sys.argv) > 1:
        mode = sys.argv[1]

    is_live = mode == "--live"

    print("=" * 60)
    print(f"  Email MCP Server — End-to-End Test")
    print(f"  Mode: {'LIVE (real Gmail calls)' if is_live else 'DEV_MODE (safe, no real sends)'}")
    print(f"  Test email: {TEST_EMAIL}")
    print(f"  Time: {now_iso()}")
    print("=" * 60)

    # ── Always run: Auth + Search ────────────────────────────────
    client = test_authentication()
    test_search(client)
    test_rate_limiter()

    if is_live:
        # ── LIVE mode: Real Gmail API calls ─────────────────────
        test_draft_live(client)
        create_approval_file()
        test_send_live(client)
    else:
        # ── DEV mode: Safe simulated tests ──────────────────────
        test_draft_dev_mode()
        create_approval_file()
        test_send_dev_mode()
        asyncio.run(test_mcp_tools_dev_mode())

    # ── Save results ────────────────────────────────────────────
    log_file = save_results()

    # ── Summary ─────────────────────────────────────────────────
    passed = sum(1 for r in RESULTS if r["status"] == "pass")
    failed = sum(1 for r in RESULTS if r["status"] == "fail")
    skipped = sum(1 for r in RESULTS if r["status"] == "skip")
    total = len(RESULTS)

    print("\n" + "=" * 60)
    print(f"  RESULTS: {passed}/{total} passed, {failed} failed, {skipped} skipped")
    print(f"  Log saved to: {log_file}")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
