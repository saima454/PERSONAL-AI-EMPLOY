"""End-to-end integration test for Odoo MCP — Live Mode.

Runs all 8 test steps against a real Odoo 17 instance.
Results are logged to vault/Logs/e2e_odoo_YYYYMMDD_HHMMSS.log

Usage:
    uv run python scripts/e2e_odoo_test.py
"""

from __future__ import annotations

import os
import shutil
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

# ── Live-mode credentials ─────────────────────────────────────────────
os.environ["ODOO_URL"] = "http://localhost:8069"
os.environ["ODOO_DATABASE"] = "ai_employee"
os.environ["ODOO_USERNAME"] = "twahaahmed130@gmail.com"
os.environ["ODOO_API_KEY"] = "MyOdoopass1996"
os.environ["DEV_MODE"] = "false"
os.environ["VAULT_PATH"] = "./vault"

VAULT = Path("./vault")
for d in ("Approved", "Pending_Approval", "Done", "Rejected", "Logs/actions"):
    (VAULT / d).mkdir(parents=True, exist_ok=True)

LOG_PATH = VAULT / "Logs" / f"e2e_odoo_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}.log"
_log_lines: list[str] = []


def log(msg: str) -> None:
    ts = datetime.now(tz=UTC).strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    print(entry)
    _log_lines.append(entry)


def save_log() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("\n".join(_log_lines), encoding="utf-8")
    print(f"\nLog saved: {LOG_PATH}")


# ── Imports ───────────────────────────────────────────────────────────
from backend.mcp_servers.approval import consume_approval, find_approval  # noqa: E402
from backend.mcp_servers.odoo.odoo_client import OdooClient  # noqa: E402
from backend.utils.frontmatter import update_frontmatter  # noqa: E402
from backend.utils.timestamps import now_iso  # noqa: E402

# ─────────────────────────────────────────────────────────────────────
log("=" * 62)
log("Odoo E2E Integration Test — LIVE MODE")
log(f"URL: http://localhost:8069 | DB: ai_employee")
log(f"Date: {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
log("=" * 62)

client = OdooClient(
    url="http://localhost:8069",
    db="ai_employee",
    username="twahaahmed130@gmail.com",
    api_key="MyOdoopass1996",
    dev_mode=False,
)

# ── STEP 1: Authentication ────────────────────────────────────────────
log("")
log("STEP 1: Authentication")
try:
    uid = client.authenticate()
    log(f"  PASS  Authenticated — uid={uid}")
except Exception as exc:
    log(f"  FAIL  {exc}")
    save_log()
    sys.exit(1)

# ── STEP 2: list_customers (baseline) ────────────────────────────────
log("")
log("STEP 2: list_customers — baseline before create")
try:
    customers_before = client.list_customers(limit=50)
    log(f"  PASS  {len(customers_before)} existing customer(s)")
    for c in customers_before[:5]:
        log(f"        [{c['id']}] {c['name']}  {c.get('email', '')}")
    if not customers_before:
        log("        (none — fresh database)")
except Exception as exc:
    log(f"  FAIL  {exc}")
    customers_before = []

# ── STEP 3: create_customer ───────────────────────────────────────────
log("")
log('STEP 3: create_customer — "Test Client Alpha" <alpha@test.com>')
cust_id: int | None = None
try:
    cust_id, created = client.create_customer(
        name="Test Client Alpha",
        email="alpha@test.com",
        phone="+1-555-0001",
        is_company=True,
    )
    status = "CREATED" if created else "ALREADY_EXISTS"
    log(f"  PASS  {status} — Odoo partner ID: {cust_id}")
except Exception as exc:
    log(f"  FAIL  {exc}")
    traceback.print_exc()

# ── STEP 4: list_customers (verify) ───────────────────────────────────
log("")
log('STEP 4: list_customers — verify "Test Client Alpha" appears')
try:
    results = client.list_customers(search="Test Client Alpha")
    found = any(c["id"] == cust_id for c in results)
    if found:
        log(f"  PASS  Customer visible in Odoo — ID={cust_id}")
    else:
        log(f"  WARN  Customer not returned by search (id={cust_id})")
    for c in results:
        log(f"        [{c['id']}] {c['name']}  {c.get('email', '')}")
except Exception as exc:
    log(f"  FAIL  {exc}")

# ── STEP 5a: Write invoice approval draft ────────────────────────────
log("")
log("STEP 5a: Write invoice approval file -> Pending_Approval/")
today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
approval_name = f"ODOO_INVOICE_{today}_E2E.md"
pending_path = VAULT / "Pending_Approval" / approval_name

pending_content = f"""---
type: odoo_invoice
status: pending_approval
customer_name: "Test Client Alpha"
customer_id: {cust_id or 1}
invoice_date: "{today}"
lines:
  - product: "Consulting Services"
    quantity: 10
    price_unit: 100.0
generated_at: "{now_iso()}"
---
# Invoice Review

**Customer**: Test Client Alpha
**Date**: {today}

## Line Items

- Consulting Services x 10 @ $100.00

**Estimated Total**: $1,000.00

---
*To approve: move to vault/Approved/ with status: approved.*
"""
pending_path.write_text(pending_content, encoding="utf-8")
log(f"  PASS  Draft created: Pending_Approval/{approval_name}")

# ── STEP 5b: Move to Approved/ ────────────────────────────────────────
log("")
log("STEP 5b: Move approval file to Approved/ (human approval simulation)")
approved_path = VAULT / "Approved" / approval_name
update_frontmatter(pending_path, {"status": "approved", "approved_at": now_iso()})
shutil.move(str(pending_path), str(approved_path))
log(f"  PASS  Moved to Approved/{approval_name}")

# ── STEP 5c: create_invoice via MCP flow ─────────────────────────────
log("")
log("STEP 5c: create_invoice — Consulting Services x10 @ $100 (HITL)")
invoice_id: int | None = None
invoice_ref: str | None = None
try:
    approval = find_approval("./vault", "odoo_invoice")
    if approval is None:
        log("  FAIL  No approval file found in vault/Approved/")
    else:
        log(f"  INFO  Approval found: {approval['path'].name}")
        invoice_id, invoice_ref = client.create_invoice(
            customer_id=cust_id or 1,
            invoice_date=today,
            lines=[{"product": "Consulting Services", "quantity": 10, "price_unit": 100.0}],
        )
        log(f"  PASS  Invoice created — Odoo ID: {invoice_id}, Ref: {invoice_ref}")

        # Update frontmatter + consume (move to Done/)
        update_frontmatter(
            approval["path"],
            {
                "status": "done",
                "odoo_invoice_id": invoice_id,
                "odoo_invoice_ref": invoice_ref,
                "completed_at": now_iso(),
            },
        )
        consume_approval(approval["path"], "./vault")
        done_file = VAULT / "Done" / approval_name
        if done_file.exists():
            log(f"  PASS  Approval consumed -> Done/{approval_name}")
        else:
            log("  WARN  Done file not found (may have been renamed)")
except Exception as exc:
    log(f"  FAIL  {exc}")
    traceback.print_exc()

# ── STEP 6: list_invoices ─────────────────────────────────────────────
log("")
log("STEP 6: list_invoices — verify new invoice visible")
try:
    invoices = client.list_invoices(limit=20, status="posted")
    log(f"  PASS  {len(invoices)} posted invoice(s)")
    for inv in invoices[:10]:
        marker = " <<<< NEW" if inv.get("id") == invoice_id else ""
        log(
            f"        [{inv['id']}] {inv['number']} | {inv['customer_name']} "
            f"| ${inv['amount_total']:.2f} | {inv['payment_status']}{marker}"
        )
    if invoice_id and not any(i["id"] == invoice_id for i in invoices):
        log(f"  INFO  Invoice {invoice_id} not in 'posted' list — trying status=all")
        all_inv = client.list_invoices(limit=20, status="all")
        match = next((i for i in all_inv if i["id"] == invoice_id), None)
        if match:
            log(f"  INFO  Found in all: [{match['id']}] {match['number']} state={match['status']}")
except Exception as exc:
    log(f"  FAIL  {exc}")
    traceback.print_exc()

# ── STEP 7: get_account_balance ───────────────────────────────────────
log("")
log("STEP 7: get_account_balance — 1121001 Receivable from Customers (id=13)")
try:
    bal = client.get_account_balance(13)
    log(f"  PASS  [{bal['code']}] {bal['name']}")
    log(f"        Balance:  ${bal['balance']:,.2f} {bal['currency']}")
    log(f"        Debit:    ${bal['debit']:,.2f}")
    log(f"        Credit:   ${bal['credit']:,.2f}")
except Exception as exc:
    log(f"  FAIL  {exc}")
    traceback.print_exc()

# Also show Bank account
log("")
log("STEP 7b: get_account_balance — Bank account (journal id=6 -> find account)")
try:
    # Find the bank account linked to journal 6
    import xmlrpc.client as xc
    m = xc.ServerProxy("http://localhost:8069/xmlrpc/2/object")
    jrnl = m.execute_kw("ai_employee", uid, "MyOdoopass1996",
        "account.journal", "read", [[6]], {"fields": ["default_account_id"]})
    if jrnl and jrnl[0].get("default_account_id"):
        bank_acc_id = jrnl[0]["default_account_id"][0]
        bal2 = client.get_account_balance(bank_acc_id)
        log(f"  PASS  [{bal2['code']}] {bal2['name']}")
        log(f"        Balance:  ${bal2['balance']:,.2f} {bal2['currency']}")
        log(f"        Debit:    ${bal2['debit']:,.2f}")
        log(f"        Credit:   ${bal2['credit']:,.2f}")
    else:
        log("  INFO  Bank journal has no default account configured")
except Exception as exc:
    log(f"  FAIL  {exc}")

# ── STEP 8: list_transactions ─────────────────────────────────────────
log("")
log("STEP 8: list_transactions — last 30 days, receivable account")
try:
    txns = client.list_transactions(account_id=13, limit=15)
    log(f"  PASS  {len(txns)} journal entry lines on receivable account")
    for t in txns[:8]:
        dr_cr = f"DR ${t['debit']:.2f}" if t["debit"] else f"CR ${t['credit']:.2f}"
        log(f"        {t['date']} | {t['journal_entry'][:20]:20s} | {dr_cr}")
except Exception as exc:
    log(f"  FAIL  {exc}")
    traceback.print_exc()

# ── Summary ───────────────────────────────────────────────────────────
log("")
log("=" * 62)
log("E2E TEST COMPLETE — LIVE MODE (DEV_MODE=false)")
if invoice_id:
    log(f"  Invoice created: ID={invoice_id}, Ref={invoice_ref}")
if cust_id:
    log(f"  Customer created: ID={cust_id}, Name=Test Client Alpha")
log("  DEV_MODE remains false — set it back in .env if needed")
log("=" * 62)

save_log()
