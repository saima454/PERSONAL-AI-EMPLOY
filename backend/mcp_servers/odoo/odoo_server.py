"""Odoo Accounting MCP Server — exposes 8 tools via Model Context Protocol.

This is the ACTION layer entry point for Odoo integration.  It registers
eight tools (5 read-only + 3 write) and communicates via stdio transport.

Read tools (no approval required):
    list_invoices, get_invoice, list_customers, get_account_balance, list_transactions

Write tools (HITL required for invoice/payment; rate-limited for all):
    create_invoice, create_payment, create_customer

Usage:
    uv run python -m backend.mcp_servers.odoo.odoo_server
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
import time
import xmlrpc.client
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from backend.mcp_servers.approval import consume_approval, find_approval
from backend.mcp_servers.odoo.odoo_client import OdooClient
from backend.mcp_servers.odoo.utils import get_financial_summary
from backend.mcp_servers.rate_limiter import RateLimiter
from backend.utils.frontmatter import update_frontmatter
from backend.utils.logging_utils import log_action
from backend.utils.timestamps import now_iso
from backend.utils.uuid_utils import correlation_id

# ── Configuration ────────────────────────────────────────────────────

load_dotenv(dotenv_path="config/.env")

DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"
VAULT_PATH = os.getenv("VAULT_PATH", "./vault")
ODOO_URL = os.getenv("ODOO_URL", "http://localhost:8069")
ODOO_DATABASE = os.getenv("ODOO_DATABASE", "ai_employee")
ODOO_USERNAME = os.getenv("ODOO_USERNAME", "")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")

# Logging MUST go to stderr (stdout is reserved for MCP JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ── Rate Limiter ─────────────────────────────────────────────────────


class OdooRateLimiter(RateLimiter):
    """Sliding-window rate limiter for Odoo write operations.

    Reads ``odoo.writes_per_hour`` from ``config/rate_limits.json``.
    Default: 20 write operations per hour (shared across all 3 write tools).
    """

    def _load_config(self, config_path: str) -> None:
        """Override to read from the ``odoo`` section."""
        path = Path(config_path)
        default_max = 20

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                odoo_config = data.get("odoo", {})
                self.max_sends = odoo_config.get("writes_per_hour", default_max)
            except (json.JSONDecodeError, KeyError):
                logger.warning("Failed to parse odoo rate limits config, using defaults")
                self.max_sends = default_max
        else:
            self.max_sends = default_max

        self.window_seconds = 3600
        logger.info(
            "Odoo rate limiter initialized: %d write ops per %d seconds",
            self.max_sends,
            self.window_seconds,
        )


# ── Application Context ───────────────────────────────────────────────


@dataclass
class AppContext:
    """Shared state injected into MCP tool handlers."""

    client: OdooClient
    rate_limiter: OdooRateLimiter


# ── Helpers ──────────────────────────────────────────────────────────


def _log_tool_action(
    action_type: str,
    target: str,
    result: str,
    cid: str,
    duration_ms: int = 0,
    parameters: dict[str, Any] | None = None,
) -> None:
    """Write an audit log entry to vault/Logs/actions/ and vault/Logs/odoo/."""
    entry = {
        "timestamp": now_iso(),
        "correlation_id": cid,
        "actor": "odoo_mcp",
        "action_type": action_type,
        "target": target,
        "result": result,
        "duration_ms": duration_ms,
        "parameters": parameters or {},
    }
    # Write to general action log
    log_dir = Path(VAULT_PATH) / "Logs" / "actions"
    try:
        log_action(log_dir, entry)
    except OSError:
        logger.exception("Failed to write audit log")
    # Write to Odoo-specific log
    odoo_log_dir = Path(VAULT_PATH) / "Logs" / "odoo"
    try:
        log_action(odoo_log_dir, entry)
    except OSError:
        logger.exception("Failed to write Odoo log")


def _reject_approval_file(file_path: Path, reason: str) -> None:
    """Move an approval file to vault/Rejected/ with rejection metadata.

    Args:
        file_path: Path to the approval file in vault/Approved/.
        reason: Human-readable rejection reason (truncated to 200 chars).
    """
    rejected_dir = Path(VAULT_PATH) / "Rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    dest = rejected_dir / file_path.name

    # Avoid overwrite collisions
    if dest.exists():
        stem = file_path.stem
        suffix = file_path.suffix
        ts = now_iso().replace(":", "-").replace(".", "-")
        dest = rejected_dir / f"{stem}_{ts}{suffix}"

    try:
        update_frontmatter(
            file_path,
            {
                "status": "rejected",
                "rejection_reason": reason[:200],
                "rejected_at": now_iso(),
            },
        )
    except (FileNotFoundError, OSError):
        logger.warning("Could not update frontmatter on %s before rejecting", file_path)

    shutil.move(str(file_path), str(dest))
    logger.info("Rejected approval file: %s → %s", file_path.name, dest.name)


# ── Lifespan ─────────────────────────────────────────────────────────


@asynccontextmanager
async def app_lifespan(_server: FastMCP) -> AsyncIterator[AppContext]:
    """Initialize OdooClient and rate limiter on server startup."""
    client = OdooClient(
        url=ODOO_URL,
        db=ODOO_DATABASE,
        username=ODOO_USERNAME,
        api_key=ODOO_API_KEY,
        dev_mode=DEV_MODE,
    )

    if not DEV_MODE:
        try:
            await asyncio.to_thread(client.authenticate)
        except ConnectionError as exc:
            logger.error("Odoo authentication failed on startup: %s", exc)
            # Don't crash server — tools will report errors per-call
    else:
        client._uid = 1
        logger.info("[DEV_MODE] Skipping Odoo authentication")

    rate_limiter = OdooRateLimiter()

    logger.info(
        "Odoo MCP server started (DEV_MODE=%s, vault=%s, url=%s)",
        DEV_MODE,
        VAULT_PATH,
        ODOO_URL,
    )

    try:
        yield AppContext(client=client, rate_limiter=rate_limiter)
    finally:
        logger.info("Odoo MCP server shutting down")


# ── Server ───────────────────────────────────────────────────────────

mcp = FastMCP(
    "odoo-mcp-server",
    instructions=(
        "Odoo accounting tools. Read tools (list_invoices, get_invoice, "
        "list_customers, get_account_balance, list_transactions) are always available. "
        "Write tools (create_invoice, create_payment) require an approval file in "
        "vault/Approved/. create_customer executes immediately (no HITL). "
        "All write tools are rate-limited to 20 operations per hour."
    ),
    lifespan=app_lifespan,
)


# ── Tool: list_invoices ───────────────────────────────────────────────


@mcp.tool()
async def list_invoices(
    limit: int = 20,
    offset: int = 0,
    status: str = "posted",
) -> str:
    """List customer invoices from Odoo.

    Args:
        limit: Maximum invoices to return (1-100, default 20).
        offset: Pagination offset (default 0).
        status: Filter by status — 'draft', 'posted', 'paid', or 'all' (default 'posted').
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    limit = max(1, min(100, limit))
    if status not in ("draft", "posted", "paid", "all"):
        return f"Error: status must be 'draft', 'posted', 'paid', or 'all'. Got: {status}"

    try:
        results = await asyncio.to_thread(app.client.list_invoices, limit, offset, status)
        duration_ms = int((time.time() - start) * 1000)

        _log_tool_action(
            "list_invoices",
            "account.move",
            "success",
            cid,
            duration_ms,
            {"count": len(results), "status": status, "limit": limit},
        )

        if not results:
            return f"No invoices found with status '{status}'."

        lines = [f"Found {len(results)} invoice(s) with status '{status}':\n"]
        for i, inv in enumerate(results, 1):
            lines.append(
                f"{i}. {inv['number']} | {inv['customer_name']} | "
                f"${inv['amount_total']:.2f} {inv['currency']} | "
                f"{inv['invoice_date']} | {inv['payment_status']}"
            )
        return "\n".join(lines)

    except ConnectionError as exc:
        duration_ms = int((time.time() - start) * 1000)
        _log_tool_action("list_invoices", "account.move", "error", cid, duration_ms)
        return f"Error: Odoo server unreachable — {exc}"


# ── Tool: get_invoice ─────────────────────────────────────────────────


@mcp.tool()
async def get_invoice(invoice_id: int) -> str:
    """Get full details for a single Odoo invoice.

    Args:
        invoice_id: Odoo account.move record ID.
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    try:
        inv = await asyncio.to_thread(app.client.get_invoice, invoice_id)
        duration_ms = int((time.time() - start) * 1000)

        _log_tool_action(
            "get_invoice",
            f"account.move:{invoice_id}",
            "success",
            cid,
            duration_ms,
            {"invoice_id": invoice_id},
        )

        lines = [
            f"Invoice: {inv['number']}",
            f"Customer: {inv['customer_name']}",
            f"Date: {inv['invoice_date']} | Due: {inv.get('due_date', 'N/A')}",
            f"Status: {inv['status']} | Payment: {inv['payment_status']}",
            f"Subtotal: ${inv.get('amount_untaxed', 0):.2f} | "
            f"Tax: ${inv.get('amount_tax', 0):.2f} | "
            f"Total: ${inv['amount_total']:.2f} {inv['currency']}",
        ]

        if inv.get("lines"):
            lines.append("\nLine Items:")
            for line in inv["lines"]:
                lines.append(
                    f"  - {line.get('product', 'Service')} × "
                    f"{line.get('qty', 1)} @ ${line.get('price_unit', 0):.2f} "
                    f"= ${line.get('subtotal', 0):.2f}"
                )

        return "\n".join(lines)

    except ValueError as exc:
        return f"Error: {exc}"
    except ConnectionError as exc:
        duration_ms = int((time.time() - start) * 1000)
        _log_tool_action("get_invoice", f"account.move:{invoice_id}", "error", cid, duration_ms)
        return f"Error: Odoo server unreachable — {exc}"


# ── Tool: list_customers ──────────────────────────────────────────────


@mcp.tool()
async def list_customers(search: str = "", limit: int = 20) -> str:
    """List customer records from Odoo.

    Args:
        search: Optional name or email search string (case-insensitive).
        limit: Maximum customers to return (1-50, default 20).
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    limit = max(1, min(50, limit))

    try:
        results = await asyncio.to_thread(app.client.list_customers, search, limit)
        duration_ms = int((time.time() - start) * 1000)

        _log_tool_action(
            "list_customers",
            "res.partner",
            "success",
            cid,
            duration_ms,
            {"count": len(results), "search": search[:50] if search else ""},
        )

        if not results:
            return f"No customers found{' matching: ' + search if search else ''}."

        lines = [f"Found {len(results)} customer(s):\n"]
        for i, c in enumerate(results, 1):
            email_str = f" | {c['email']}" if c.get("email") else ""
            phone_str = f" | {c['phone']}" if c.get("phone") else ""
            lines.append(f"{i}. [{c['id']}] {c['name']}{email_str}{phone_str}")
        return "\n".join(lines)

    except ConnectionError as exc:
        duration_ms = int((time.time() - start) * 1000)
        _log_tool_action("list_customers", "res.partner", "error", cid, duration_ms)
        return f"Error: Odoo server unreachable — {exc}"


# ── Tool: get_account_balance ─────────────────────────────────────────


@mcp.tool()
async def get_account_balance(account_id: int) -> str:
    """Get the current balance for an Odoo account.

    Args:
        account_id: Odoo account.account record ID.
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    try:
        data = await asyncio.to_thread(app.client.get_account_balance, account_id)
        duration_ms = int((time.time() - start) * 1000)

        _log_tool_action(
            "get_account_balance",
            f"account.account:{account_id}",
            "success",
            cid,
            duration_ms,
            {"account_id": account_id},
        )

        return (
            f"Account: {data['code']} — {data['name']}\n"
            f"Balance: ${data['balance']:.2f} {data['currency']}\n"
            f"(Debit: ${data['debit']:.2f} | Credit: ${data['credit']:.2f})\n"
            f"As of: {now_iso()}"
        )

    except ValueError as exc:
        return f"Error: {exc}"
    except ConnectionError as exc:
        duration_ms = int((time.time() - start) * 1000)
        _log_tool_action(
            "get_account_balance",
            f"account.account:{account_id}",
            "error",
            cid,
            duration_ms,
        )
        return f"Error: Odoo server unreachable — {exc}"


# ── Tool: list_transactions ───────────────────────────────────────────


@mcp.tool()
async def list_transactions(
    date_from: str = "",
    date_to: str = "",
    account_id: int = 0,
    limit: int = 50,
) -> str:
    """List journal entry lines (transactions) from Odoo.

    Args:
        date_from: Start date YYYY-MM-DD (default: 30 days ago).
        date_to: End date YYYY-MM-DD (default: today).
        account_id: Filter by Odoo account ID (0 = all accounts).
        limit: Maximum lines to return (1-200, default 50).
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    limit = max(1, min(200, limit))

    # Default date_from to 30 days ago if not provided
    if not date_from:
        date_from = (datetime.now(tz=UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

    # Validate date formats
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if date_from and not date_pattern.match(date_from):
        return "Error: date_from must be YYYY-MM-DD format."
    if date_to and not date_pattern.match(date_to):
        return "Error: date_to must be YYYY-MM-DD format."

    try:
        results = await asyncio.to_thread(
            app.client.list_transactions, date_from, date_to, account_id, limit
        )
        duration_ms = int((time.time() - start) * 1000)

        _log_tool_action(
            "list_transactions",
            "account.move.line",
            "success",
            cid,
            duration_ms,
            {"count": len(results), "date_from": date_from, "date_to": date_to},
        )

        if not results:
            return "No transactions found for the specified criteria."

        lines = [f"Found {len(results)} transaction(s):\n"]
        for t in results:
            dr_cr = f"DR ${t['debit']:.2f}" if t["debit"] else f"CR ${t['credit']:.2f}"
            lines.append(
                f"{t['date']} | {t['journal_entry']} | "
                f"{t['account_name']} | {t['description'][:40]} | {dr_cr}"
            )
        return "\n".join(lines)

    except ConnectionError as exc:
        duration_ms = int((time.time() - start) * 1000)
        _log_tool_action("list_transactions", "account.move.line", "error", cid, duration_ms)
        return f"Error: Odoo server unreachable — {exc}"


# ── Tool: create_invoice (HITL) ───────────────────────────────────────


@mcp.tool()
async def create_invoice(
    customer_id: int,
    invoice_date: str,
    lines: list[dict[str, Any]],
) -> str:
    """Create a customer invoice in Odoo.

    Requires an approval file in vault/Approved/ with type: odoo_invoice.
    Rate limited to 20 write operations per hour (shared with other write tools).

    Args:
        customer_id: Odoo res.partner record ID for the customer.
        invoice_date: Invoice date in YYYY-MM-DD format.
        lines: List of line items, each with 'product' (str), 'quantity' (float),
               and 'price_unit' (float).
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    # Approval check
    approval = find_approval(VAULT_PATH, "odoo_invoice")
    if approval is None:
        _log_tool_action(
            "create_invoice", "account.move", "rejected", cid,
            parameters={"reason": "no_approval"},
        )
        return (
            "Rejected: No approval file found in vault/Approved/ with type: odoo_invoice. "
            "Create an ODOO_INVOICE_*.md file in vault/Pending_Approval/ with the invoice "
            "details, then move it to vault/Approved/ with status: approved."
        )

    # Rate limit check
    allowed, wait_seconds = app.rate_limiter.check()
    if not allowed:
        _log_tool_action(
            "create_invoice", "account.move", "rate_limited", cid,
            parameters={"wait_seconds": wait_seconds},
        )
        return (
            f"Rejected: Rate limit exceeded ({app.rate_limiter.max_sends} write ops/hour). "
            f"Next slot available in {wait_seconds} seconds."
        )

    try:
        invoice_id, invoice_ref = await asyncio.to_thread(
            app.client.create_invoice, customer_id, invoice_date, lines
        )
        duration_ms = int((time.time() - start) * 1000)

        app.rate_limiter.record_send()

        # Update approval file and move to Done
        try:
            update_frontmatter(
                approval["path"],
                {
                    "status": "done",
                    "odoo_invoice_id": invoice_id,
                    "odoo_invoice_ref": invoice_ref,
                    "dev_mode": DEV_MODE,
                    "completed_at": now_iso(),
                },
            )
        except OSError:
            logger.warning("Could not update frontmatter on approval file")

        consume_approval(approval["path"], VAULT_PATH)

        _log_tool_action(
            "create_invoice",
            "account.move",
            "success",
            cid,
            duration_ms,
            {"invoice_id": invoice_id, "invoice_ref": invoice_ref, "dev_mode": DEV_MODE},
        )

        dev_note = " (DEV_MODE — no real invoice created)" if DEV_MODE else ""
        return (
            f"Invoice created successfully{dev_note}. "
            f"Odoo ID: {invoice_id}. Invoice Ref: {invoice_ref}. "
            f"Approval file moved to vault/Done/."
        )

    except xmlrpc.client.Fault as exc:
        duration_ms = int((time.time() - start) * 1000)
        _reject_approval_file(approval["path"], exc.faultString)
        _log_tool_action("create_invoice", "account.move", "error", cid, duration_ms)
        return f"Error creating invoice: {exc.faultString}. Approval file moved to vault/Rejected/."


# ── Tool: create_payment (HITL) ───────────────────────────────────────


@mcp.tool()
async def create_payment(
    invoice_id: int,
    amount: float,
    payment_date: str,
    journal_id: int,
    memo: str = "",
) -> str:
    """Register a payment against an Odoo invoice.

    Requires an approval file in vault/Approved/ with type: odoo_payment.
    Rate limited to 20 write operations per hour (shared with other write tools).

    Args:
        invoice_id: Odoo account.move record ID to settle.
        amount: Payment amount (must be > 0).
        payment_date: Payment date in YYYY-MM-DD format.
        journal_id: Odoo account.journal record ID (bank or cash journal).
        memo: Optional payment reference/memo.
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    if amount <= 0:
        return "Error: Payment amount must be greater than 0."

    # Approval check
    approval = find_approval(VAULT_PATH, "odoo_payment")
    if approval is None:
        _log_tool_action(
            "create_payment", "account.payment", "rejected", cid,
            parameters={"reason": "no_approval"},
        )
        return (
            "Rejected: No approval file found in vault/Approved/ with type: odoo_payment. "
            "Create an ODOO_PAYMENT_*.md file in vault/Pending_Approval/ with the payment "
            "details, then move it to vault/Approved/ with status: approved."
        )

    # Rate limit check
    allowed, wait_seconds = app.rate_limiter.check()
    if not allowed:
        _log_tool_action(
            "create_payment", "account.payment", "rate_limited", cid,
            parameters={"wait_seconds": wait_seconds},
        )
        return (
            f"Rejected: Rate limit exceeded ({app.rate_limiter.max_sends} write ops/hour). "
            f"Next slot available in {wait_seconds} seconds."
        )

    try:
        payment_id = await asyncio.to_thread(
            app.client.create_payment, invoice_id, amount, payment_date, journal_id, memo
        )
        duration_ms = int((time.time() - start) * 1000)

        app.rate_limiter.record_send()

        try:
            update_frontmatter(
                approval["path"],
                {
                    "status": "done",
                    "odoo_payment_id": payment_id,
                    "dev_mode": DEV_MODE,
                    "completed_at": now_iso(),
                },
            )
        except OSError:
            logger.warning("Could not update frontmatter on payment approval file")

        consume_approval(approval["path"], VAULT_PATH)

        _log_tool_action(
            "create_payment",
            "account.payment",
            "success",
            cid,
            duration_ms,
            {"payment_id": payment_id, "invoice_id": invoice_id, "dev_mode": DEV_MODE},
        )

        dev_note = " (DEV_MODE — no real payment created)" if DEV_MODE else ""
        return (
            f"Payment registered successfully{dev_note}. "
            f"Odoo Payment ID: {payment_id}. "
            f"Approval file moved to vault/Done/."
        )

    except ValueError as exc:
        duration_ms = int((time.time() - start) * 1000)
        reason = str(exc)
        _reject_approval_file(approval["path"], reason)
        _log_tool_action(
            "create_payment", "account.payment", "rejected", cid, duration_ms,
            {"reason": reason},
        )
        if reason == "already_paid":
            return (
                f"Rejected: Invoice ID {invoice_id} is already fully paid. "
                f"No duplicate payment created. Approval file moved to vault/Rejected/."
            )
        return f"Error: {reason}. Approval file moved to vault/Rejected/."

    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.time() - start) * 1000)
        _reject_approval_file(approval["path"], str(exc))
        _log_tool_action("create_payment", "account.payment", "error", cid, duration_ms)
        return f"Error registering payment: {exc}. Approval file moved to vault/Rejected/."


# ── Tool: create_customer ─────────────────────────────────────────────


@mcp.tool()
async def create_customer(
    name: str,
    email: str = "",
    phone: str = "",
    is_company: bool = True,
) -> str:
    """Create a new customer record in Odoo (no approval required).

    Checks for existing customers with the same name before creating
    to prevent duplicates. Rate limited to 20 write operations per hour.

    Args:
        name: Customer display name (required).
        email: Email address (optional).
        phone: Phone number (optional).
        is_company: True for business entities, False for individual contacts.
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    if not name.strip():
        return "Error: Customer name is required."

    # Rate limit check
    allowed, wait_seconds = app.rate_limiter.check()
    if not allowed:
        _log_tool_action(
            "create_customer", "res.partner", "rate_limited", cid,
            parameters={"wait_seconds": wait_seconds},
        )
        return (
            f"Rejected: Rate limit exceeded ({app.rate_limiter.max_sends} write ops/hour). "
            f"Next slot available in {wait_seconds} seconds."
        )

    try:
        customer_id, created = await asyncio.to_thread(
            app.client.create_customer, name, email, phone, is_company
        )
        duration_ms = int((time.time() - start) * 1000)

        if created:
            app.rate_limiter.record_send()
            _log_tool_action(
                "create_customer",
                "res.partner",
                "success",
                cid,
                duration_ms,
                {"customer_id": customer_id, "dev_mode": DEV_MODE},
            )
            dev_note = " (DEV_MODE — no real customer created)" if DEV_MODE else ""
            return (
                f"Customer created successfully{dev_note}. "
                f"Odoo ID: {customer_id}. Name: {name}"
            )
        else:
            # Duplicate — no rate limit hit since no write occurred
            _log_tool_action(
                "create_customer",
                "res.partner",
                "duplicate",
                cid,
                duration_ms,
                {"customer_id": customer_id},
            )
            return f"Customer already exists. Odoo ID: {customer_id}. Name: {name}"

    except Exception as exc:  # noqa: BLE001
        duration_ms = int((time.time() - start) * 1000)
        _log_tool_action("create_customer", "res.partner", "error", cid, duration_ms)
        return f"Error creating customer: {exc}"


# ── Tool: get_financial_summary ───────────────────────────────────────


@mcp.tool()
async def odoo_financial_summary() -> str:
    """Get a financial summary from Odoo for the CEO daily briefing.

    Returns aggregated data: monthly revenue, outstanding invoices,
    recent payments (7 days), and main account balance.
    Falls back to cached data if Odoo is temporarily unreachable.
    """
    ctx = mcp.get_context()
    app: AppContext = ctx.request_context.lifespan_context
    cid = correlation_id()
    start = time.time()

    summary = await asyncio.to_thread(get_financial_summary, app.client, VAULT_PATH)
    duration_ms = int((time.time() - start) * 1000)

    _log_tool_action(
        "odoo_financial_summary",
        "odoo_summary",
        "error" if "error" in summary else "success",
        cid,
        duration_ms,
    )

    if "error" in summary:
        cached = summary.get("last_known") or {}
        stale_note = f"\n⚠️ Odoo data unavailable. Last known values (cached at {summary.get('cached_at', 'unknown')}):"
        if not cached:
            return f"## Financial Summary (Odoo)\n\n{stale_note}\n_No cached data available._"
        return (
            f"## Financial Summary (Odoo — Stale Data)\n"
            f"{stale_note}\n"
            + _format_summary(cached)
        )

    dev_note = " ⚠️ DEV_MODE — Mock Data" if DEV_MODE else ""
    return f"## Financial Summary (Odoo){dev_note}\n\n" + _format_summary(summary)


def _format_summary(summary: dict[str, Any]) -> str:
    """Format financial summary dict as markdown."""
    oi = summary.get("outstanding_invoices", {})
    rp = summary.get("recent_payments", {})
    currency = summary.get("currency", "USD")
    as_of = summary.get("as_of", "")

    return (
        f"*As of {as_of}*\n\n"
        f"- **Monthly Revenue**: ${summary.get('monthly_revenue', 0):.2f} {currency}\n"
        f"- **Outstanding Invoices**: {oi.get('count', 0)} invoices · "
        f"${oi.get('total_value', 0):.2f} {currency} total\n"
        f"- **Recent Payments** (last 7 days): {rp.get('count', 0)} payments · "
        f"${rp.get('total_value', 0):.2f} {currency}\n"
        f"- **Account Balance**: ${summary.get('account_balance', 0):.2f} {currency}\n"
    )


# ── Entry Point ──────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point for the Odoo MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
