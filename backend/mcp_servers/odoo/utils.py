"""Utility helpers for the Odoo MCP server.

Provides:
- ``write_invoice_draft`` — create HITL draft file in vault/Pending_Approval/
- ``write_payment_draft`` — create HITL draft file in vault/Pending_Approval/
- ``get_financial_summary`` — aggregate Odoo data for CEO briefings
- ``cache_financial_summary`` / ``load_cached_summary`` — stale-data fallback
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.utils.timestamps import now_iso

if TYPE_CHECKING:
    from backend.mcp_servers.odoo.odoo_client import OdooClient

logger = logging.getLogger(__name__)

_CACHE_FILENAME = "odoo_briefing_cache.json"


# ── HITL Draft Writers ───────────────────────────────────────────────


def write_invoice_draft(
    vault_path: str,
    customer_name: str,
    customer_id: int,
    invoice_date: str,
    lines: list[dict[str, Any]],
) -> Path:
    """Create an invoice approval draft in vault/Pending_Approval/.

    Args:
        vault_path: Root vault directory path.
        customer_name: Human-readable customer name for the file body.
        customer_id: Odoo partner ID for machine processing.
        invoice_date: Invoice date in ``YYYY-MM-DD`` format.
        lines: List of dicts with ``product``, ``quantity``, ``price_unit``.

    Returns:
        Path to the created draft file.
    """
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    pending_dir = Path(vault_path) / "Pending_Approval"
    pending_dir.mkdir(parents=True, exist_ok=True)

    filename = f"ODOO_INVOICE_{today}.md"
    file_path = pending_dir / filename

    # Build human-readable summary
    total = sum(float(ln.get("quantity", 1)) * float(ln.get("price_unit", 0)) for ln in lines)
    lines_md = "\n".join(
        f"- {ln.get('product', 'Service')} × {ln.get('quantity', 1)} @ ${ln.get('price_unit', 0):.2f}"
        for ln in lines
    )

    # YAML frontmatter
    lines_yaml = "\n".join(
        f"  - product: \"{ln.get('product', 'Service')}\"\n"
        f"    quantity: {ln.get('quantity', 1)}\n"
        f"    price_unit: {ln.get('price_unit', 0.0)}"
        for ln in lines
    )

    content = f"""---
type: odoo_invoice
status: pending_approval
customer_name: "{customer_name}"
customer_id: {customer_id}
invoice_date: "{invoice_date}"
lines:
{lines_yaml}
generated_at: "{now_iso()}"
---
# Invoice Review

**Customer**: {customer_name}
**Date**: {invoice_date}

## Line Items

{lines_md}

**Estimated Total**: ${total:.2f}

---
*To approve: move this file to `vault/Approved/` and update `status: approved`.*
*To reject: move to `vault/Rejected/`.*
"""

    file_path.write_text(content, encoding="utf-8")
    logger.info("Invoice draft created: %s", file_path)
    return file_path


def write_payment_draft(
    vault_path: str,
    invoice_id: int,
    invoice_ref: str,
    amount: float,
    currency: str,
    payment_date: str,
    journal: str,
) -> Path:
    """Create a payment approval draft in vault/Pending_Approval/.

    Args:
        vault_path: Root vault directory path.
        invoice_id: Odoo ``account.move`` ID being settled.
        invoice_ref: Human-readable invoice reference (e.g. ``INV/2026/001``).
        amount: Payment amount.
        currency: Currency code (e.g. ``USD``).
        payment_date: Payment date in ``YYYY-MM-DD`` format.
        journal: Journal name (e.g. ``bank``).

    Returns:
        Path to the created draft file.
    """
    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    pending_dir = Path(vault_path) / "Pending_Approval"
    pending_dir.mkdir(parents=True, exist_ok=True)

    filename = f"ODOO_PAYMENT_{today}.md"
    file_path = pending_dir / filename

    content = f"""---
type: odoo_payment
status: pending_approval
invoice_id: {invoice_id}
invoice_ref: "{invoice_ref}"
amount: {amount}
currency: "{currency}"
payment_date: "{payment_date}"
journal: "{journal}"
generated_at: "{now_iso()}"
---
# Payment Review

**Invoice**: {invoice_ref}
**Amount**: ${amount:.2f} {currency}
**Payment Date**: {payment_date}
**Journal**: {journal}

---
*To approve: move this file to `vault/Approved/` and update `status: approved`.*
*To reject: move to `vault/Rejected/`.*
"""

    file_path.write_text(content, encoding="utf-8")
    logger.info("Payment draft created: %s", file_path)
    return file_path


# ── CEO Briefing Financial Summary ──────────────────────────────────


def get_financial_summary(client: OdooClient, vault_path: str) -> dict[str, Any]:
    """Aggregate financial data from Odoo for the CEO daily briefing.

    Collects:
    - Monthly revenue (sum of paid invoices in current calendar month)
    - Outstanding invoices (count + total of unpaid/in-payment invoices)
    - Recent payments (count + total credits in last 7 days)
    - Main account balance

    On any Odoo error, loads cached data and returns with an error flag.

    Args:
        client: Authenticated OdooClient instance.
        vault_path: Root vault directory for cache file.

    Returns:
        Dict with financial summary fields and ``as_of`` ISO timestamp.
        On failure: includes ``"error"`` key with message and ``"last_known"`` data.
    """
    import os

    main_account_id = int(os.getenv("ODOO_MAIN_ACCOUNT_ID", "1"))
    today = datetime.now(tz=UTC)
    seven_days_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    try:
        # Monthly revenue: paid invoices in current month
        all_invoices = client.list_invoices(limit=100, status="all")
        monthly_revenue = sum(
            inv["amount_total"]
            for inv in all_invoices
            if inv["payment_status"] == "paid"
            and inv.get("invoice_date", "")[:7] == today.strftime("%Y-%m")
        )

        # Outstanding invoices (not_paid or in_payment)
        outstanding = [
            inv for inv in all_invoices
            if inv["payment_status"] in ("not_paid", "in_payment")
        ]
        outstanding_count = len(outstanding)
        outstanding_total = sum(inv["amount_total"] for inv in outstanding)

        # Recent payments (last 7 days): count credit-side lines
        transactions = client.list_transactions(date_from=seven_days_ago, limit=200)
        payment_txns = [t for t in transactions if t["credit"] > 0]
        recent_payment_count = len(payment_txns)
        recent_payment_total = sum(t["credit"] for t in payment_txns)

        # Account balance
        balance_data = client.get_account_balance(main_account_id)
        account_balance = balance_data.get("balance", 0.0)
        currency = balance_data.get("currency", "USD")

        summary: dict[str, Any] = {
            "monthly_revenue": monthly_revenue,
            "outstanding_invoices": {
                "count": outstanding_count,
                "total_value": outstanding_total,
            },
            "recent_payments": {
                "count": recent_payment_count,
                "total_value": recent_payment_total,
            },
            "account_balance": account_balance,
            "currency": currency,
            "as_of": now_iso(),
        }

        cache_financial_summary(vault_path, summary)
        return summary

    except Exception as exc:
        logger.warning("Odoo financial summary failed: %s", exc)
        cached = load_cached_summary(vault_path)
        return {
            "error": f"Odoo unavailable: {exc}",
            "last_known": cached.get("data") if cached else {},
            "cached_at": cached.get("cached_at") if cached else None,
            "as_of": now_iso(),
        }


def cache_financial_summary(vault_path: str, summary: dict[str, Any]) -> None:
    """Write financial summary to cache file for stale-data fallback.

    Args:
        vault_path: Root vault directory path.
        summary: Financial summary dict to cache.
    """
    cache_path = Path(vault_path) / "Logs" / _CACHE_FILENAME
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        cache_path.write_text(
            json.dumps({"data": summary, "cached_at": now_iso()}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        logger.warning("Failed to write Odoo briefing cache to %s", cache_path)


def load_cached_summary(vault_path: str) -> dict[str, Any] | None:
    """Load the last cached financial summary.

    Args:
        vault_path: Root vault directory path.

    Returns:
        Dict with ``"data"`` and ``"cached_at"`` keys, or ``None`` if no cache.
    """
    cache_path = Path(vault_path) / "Logs" / _CACHE_FILENAME

    if not cache_path.exists():
        return None

    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to load Odoo briefing cache from %s", cache_path)
        return None
