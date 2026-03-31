"""Tests for Odoo Accounting MCP Integration (Feature 006).

Covers:
- OdooClient — DEV_MODE mock data and live-path logic
- OdooRateLimiter — config loading and sliding window
- Utils — vault draft writers and financial summary helpers
- MCP tool handlers — read tools and write/HITL tools
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.mcp_servers.odoo.odoo_client import OdooClient
from backend.mcp_servers.odoo.odoo_server import AppContext, OdooRateLimiter
from backend.mcp_servers.odoo.utils import (
    cache_financial_summary,
    get_financial_summary,
    load_cached_summary,
    write_invoice_draft,
    write_payment_draft,
)

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def dev_client() -> OdooClient:
    """OdooClient in DEV_MODE — no network calls."""
    client = OdooClient(
        url="http://localhost:8069",
        db="test_db",
        username="admin",
        api_key="test_key",
        dev_mode=True,
    )
    client._uid = 1
    return client


@pytest.fixture()
def mock_rate_limiter() -> MagicMock:
    """Mock rate limiter that always allows."""
    rl = MagicMock()
    rl.check.return_value = (True, 0)
    rl.max_sends = 20
    return rl


@pytest.fixture()
def mock_app(dev_client: OdooClient, mock_rate_limiter: MagicMock) -> AppContext:
    """AppContext backed by a DEV_MODE OdooClient."""
    return AppContext(client=dev_client, rate_limiter=mock_rate_limiter)


@pytest.fixture()
def mock_context(mock_app: AppContext) -> MagicMock:
    """Simulated MCP request context."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = mock_app
    return ctx


@pytest.fixture()
def vault_tmp(tmp_path: Path) -> Path:
    """Temporary vault directory with standard subdirs."""
    for subdir in ("Approved", "Pending_Approval", "Done", "Rejected", "Logs/actions"):
        (tmp_path / subdir).mkdir(parents=True, exist_ok=True)
    return tmp_path


# ── TestOdooClient ────────────────────────────────────────────────────


class TestOdooClient:
    """Tests for the OdooClient class (DEV_MODE paths)."""

    def test_authenticate_dev_mode_sets_uid_1(self) -> None:
        client = OdooClient(url="http://localhost:8069", db="db", username="u", api_key="k", dev_mode=True)
        uid = client.authenticate()
        assert uid == 1
        assert client._uid == 1

    def test_authenticate_failure_raises_connection_error(self) -> None:
        """Live auth with wrong creds raises ConnectionError."""

        client = OdooClient(url="http://badhost:9999", db="db", username="u", api_key="k", dev_mode=False)
        # _common is a real ServerProxy pointing to an unreachable host
        with pytest.raises(ConnectionError):
            client.authenticate()

    def test_list_invoices_dev_mode_returns_3_records(self, dev_client: OdooClient) -> None:
        results = dev_client.list_invoices()
        assert len(results) == 3
        assert all("number" in r for r in results)
        assert all("amount_total" in r for r in results)

    def test_list_invoices_dev_mode_paid_filter(self, dev_client: OdooClient) -> None:
        results = dev_client.list_invoices(status="paid")
        assert all(r["payment_status"] == "paid" for r in results)

    def test_get_invoice_dev_mode_returns_correct_record(self, dev_client: OdooClient) -> None:
        inv = dev_client.get_invoice(1)
        assert inv["id"] == 1
        assert inv["number"] == "INV/2026/001"
        assert "lines" in inv

    def test_get_invoice_not_found_raises_value_error(self, dev_client: OdooClient) -> None:
        with pytest.raises(ValueError, match="not found"):
            dev_client.get_invoice(9999)

    def test_list_customers_dev_mode_returns_2_records(self, dev_client: OdooClient) -> None:
        results = dev_client.list_customers()
        assert len(results) == 2
        assert results[0]["name"] == "ACME Corp"

    def test_list_customers_dev_mode_search_filters(self, dev_client: OdooClient) -> None:
        results = dev_client.list_customers(search="beta")
        assert len(results) == 1
        assert results[0]["name"] == "Beta Ltd"

    def test_get_account_balance_dev_mode(self, dev_client: OdooClient) -> None:
        bal = dev_client.get_account_balance(10)
        assert bal["balance"] == pytest.approx(28600.0)
        assert "currency" in bal
        assert bal["account_id"] == 10

    def test_list_transactions_dev_mode_returns_5_records(self, dev_client: OdooClient) -> None:
        txns = dev_client.list_transactions()
        assert len(txns) == 5
        assert all("date" in t for t in txns)
        assert all("debit" in t for t in txns)

    def test_create_invoice_dev_mode_returns_mock_id(self, dev_client: OdooClient) -> None:
        lines = [{"product": "Consulting", "quantity": 1, "price_unit": 100.0}]
        invoice_id, invoice_ref = dev_client.create_invoice(5, "2026-02-22", lines)
        assert invoice_id == 9001
        assert invoice_ref == "DEV/2026/001"

    def test_create_payment_dev_mode_returns_mock_id(self, dev_client: OdooClient) -> None:
        payment_id = dev_client.create_payment(1, 1500.0, "2026-02-22", 1)
        assert payment_id == 8001

    def test_create_customer_dev_mode_returns_mock_tuple(self, dev_client: OdooClient) -> None:
        customer_id, created = dev_client.create_customer("NewCorp", "billing@newcorp.com")
        assert customer_id == 9999
        assert created is True

    def test_execute_kw_requires_authentication(self) -> None:
        """_execute_kw raises ConnectionError when _uid is None."""
        client = OdooClient(url="http://localhost:8069", db="db", username="u", api_key="k", dev_mode=False)
        # _uid is None (not authenticated)
        with pytest.raises(ConnectionError, match="Not authenticated"):
            client._execute_kw("account.move", "search", [[]])


# ── TestOdooRateLimiter ───────────────────────────────────────────────


class TestOdooRateLimiter:
    """Tests for OdooRateLimiter config loading and limit enforcement."""

    def test_reads_odoo_writes_per_hour_from_config(self, tmp_path: Path) -> None:
        config = tmp_path / "rate_limits.json"
        config.write_text(json.dumps({"odoo": {"writes_per_hour": 15}}), encoding="utf-8")
        limiter = OdooRateLimiter(config_path=str(config))
        assert limiter.max_sends == 15
        assert limiter.window_seconds == 3600

    def test_default_limit_20_when_config_missing(self, tmp_path: Path) -> None:
        config = tmp_path / "no_such_file.json"
        limiter = OdooRateLimiter(config_path=str(config))
        assert limiter.max_sends == 20

    def test_default_limit_20_when_odoo_key_absent(self, tmp_path: Path) -> None:
        config = tmp_path / "rate_limits.json"
        config.write_text(json.dumps({"email": {"sends_per_hour": 10}}), encoding="utf-8")
        limiter = OdooRateLimiter(config_path=str(config))
        assert limiter.max_sends == 20

    def test_allows_under_limit(self, tmp_path: Path) -> None:
        limiter = OdooRateLimiter(config_path=str(tmp_path / "none.json"))
        allowed, wait = limiter.check()
        assert allowed is True
        assert wait == 0

    def test_rejects_at_limit(self, tmp_path: Path) -> None:
        config = tmp_path / "rate_limits.json"
        config.write_text(json.dumps({"odoo": {"writes_per_hour": 2}}), encoding="utf-8")
        limiter = OdooRateLimiter(config_path=str(config))
        limiter.record_send()
        limiter.record_send()
        allowed, wait = limiter.check()
        assert allowed is False
        assert wait > 0


# ── TestOdooUtils ─────────────────────────────────────────────────────


class TestOdooUtils:
    """Tests for vault helper functions in utils.py."""

    def test_write_invoice_draft_creates_file(self, vault_tmp: Path) -> None:
        path = write_invoice_draft(
            vault_path=str(vault_tmp),
            customer_name="ACME Corp",
            customer_id=5,
            invoice_date="2026-02-22",
            lines=[{"product": "Consulting", "quantity": 2, "price_unit": 500.0}],
        )
        assert path.exists()
        assert "ODOO_INVOICE_" in path.name

    def test_write_invoice_draft_frontmatter_fields(self, vault_tmp: Path) -> None:
        path = write_invoice_draft(
            vault_path=str(vault_tmp),
            customer_name="Beta Ltd",
            customer_id=7,
            invoice_date="2026-02-22",
            lines=[{"product": "Support", "quantity": 1, "price_unit": 300.0}],
        )
        content = path.read_text(encoding="utf-8")
        assert "type: odoo_invoice" in content
        assert "status: pending_approval" in content
        assert 'customer_name: "Beta Ltd"' in content
        assert "customer_id: 7" in content
        assert "generated_at:" in content

    def test_write_payment_draft_creates_file(self, vault_tmp: Path) -> None:
        path = write_payment_draft(
            vault_path=str(vault_tmp),
            invoice_id=42,
            invoice_ref="INV/2026/001",
            amount=1500.0,
            currency="USD",
            payment_date="2026-02-22",
            journal="bank",
        )
        assert path.exists()
        assert "ODOO_PAYMENT_" in path.name

    def test_write_payment_draft_frontmatter_fields(self, vault_tmp: Path) -> None:
        path = write_payment_draft(
            vault_path=str(vault_tmp),
            invoice_id=42,
            invoice_ref="INV/2026/001",
            amount=1500.0,
            currency="USD",
            payment_date="2026-02-22",
            journal="bank",
        )
        content = path.read_text(encoding="utf-8")
        assert "type: odoo_payment" in content
        assert "status: pending_approval" in content
        assert "invoice_id: 42" in content
        assert 'amount: 1500.0' in content

    def test_get_financial_summary_dev_mode(self, dev_client: OdooClient, vault_tmp: Path) -> None:
        summary = get_financial_summary(dev_client, str(vault_tmp))
        assert "monthly_revenue" in summary
        assert "outstanding_invoices" in summary
        assert "recent_payments" in summary
        assert "account_balance" in summary
        assert "as_of" in summary
        assert "error" not in summary

    def test_get_financial_summary_on_client_error_returns_cached(self, vault_tmp: Path) -> None:
        """When client raises, load_cached_summary provides fallback."""
        bad_client = MagicMock()
        bad_client.list_invoices.side_effect = ConnectionError("Odoo down")

        # Pre-seed cache
        cache_data = {"monthly_revenue": 999.0, "as_of": "2026-01-01T00:00:00Z"}
        cache_financial_summary(str(vault_tmp), cache_data)

        result = get_financial_summary(bad_client, str(vault_tmp))
        assert "error" in result
        assert result["last_known"]["monthly_revenue"] == 999.0

    def test_cache_financial_summary_writes_json(self, vault_tmp: Path) -> None:
        summary = {"monthly_revenue": 5000.0, "currency": "USD"}
        cache_financial_summary(str(vault_tmp), summary)
        cache_path = vault_tmp / "Logs" / "odoo_briefing_cache.json"
        assert cache_path.exists()
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        assert data["data"]["monthly_revenue"] == 5000.0
        assert "cached_at" in data

    def test_load_cached_summary_returns_dict(self, vault_tmp: Path) -> None:
        summary = {"monthly_revenue": 1234.0}
        cache_financial_summary(str(vault_tmp), summary)
        result = load_cached_summary(str(vault_tmp))
        assert result is not None
        assert result["data"]["monthly_revenue"] == 1234.0

    def test_load_cached_summary_returns_none_if_missing(self, vault_tmp: Path) -> None:
        result = load_cached_summary(str(vault_tmp))
        assert result is None


# ── TestOdooServer_Read ────────────────────────────────────────────────


class TestOdooServer_Read:
    """Tests for the 5 read-only MCP tools in odoo_server.py."""

    async def test_list_invoices_returns_formatted_string(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import list_invoices

            result = await list_invoices()
        assert "Found 3 invoice(s)" in result
        assert "INV/2026/001" in result

    async def test_list_invoices_invalid_status_returns_error(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import list_invoices

            result = await list_invoices(status="invalid")
        assert "Error" in result

    async def test_list_invoices_connection_error_returns_error_string(self, mock_context: MagicMock) -> None:
        client = mock_context.request_context.lifespan_context.client
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
            patch.object(client, "list_invoices", side_effect=ConnectionError("down")),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import list_invoices

            result = await list_invoices()
        assert "unreachable" in result.lower() or "Error" in result

    async def test_get_invoice_returns_details(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import get_invoice

            result = await get_invoice(1)
        assert "INV/2026/001" in result
        assert "ACME Corp" in result

    async def test_get_invoice_not_found_returns_error(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import get_invoice

            result = await get_invoice(9999)
        assert "Error" in result

    async def test_list_customers_returns_formatted_string(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import list_customers

            result = await list_customers()
        assert "Found 2 customer(s)" in result
        assert "ACME Corp" in result

    async def test_get_account_balance_returns_formatted_string(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import get_account_balance

            result = await get_account_balance(10)
        assert "Balance:" in result
        assert "28600" in result

    async def test_list_transactions_returns_formatted_string(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import list_transactions

            result = await list_transactions(date_from="2026-01-01")
        assert "Found 5 transaction(s)" in result

    async def test_list_transactions_invalid_date_returns_error(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import list_transactions

            result = await list_transactions(date_from="not-a-date")
        assert "Error" in result


# ── TestOdooServer_Write ───────────────────────────────────────────────


class TestOdooServer_Write:
    """Tests for HITL and write MCP tools in odoo_server.py."""

    async def test_create_invoice_no_approval_returns_rejection(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
            patch("backend.mcp_servers.odoo.odoo_server.find_approval", return_value=None),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_invoice

            result = await create_invoice(5, "2026-02-22", [{"product": "X", "quantity": 1, "price_unit": 100}])
        assert "Rejected" in result
        assert "odoo_invoice" in result

    async def test_create_invoice_with_approval_dev_mode_success(
        self, mock_context: MagicMock, vault_tmp: Path
    ) -> None:
        approval_path = vault_tmp / "Approved" / "ODOO_INVOICE_test.md"
        approval_path.write_text(
            "---\ntype: odoo_invoice\nstatus: approved\n---\n# Invoice\n",
            encoding="utf-8",
        )
        approval = {"path": approval_path, "type": "odoo_invoice", "status": "approved"}

        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
            patch("backend.mcp_servers.odoo.odoo_server.find_approval", return_value=approval),
            patch("backend.mcp_servers.odoo.odoo_server.consume_approval"),
            patch("backend.mcp_servers.odoo.odoo_server.update_frontmatter"),
            patch("backend.mcp_servers.odoo.odoo_server.VAULT_PATH", str(vault_tmp)),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_invoice

            result = await create_invoice(5, "2026-02-22", [{"product": "X", "quantity": 1, "price_unit": 100}])
        assert "Invoice created successfully" in result
        assert "9001" in result

    async def test_create_invoice_rate_limited_does_not_consume_approval(
        self, mock_context: MagicMock, vault_tmp: Path
    ) -> None:
        # Set rate limiter to reject
        mock_context.request_context.lifespan_context.rate_limiter.check.return_value = (False, 300)
        approval = {"path": vault_tmp / "Approved" / "ODOO_INVOICE_test.md", "type": "odoo_invoice"}

        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
            patch("backend.mcp_servers.odoo.odoo_server.find_approval", return_value=approval),
            patch("backend.mcp_servers.odoo.odoo_server.consume_approval") as mock_consume,
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_invoice

            result = await create_invoice(5, "2026-02-22", [])
        assert "Rate limit" in result
        mock_consume.assert_not_called()

    async def test_create_payment_no_approval_returns_rejection(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
            patch("backend.mcp_servers.odoo.odoo_server.find_approval", return_value=None),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_payment

            result = await create_payment(1, 1500.0, "2026-02-22", 1)
        assert "Rejected" in result
        assert "odoo_payment" in result

    async def test_create_payment_amount_zero_returns_error(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_payment

            result = await create_payment(1, 0.0, "2026-02-22", 1)
        assert "must be greater than 0" in result

    async def test_create_payment_dev_mode_success(self, mock_context: MagicMock, vault_tmp: Path) -> None:
        approval_path = vault_tmp / "Approved" / "ODOO_PAYMENT_test.md"
        approval_path.write_text(
            "---\ntype: odoo_payment\nstatus: approved\n---\n# Payment\n",
            encoding="utf-8",
        )
        approval = {"path": approval_path, "type": "odoo_payment", "status": "approved"}

        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
            patch("backend.mcp_servers.odoo.odoo_server.find_approval", return_value=approval),
            patch("backend.mcp_servers.odoo.odoo_server.consume_approval"),
            patch("backend.mcp_servers.odoo.odoo_server.update_frontmatter"),
            patch("backend.mcp_servers.odoo.odoo_server.VAULT_PATH", str(vault_tmp)),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_payment

            result = await create_payment(1, 1500.0, "2026-02-22", 1)
        assert "Payment registered successfully" in result
        assert "8001" in result

    async def test_create_payment_already_paid_moves_to_rejected(
        self, mock_context: MagicMock, vault_tmp: Path
    ) -> None:
        approval_path = vault_tmp / "Approved" / "ODOO_PAYMENT_dup.md"
        approval_path.write_text(
            "---\ntype: odoo_payment\nstatus: approved\n---\n",
            encoding="utf-8",
        )
        approval = {"path": approval_path, "type": "odoo_payment"}
        client = mock_context.request_context.lifespan_context.client

        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
            patch("backend.mcp_servers.odoo.odoo_server.find_approval", return_value=approval),
            patch("backend.mcp_servers.odoo.odoo_server.VAULT_PATH", str(vault_tmp)),
            patch.object(client, "create_payment", side_effect=ValueError("already_paid")),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_payment

            result = await create_payment(1, 1500.0, "2026-02-22", 1)
        assert "already fully paid" in result
        rejected_dir = vault_tmp / "Rejected"
        assert any(rejected_dir.iterdir())

    async def test_create_customer_success_dev_mode(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_customer

            result = await create_customer(name="NewCorp", email="billing@newcorp.com")
        assert "Customer created successfully" in result
        assert "9999" in result

    async def test_create_customer_duplicate_no_rate_limit_hit(self, mock_context: MagicMock) -> None:
        client = mock_context.request_context.lifespan_context.client
        mock_rl = mock_context.request_context.lifespan_context.rate_limiter

        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
            patch.object(client, "create_customer", return_value=(5, False)),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_customer

            result = await create_customer(name="ACME Corp")
        assert "already exists" in result
        mock_rl.record_send.assert_not_called()

    async def test_create_customer_empty_name_returns_error(self, mock_context: MagicMock) -> None:
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_customer

            result = await create_customer(name="   ")
        assert "required" in result.lower()

    async def test_create_customer_rate_limited_returns_rejection(self, mock_context: MagicMock) -> None:
        mock_context.request_context.lifespan_context.rate_limiter.check.return_value = (False, 120)
        with (
            patch("backend.mcp_servers.odoo.odoo_server.mcp") as mock_mcp,
            patch("backend.mcp_servers.odoo.odoo_server._log_tool_action"),
        ):
            mock_mcp.get_context.return_value = mock_context
            from backend.mcp_servers.odoo.odoo_server import create_customer

            result = await create_customer(name="SomeCorp")
        assert "Rate limit" in result
