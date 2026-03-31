"""Odoo XML-RPC client for the Personal AI Employee.

Wraps Python's standard-library ``xmlrpc.client`` to communicate with a
self-hosted Odoo Community Edition instance.  All methods are *synchronous*;
callers must wrap them with ``asyncio.to_thread()`` inside async MCP tools.

DEV_MODE:
    When ``dev_mode=True`` the client skips all network calls and returns
    hard-coded mock data.  Authentication is simulated (uid = 1).
"""

from __future__ import annotations

import logging
import xmlrpc.client
from typing import Any

logger = logging.getLogger(__name__)

# ── Mock data used when DEV_MODE=True ───────────────────────────────

_MOCK_INVOICES: list[dict[str, Any]] = [
    {
        "id": 1,
        "number": "INV/2026/001",
        "customer_name": "ACME Corp",
        "customer_id": 5,
        "amount_total": 1500.0,
        "currency": "USD",
        "invoice_date": "2026-02-01",
        "due_date": "2026-03-01",
        "status": "posted",
        "payment_status": "not_paid",
    },
    {
        "id": 2,
        "number": "INV/2026/002",
        "customer_name": "Beta Ltd",
        "customer_id": 7,
        "amount_total": 3200.0,
        "currency": "USD",
        "invoice_date": "2026-02-10",
        "due_date": "2026-03-10",
        "status": "posted",
        "payment_status": "paid",
    },
    {
        "id": 3,
        "number": "INV/2026/003",
        "customer_name": "Gamma Inc",
        "customer_id": 9,
        "amount_total": 750.0,
        "currency": "USD",
        "invoice_date": "2026-02-15",
        "due_date": "2026-03-15",
        "status": "posted",
        "payment_status": "in_payment",
    },
]

_MOCK_CUSTOMERS: list[dict[str, Any]] = [
    {
        "id": 5,
        "name": "ACME Corp",
        "email": "billing@acme.com",
        "phone": "+1-555-0100",
        "customer_rank": 3,
    },
    {
        "id": 7,
        "name": "Beta Ltd",
        "email": "accounts@beta.com",
        "phone": "+1-555-0200",
        "customer_rank": 1,
    },
]

_MOCK_BALANCE: dict[str, Any] = {
    "account_id": 10,
    "code": "1010",
    "name": "Bank",
    "debit": 45000.0,
    "credit": 16400.0,
    "balance": 28600.0,
    "currency": "USD",
}

_MOCK_TRANSACTIONS: list[dict[str, Any]] = [
    {
        "id": 101,
        "date": "2026-02-20",
        "journal_entry": "INV/2026/003",
        "account_code": "1200",
        "account_name": "Accounts Receivable",
        "description": "Invoice for Gamma Inc",
        "debit": 750.0,
        "credit": 0.0,
        "partner_name": "Gamma Inc",
    },
    {
        "id": 102,
        "date": "2026-02-18",
        "journal_entry": "BILL/2026/001",
        "account_code": "4000",
        "account_name": "Sales Revenue",
        "description": "Sales — consulting",
        "debit": 0.0,
        "credit": 750.0,
        "partner_name": None,
    },
    {
        "id": 103,
        "date": "2026-02-15",
        "journal_entry": "BNK/2026/005",
        "account_code": "1010",
        "account_name": "Bank",
        "description": "Payment received — Beta Ltd",
        "debit": 3200.0,
        "credit": 0.0,
        "partner_name": "Beta Ltd",
    },
    {
        "id": 104,
        "date": "2026-02-10",
        "journal_entry": "INV/2026/002",
        "account_code": "1200",
        "account_name": "Accounts Receivable",
        "description": "Invoice for Beta Ltd",
        "debit": 3200.0,
        "credit": 0.0,
        "partner_name": "Beta Ltd",
    },
    {
        "id": 105,
        "date": "2026-02-01",
        "journal_entry": "INV/2026/001",
        "account_code": "1200",
        "account_name": "Accounts Receivable",
        "description": "Invoice for ACME Corp",
        "debit": 1500.0,
        "credit": 0.0,
        "partner_name": "ACME Corp",
    },
]


# ── OdooClient ───────────────────────────────────────────────────────


class OdooClient:
    """Synchronous wrapper around the Odoo XML-RPC external API.

    Args:
        url: Odoo base URL (e.g. ``http://localhost:8069``).
        db: Database name (e.g. ``ai_employee``).
        username: Odoo login username.
        api_key: Odoo API key (generated in Settings → Technical → API Keys).
        dev_mode: When ``True``, skip all network calls and return mock data.
    """

    def __init__(
        self,
        url: str,
        db: str,
        username: str,
        api_key: str,
        dev_mode: bool = False,
    ) -> None:
        self._url = url.rstrip("/")
        self._db = db
        self._username = username
        self._api_key = api_key
        self._dev_mode = dev_mode
        self._uid: int | None = None

        if not dev_mode:
            self._common = xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/common", allow_none=True)
            self._models = xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/object", allow_none=True)
        else:
            self._common = None  # type: ignore[assignment]
            self._models = None  # type: ignore[assignment]

    # ── Authentication ───────────────────────────────────────────────

    def authenticate(self) -> int:
        """Authenticate with Odoo and cache the user ID (uid).

        Returns:
            Authenticated user ID (uid).

        Raises:
            ConnectionError: If authentication fails or Odoo is unreachable.
        """
        if self._dev_mode:
            self._uid = 1
            logger.info("[DEV_MODE] Skipping Odoo authentication (uid=1)")
            return 1

        try:
            result = self._common.authenticate(
                self._db, self._username, self._api_key, {}
            )
        except xmlrpc.client.ProtocolError as exc:
            raise ConnectionError(f"Odoo unreachable: {exc.errmsg}") from exc
        except OSError as exc:
            raise ConnectionError(f"Odoo unreachable: {exc}") from exc

        if not result:
            raise ConnectionError(
                "Odoo authentication failed — check ODOO_USERNAME and ODOO_API_KEY"
            )

        self._uid = int(result)
        logger.info("Authenticated with Odoo (uid=%d)", self._uid)
        return self._uid

    # ── Internal helper ──────────────────────────────────────────────

    def _execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Call ``execute_kw`` on the Odoo models endpoint.

        Raises:
            ConnectionError: If Odoo is unreachable.
            xmlrpc.client.Fault: Propagated directly so callers can inspect
                ``faultString`` for domain-specific error messages.
        """
        if self._uid is None:
            raise ConnectionError("Not authenticated — call authenticate() first")

        try:
            return self._models.execute_kw(
                self._db,
                self._uid,
                self._api_key,
                model,
                method,
                args,
                kwargs or {},
            )
        except xmlrpc.client.ProtocolError as exc:
            raise ConnectionError(f"Odoo unreachable: {exc.errmsg}") from exc
        except OSError as exc:
            raise ConnectionError(f"Odoo unreachable: {exc}") from exc
        # xmlrpc.client.Fault is NOT caught here — propagated to callers

    # ── Read: Invoices ───────────────────────────────────────────────

    def list_invoices(
        self,
        limit: int = 20,
        offset: int = 0,
        status: str = "posted",
    ) -> list[dict[str, Any]]:
        """List customer invoices (account.move, move_type=out_invoice).

        Args:
            limit: Maximum records to return (1–100).
            offset: Pagination offset.
            status: Filter by ``state`` (``"draft"``, ``"posted"``, ``"all"``)
                or ``payment_state`` (``"paid"``).

        Returns:
            List of normalised invoice dicts.
        """
        if self._dev_mode:
            if status == "paid":
                return [i for i in _MOCK_INVOICES if i["payment_status"] == "paid"]
            if status in ("draft", "all"):
                return _MOCK_INVOICES[:]
            return [i for i in _MOCK_INVOICES if i["status"] == "posted"]

        domain: list[Any] = [["move_type", "=", "out_invoice"]]
        if status == "paid":
            domain.append(["payment_state", "=", "paid"])
        elif status != "all":
            domain.append(["state", "=", status])

        records = self._execute_kw(
            "account.move",
            "search_read",
            [domain],
            {
                "fields": [
                    "id",
                    "name",
                    "partner_id",
                    "amount_total",
                    "currency_id",
                    "invoice_date",
                    "invoice_date_due",
                    "state",
                    "payment_state",
                ],
                "limit": min(limit, 100),
                "offset": offset,
                "order": "invoice_date desc",
            },
        )

        return [
            {
                "id": r["id"],
                "number": r["name"],
                "customer_name": r["partner_id"][1] if r.get("partner_id") else "Unknown",
                "customer_id": r["partner_id"][0] if r.get("partner_id") else 0,
                "amount_total": r["amount_total"],
                "currency": r["currency_id"][1] if r.get("currency_id") else "USD",
                "invoice_date": r.get("invoice_date") or "",
                "due_date": r.get("invoice_date_due") or "",
                "status": r["state"],
                "payment_status": r["payment_state"],
            }
            for r in records
        ]

    def get_invoice(self, invoice_id: int) -> dict[str, Any]:
        """Fetch full details for a single invoice.

        Args:
            invoice_id: Odoo ``account.move`` record ID.

        Returns:
            Invoice dict with line items.

        Raises:
            ValueError: If the invoice is not found.
        """
        if self._dev_mode:
            match = next((i for i in _MOCK_INVOICES if i["id"] == invoice_id), None)
            if match:
                return {**match, "lines": [{"product": "Consulting Services", "qty": 10, "price_unit": 150.0, "subtotal": 1500.0}]}
            raise ValueError(f"Invoice ID {invoice_id} not found")

        records = self._execute_kw(
            "account.move",
            "read",
            [[invoice_id]],
            {
                "fields": [
                    "id",
                    "name",
                    "partner_id",
                    "amount_total",
                    "amount_untaxed",
                    "amount_tax",
                    "currency_id",
                    "invoice_date",
                    "invoice_date_due",
                    "state",
                    "payment_state",
                    "invoice_line_ids",
                ]
            },
        )

        if not records:
            raise ValueError(f"Invoice ID {invoice_id} not found")

        r = records[0]
        return {
            "id": r["id"],
            "number": r["name"],
            "customer_name": r["partner_id"][1] if r.get("partner_id") else "Unknown",
            "customer_id": r["partner_id"][0] if r.get("partner_id") else 0,
            "amount_untaxed": r["amount_untaxed"],
            "amount_tax": r["amount_tax"],
            "amount_total": r["amount_total"],
            "currency": r["currency_id"][1] if r.get("currency_id") else "USD",
            "invoice_date": r.get("invoice_date") or "",
            "due_date": r.get("invoice_date_due") or "",
            "status": r["state"],
            "payment_status": r["payment_state"],
            "line_ids": r.get("invoice_line_ids", []),
        }

    # ── Read: Customers ──────────────────────────────────────────────

    def list_customers(
        self,
        search: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List customer records from res.partner.

        Args:
            search: Optional name/email filter (case-insensitive).
            limit: Maximum records (1–50).

        Returns:
            List of customer dicts.
        """
        if self._dev_mode:
            if search:
                s = search.lower()
                return [
                    c for c in _MOCK_CUSTOMERS
                    if s in c["name"].lower() or (c.get("email") and s in c["email"].lower())
                ]
            return _MOCK_CUSTOMERS[:]

        domain: list[Any] = [["customer_rank", ">", 0]]
        if search:
            domain = ["|", ["name", "ilike", search], ["email", "ilike", search]]

        records = self._execute_kw(
            "res.partner",
            "search_read",
            [domain],
            {
                "fields": ["id", "name", "email", "phone", "customer_rank"],
                "limit": min(limit, 50),
                "order": "name asc",
            },
        )

        return [
            {
                "id": r["id"],
                "name": r["name"],
                "email": r.get("email") or "",
                "phone": r.get("phone") or "",
                "customer_rank": r.get("customer_rank", 0),
            }
            for r in records
        ]

    # ── Read: Account Balance ────────────────────────────────────────

    def get_account_balance(self, account_id: int) -> dict[str, Any]:
        """Fetch balance for an account.account record.

        Computes balance by summing debit/credit on posted journal lines.

        Args:
            account_id: Odoo ``account.account`` record ID.

        Returns:
            Balance dict with code, name, debit, credit, balance, currency.

        Raises:
            ValueError: If the account is not found.
        """
        if self._dev_mode:
            return {**_MOCK_BALANCE, "account_id": account_id}

        accounts = self._execute_kw(
            "account.account",
            "read",
            [[account_id]],
            {"fields": ["id", "code", "name", "account_type"]},
        )

        if not accounts:
            raise ValueError(f"Account ID {account_id} not found")

        account = accounts[0]

        # Sum debit/credit from posted journal lines
        groups = self._execute_kw(
            "account.move.line",
            "read_group",
            [[["account_id", "=", account_id], ["parent_state", "=", "posted"]]],
            {"fields": ["debit:sum", "credit:sum"], "groupby": []},
        )

        debit = groups[0].get("debit", 0.0) if groups else 0.0
        credit = groups[0].get("credit", 0.0) if groups else 0.0

        return {
            "account_id": account["id"],
            "code": account["code"],
            "name": account["name"],
            "debit": debit,
            "credit": credit,
            "balance": debit - credit,
            "currency": "USD",
        }

    # ── Read: Transactions ───────────────────────────────────────────

    def list_transactions(
        self,
        date_from: str = "",
        date_to: str = "",
        account_id: int = 0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List journal entry lines (transactions).

        Args:
            date_from: Start date ``YYYY-MM-DD`` (inclusive).
            date_to: End date ``YYYY-MM-DD`` (inclusive).
            account_id: Filter by account ID (0 = all accounts).
            limit: Maximum records (1–200).

        Returns:
            List of transaction dicts.
        """
        if self._dev_mode:
            return _MOCK_TRANSACTIONS[:]

        domain: list[Any] = [["parent_state", "=", "posted"]]
        if date_from:
            domain.append(["date", ">=", date_from])
        if date_to:
            domain.append(["date", "<=", date_to])
        if account_id > 0:
            domain.append(["account_id", "=", account_id])

        records = self._execute_kw(
            "account.move.line",
            "search_read",
            [domain],
            {
                "fields": [
                    "id",
                    "date",
                    "name",
                    "account_id",
                    "move_id",
                    "debit",
                    "credit",
                    "partner_id",
                ],
                "limit": min(limit, 200),
                "order": "date desc",
            },
        )

        return [
            {
                "id": r["id"],
                "date": r.get("date") or "",
                "journal_entry": r["move_id"][1] if r.get("move_id") else "",
                "account_code": r["account_id"][0] if r.get("account_id") else 0,
                "account_name": r["account_id"][1] if r.get("account_id") else "",
                "description": r.get("name") or "",
                "debit": r.get("debit", 0.0),
                "credit": r.get("credit", 0.0),
                "partner_name": r["partner_id"][1] if r.get("partner_id") else None,
            }
            for r in records
        ]

    # ── Write: Create Invoice (HITL) ─────────────────────────────────

    def create_invoice(
        self,
        customer_id: int,
        invoice_date: str,
        lines: list[dict[str, Any]],
    ) -> tuple[int, str]:
        """Create and post a customer invoice in Odoo.

        Args:
            customer_id: Odoo ``res.partner`` ID for the customer.
            invoice_date: Invoice date in ``YYYY-MM-DD`` format.
            lines: List of line item dicts with keys:
                ``product`` (str), ``quantity`` (float), ``price_unit`` (float).
                Optional: ``product_id`` (int), ``tax_ids`` (list).

        Returns:
            Tuple of ``(invoice_id, invoice_ref)``.
        """
        if self._dev_mode:
            logger.info("[DEV_MODE] Simulating invoice creation")
            return (9001, "DEV/2026/001")

        invoice_line_ids = [
            (
                0,
                0,
                {
                    "name": line.get("product", "Service"),
                    "quantity": float(line.get("quantity", 1)),
                    "price_unit": float(line.get("price_unit", 0.0)),
                },
            )
            for line in lines
        ]

        invoice_id = self._execute_kw(
            "account.move",
            "create",
            [
                {
                    "move_type": "out_invoice",
                    "partner_id": customer_id,
                    "invoice_date": invoice_date,
                    "invoice_line_ids": invoice_line_ids,
                }
            ],
        )

        # Post (confirm) the invoice — action_post may return None which
        # causes Odoo's XML-RPC serializer to fail. Catch and verify state.
        try:
            self._execute_kw("account.move", "action_post", [[invoice_id]], {})
        except xmlrpc.client.Fault as exc:
            if "cannot marshal None" in exc.faultString:
                state = self._execute_kw(
                    "account.move", "read", [[invoice_id]],
                    {"fields": ["state"]},
                )
                if state and state[0].get("state") == "posted":
                    logger.info("Invoice %d posted (ignoring Odoo None serialization error)", invoice_id)
                else:
                    raise
            else:
                raise

        # Read back the invoice reference number
        ref_records = self._execute_kw(
            "account.move",
            "read",
            [[invoice_id]],
            {"fields": ["name"]},
        )
        invoice_ref = ref_records[0]["name"] if ref_records else f"INV/{invoice_id}"

        return (invoice_id, invoice_ref)

    # ── Write: Create Payment (HITL) ─────────────────────────────────

    def create_payment(
        self,
        invoice_id: int,
        amount: float,
        payment_date: str,
        journal_id: int,
        memo: str = "",
    ) -> int:
        """Register a payment against a customer invoice using Odoo's payment wizard.

        Uses ``account.payment.register`` wizard to properly create, post,
        and **reconcile** the payment with the invoice.  This ensures the
        invoice's ``payment_state`` is updated (e.g. ``paid`` / ``in_payment``)
        and the Odoo dashboard reflects the payment.

        Args:
            invoice_id: Odoo ``account.move`` ID to settle.
            amount: Payment amount (must be > 0).
            payment_date: Payment date in ``YYYY-MM-DD`` format.
            journal_id: Odoo ``account.journal`` ID (bank/cash).
            memo: Optional reference/memo text.

        Returns:
            Odoo ``account.payment`` record ID.

        Raises:
            ValueError: If invoice not found or already paid.
        """
        if self._dev_mode:
            logger.info("[DEV_MODE] Simulating payment creation")
            return 8001

        # Pre-condition: fetch invoice to check payment state
        invoices = self._execute_kw(
            "account.move",
            "read",
            [[invoice_id]],
            {"fields": ["payment_state", "partner_id", "name", "amount_residual"]},
        )

        if not invoices:
            raise ValueError(f"Invoice ID {invoice_id} not found")

        invoice = invoices[0]
        if invoice["payment_state"] == "paid":
            raise ValueError("already_paid")

        # Record the highest existing payment ID so we can find the new one
        existing_max = self._execute_kw(
            "account.payment", "search",
            [[]],
            {"limit": 1, "order": "id desc"},
        )
        max_id_before = existing_max[0] if existing_max else 0

        # ── Use payment register wizard (creates + reconciles) ──────────
        ctx = {
            "active_model": "account.move",
            "active_ids": [invoice_id],
        }

        wizard_vals: dict[str, Any] = {
            "payment_date": payment_date,
            "journal_id": journal_id,
        }
        if amount:
            wizard_vals["amount"] = amount
        if memo:
            wizard_vals["communication"] = memo

        wizard_id = self._execute_kw(
            "account.payment.register",
            "create",
            [wizard_vals],
            {"context": ctx},
        )

        # Execute the wizard — this creates, posts, and reconciles
        try:
            self._execute_kw(
                "account.payment.register",
                "action_create_payments",
                [[wizard_id]],
                {"context": ctx},
            )
        except xmlrpc.client.Fault as exc:
            if "cannot marshal None" in exc.faultString:
                logger.info(
                    "Payment wizard completed (ignoring Odoo None serialization)"
                )
            else:
                raise

        # ── Find the newly-created payment record ───────────────────────
        new_payments = self._execute_kw(
            "account.payment",
            "search_read",
            [[["id", ">", max_id_before]]],
            {"fields": ["id", "state", "amount", "ref"], "limit": 1, "order": "id desc"},
        )
        payment_id = new_payments[0]["id"] if new_payments else 0

        # Verify the invoice's payment_state changed
        updated = self._execute_kw(
            "account.move", "read", [[invoice_id]],
            {"fields": ["payment_state", "amount_residual"]},
        )
        if updated:
            ps = updated[0].get("payment_state", "unknown")
            residual = updated[0].get("amount_residual", -1)
            logger.info(
                "Invoice %d after payment: payment_state=%s, amount_residual=%.2f",
                invoice_id, ps, residual,
            )

        return payment_id

    # ── Write: Create Customer ────────────────────────────────────────

    def create_customer(
        self,
        name: str,
        email: str = "",
        phone: str = "",
        is_company: bool = True,
    ) -> tuple[int, bool]:
        """Create a new customer record in Odoo, or return existing if duplicate.

        Searches for an existing partner with the same name (case-insensitive)
        before creating to prevent duplicates.

        Args:
            name: Customer display name (required).
            email: Email address (optional).
            phone: Phone number (optional).
            is_company: True for business entities.

        Returns:
            Tuple of ``(partner_id, created)`` where ``created`` is ``True``
            if a new record was created, ``False`` if an existing one was found.
        """
        if self._dev_mode:
            logger.info("[DEV_MODE] Simulating customer creation")
            return (9999, True)

        # Duplicate check
        existing = self._execute_kw(
            "res.partner",
            "search_read",
            [[["name", "=ilike", name]]],
            {"fields": ["id", "name", "email"], "limit": 1},
        )

        if existing:
            logger.info("Duplicate customer found: %s (id=%d)", name, existing[0]["id"])
            return (existing[0]["id"], False)

        new_id = self._execute_kw(
            "res.partner",
            "create",
            [
                {
                    "name": name,
                    "email": email or False,
                    "phone": phone or False,
                    "is_company": is_company,
                    "customer_rank": 1,
                }
            ],
        )

        return (new_id, True)
