"""Tests for backend.orchestrator.action_executor — action dispatch and execution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.orchestrator.action_executor import ActionExecutor
from backend.orchestrator.orchestrator import OrchestratorConfig

# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def config(tmp_path: Path) -> OrchestratorConfig:
    """Config with vault in temp directory."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Approved").mkdir()
    (vault / "Done").mkdir()
    (vault / "Logs" / "actions").mkdir(parents=True)
    return OrchestratorConfig(
        vault_path=str(vault),
        check_interval=1,
        dev_mode=True,
    )


@pytest.fixture
def executor(config: OrchestratorConfig) -> ActionExecutor:
    return ActionExecutor(config)


def _create_approval(approved_dir: Path, name: str, action_type: str, **extra: str) -> Path:
    """Create a test approval file with frontmatter."""
    fm_lines = [
        "---",
        f"type: {action_type}",
        "status: approved",
    ]
    for k, v in extra.items():
        fm_lines.append(f"{k}: {v}")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append("## Email Content")
    fm_lines.append("")
    fm_lines.append("Test email body content.")
    content = "\n".join(fm_lines)
    file_path = approved_dir / name
    file_path.write_text(content, encoding="utf-8")
    return file_path


# ── Scan Tests ───────────────────────────────────────────────────


class TestScanApproved:
    def test_empty_directory(self, executor: ActionExecutor) -> None:
        results = executor._scan_approved()
        assert results == []

    def test_finds_approved_files(
        self, executor: ActionExecutor, config: OrchestratorConfig
    ) -> None:
        approved = Path(config.vault_path) / "Approved"
        _create_approval(approved, "test.md", "email_send", to="a@b.com", subject="Hi")
        results = executor._scan_approved()
        assert len(results) == 1
        assert results[0][1]["type"] == "email_send"

    def test_ignores_non_approved_status(
        self, executor: ActionExecutor, config: OrchestratorConfig
    ) -> None:
        approved = Path(config.vault_path) / "Approved"
        path = approved / "pending.md"
        path.write_text("---\ntype: email_send\nstatus: pending\n---\n", encoding="utf-8")
        results = executor._scan_approved()
        assert results == []


# ── DEV_MODE Tests ───────────────────────────────────────────────


class TestDevMode:
    @pytest.mark.asyncio
    async def test_dev_mode_moves_to_done(
        self, executor: ActionExecutor, config: OrchestratorConfig
    ) -> None:
        approved = Path(config.vault_path) / "Approved"
        done = Path(config.vault_path) / "Done"
        _create_approval(approved, "test.md", "email_send", to="a@b.com", subject="Hi")

        files = executor._scan_approved()
        assert len(files) == 1

        result = await executor.process_file(files[0][0], files[0][1])
        assert result is True
        assert not (approved / "test.md").exists()
        assert (done / "test.md").exists()

    @pytest.mark.asyncio
    async def test_dev_mode_logs_event(
        self, executor: ActionExecutor, config: OrchestratorConfig
    ) -> None:
        approved = Path(config.vault_path) / "Approved"
        _create_approval(approved, "test.md", "email_send", to="a@b.com", subject="Hi")

        files = executor._scan_approved()
        await executor.process_file(files[0][0], files[0][1])

        log_dir = Path(config.vault_path) / "Logs" / "actions"
        log_files = list(log_dir.glob("*.json"))
        assert len(log_files) > 0


# ── Dispatch Tests ───────────────────────────────────────────────


class TestDispatch:
    @pytest.mark.asyncio
    async def test_unknown_type_returns_false(self, config: OrchestratorConfig) -> None:
        config.dev_mode = False
        executor = ActionExecutor(config)
        approved = Path(config.vault_path) / "Approved"
        path = _create_approval(approved, "unknown.md", "unknown_type")

        result = await executor.process_file(path, {"type": "unknown_type", "status": "approved"})
        assert result is False
        # File should still be in Approved
        assert path.exists()

    @pytest.mark.asyncio
    async def test_email_send_dispatches_correctly(self, config: OrchestratorConfig) -> None:
        config.dev_mode = False
        executor = ActionExecutor(config)
        approved = Path(config.vault_path) / "Approved"
        path = _create_approval(approved, "send.md", "email_send", to="a@b.com", subject="Test")

        mock_client = MagicMock()
        mock_client.authenticate = MagicMock()
        mock_client.send_message = MagicMock(return_value={"id": "msg123"})
        executor._gmail_client = mock_client

        mock_rl = MagicMock()
        mock_rl.check = MagicMock(return_value=(True, 0))
        mock_rl.record_send = MagicMock()
        executor._rate_limiter = mock_rl

        fm = {"type": "email_send", "status": "approved", "to": "a@b.com", "subject": "Test"}
        result = await executor.process_file(path, fm)
        assert result is True
        mock_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_send(self, config: OrchestratorConfig) -> None:
        config.dev_mode = False
        executor = ActionExecutor(config)
        approved = Path(config.vault_path) / "Approved"
        path = _create_approval(approved, "limited.md", "email_send", to="a@b.com", subject="Test")

        mock_client = MagicMock()
        executor._gmail_client = mock_client

        mock_rl = MagicMock()
        mock_rl.check = MagicMock(return_value=(False, 300))
        executor._rate_limiter = mock_rl

        fm = {"type": "email_send", "status": "approved", "to": "a@b.com", "subject": "Test"}
        result = await executor.process_file(path, fm)
        assert result is False
        # File should still be in Approved on failure
        assert path.exists()


# ── Email Body Extraction ────────────────────────────────────────


class TestEmailBodyExtraction:
    def test_extracts_email_content_section(self) -> None:
        body = "## Email Content\n\nHello World\n\n## Metadata\n\nStuff"
        result = ActionExecutor._extract_email_body(body)
        assert result == "Hello World"

    def test_fallback_to_full_body(self) -> None:
        body = "Just some text without sections"
        result = ActionExecutor._extract_email_body(body)
        assert result == "Just some text without sections"


# ── Odoo Handler Tests ──────────────────────────────────────────


def _create_odoo_invoice_approval(approved_dir: Path, name: str = "ODOO_INVOICE_test.md") -> Path:
    """Create a test Odoo invoice approval file."""
    content = (
        "---\n"
        "type: odoo_invoice\n"
        "status: approved\n"
        "customer_name: Test Client\n"
        "customer_id: 7\n"
        "invoice_date: '2026-02-22'\n"
        "lines:\n"
        "- product: Consulting Services\n"
        "  quantity: 10\n"
        "  price_unit: 100.0\n"
        "approved_at: '2026-02-22T00:00:00Z'\n"
        "---\n"
        "# Invoice Review\n\n"
        "**Customer**: Test Client\n"
    )
    file_path = approved_dir / name
    file_path.write_text(content, encoding="utf-8")
    return file_path


def _create_odoo_payment_approval(approved_dir: Path, name: str = "ODOO_PAYMENT_test.md") -> Path:
    """Create a test Odoo payment approval file."""
    content = (
        "---\n"
        "type: odoo_payment\n"
        "status: approved\n"
        "invoice_id: 1\n"
        "amount: 1000.0\n"
        "payment_date: '2026-02-22'\n"
        "journal_id: 7\n"
        "memo: Test payment\n"
        "approved_at: '2026-02-22T00:00:00Z'\n"
        "---\n"
        "# Payment Review\n"
    )
    file_path = approved_dir / name
    file_path.write_text(content, encoding="utf-8")
    return file_path


class TestOdooInvoiceHandler:
    @pytest.mark.asyncio
    async def test_dev_mode_moves_invoice_to_done(
        self, executor: ActionExecutor, config: OrchestratorConfig
    ) -> None:
        """In DEV_MODE, odoo_invoice files should be logged and moved to Done."""
        approved = Path(config.vault_path) / "Approved"
        done = Path(config.vault_path) / "Done"
        _create_odoo_invoice_approval(approved)

        files = executor._scan_approved()
        assert len(files) == 1
        assert files[0][1]["type"] == "odoo_invoice"

        result = await executor.process_file(files[0][0], files[0][1])
        assert result is True
        assert not (approved / "ODOO_INVOICE_test.md").exists()
        assert (done / "ODOO_INVOICE_test.md").exists()

    @pytest.mark.asyncio
    async def test_invoice_handler_calls_odoo_client(self, config: OrchestratorConfig) -> None:
        """Production mode: handler should call OdooClient.create_invoice."""
        config.dev_mode = False
        executor = ActionExecutor(config)
        approved = Path(config.vault_path) / "Approved"
        path = _create_odoo_invoice_approval(approved)

        mock_client = MagicMock()
        mock_client.authenticate = MagicMock()
        mock_client.create_invoice = MagicMock(return_value=(42, "INV/2026/TEST"))
        mock_client.create_customer = MagicMock(return_value=(7, False))
        executor._odoo_client = mock_client

        fm = {
            "type": "odoo_invoice",
            "status": "approved",
            "customer_name": "Test Client",
            "customer_id": 7,
            "invoice_date": "2026-02-22",
            "lines": [{"product": "Consulting", "quantity": 10, "price_unit": 100.0}],
        }
        result = await executor.process_file(path, fm)
        assert result is True
        mock_client.create_invoice.assert_called_once_with(
            7, "2026-02-22", [{"product": "Consulting", "quantity": 10, "price_unit": 100.0}]
        )

    @pytest.mark.asyncio
    async def test_invoice_missing_customer_id_fails(self, config: OrchestratorConfig) -> None:
        """Handler should fail if customer_id is missing."""
        config.dev_mode = False
        executor = ActionExecutor(config)
        approved = Path(config.vault_path) / "Approved"
        path = approved / "bad_invoice.md"
        path.write_text(
            "---\ntype: odoo_invoice\nstatus: approved\nlines:\n- product: X\n  quantity: 1\n  price_unit: 10\n---\n",
            encoding="utf-8",
        )

        mock_client = MagicMock()
        executor._odoo_client = mock_client

        fm = {"type": "odoo_invoice", "status": "approved", "lines": [{"product": "X"}]}
        result = await executor.process_file(path, fm)
        assert result is False
        mock_client.create_invoice.assert_not_called()


class TestOdooPaymentHandler:
    @pytest.mark.asyncio
    async def test_dev_mode_moves_payment_to_done(
        self, executor: ActionExecutor, config: OrchestratorConfig
    ) -> None:
        """In DEV_MODE, odoo_payment files should be logged and moved to Done."""
        approved = Path(config.vault_path) / "Approved"
        done = Path(config.vault_path) / "Done"
        _create_odoo_payment_approval(approved)

        files = executor._scan_approved()
        assert len(files) == 1
        assert files[0][1]["type"] == "odoo_payment"

        result = await executor.process_file(files[0][0], files[0][1])
        assert result is True
        assert not (approved / "ODOO_PAYMENT_test.md").exists()
        assert (done / "ODOO_PAYMENT_test.md").exists()

    @pytest.mark.asyncio
    async def test_payment_handler_calls_odoo_client(self, config: OrchestratorConfig) -> None:
        """Production mode: handler should call OdooClient.create_payment."""
        config.dev_mode = False
        executor = ActionExecutor(config)
        approved = Path(config.vault_path) / "Approved"
        path = _create_odoo_payment_approval(approved)

        mock_client = MagicMock()
        mock_client.authenticate = MagicMock()
        mock_client.create_payment = MagicMock(return_value=101)
        executor._odoo_client = mock_client

        fm = {
            "type": "odoo_payment",
            "status": "approved",
            "invoice_id": 1,
            "amount": 1000.0,
            "payment_date": "2026-02-22",
            "journal_id": 7,
            "memo": "Test payment",
        }
        result = await executor.process_file(path, fm)
        assert result is True
        mock_client.create_payment.assert_called_once_with(
            1, 1000.0, "2026-02-22", 7, "Test payment"
        )

    @pytest.mark.asyncio
    async def test_payment_missing_invoice_id_fails(self, config: OrchestratorConfig) -> None:
        """Handler should fail if invoice_id is missing."""
        config.dev_mode = False
        executor = ActionExecutor(config)
        approved = Path(config.vault_path) / "Approved"
        path = approved / "bad_payment.md"
        path.write_text(
            "---\ntype: odoo_payment\nstatus: approved\namount: 100\njournal_id: 7\n---\n",
            encoding="utf-8",
        )

        mock_client = MagicMock()
        executor._odoo_client = mock_client

        fm = {"type": "odoo_payment", "status": "approved", "amount": 100, "journal_id": 7}
        result = await executor.process_file(path, fm)
        assert result is False
        mock_client.create_payment.assert_not_called()
