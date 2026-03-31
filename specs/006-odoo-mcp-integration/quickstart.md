# Quickstart & Integration Scenarios: Odoo Accounting MCP Integration

**Feature**: 006-odoo-mcp-integration
**Date**: 2026-02-22

---

## Prerequisites

1. Odoo Community Edition 17 running at `http://localhost:8069` with database `ai_employee`
2. Odoo API key generated: Settings → Technical → API Keys → New API Key
3. `.env` configured:
   ```
   ODOO_URL=http://localhost:8069
   ODOO_DATABASE=ai_employee
   ODOO_USERNAME=admin@example.com
   ODOO_API_KEY=your-api-key-here
   DEV_MODE=true
   ```
4. `config/mcp.json` has the `odoo` server entry enabled

---

## Scenario 1: Start the MCP Server (Manual)

```bash
# From project root
uv run python -m backend.mcp_servers.odoo.odoo_server
```

On startup you should see on stderr:
```
2026-02-22 09:00:00 [backend.mcp_servers.odoo.odoo_server] INFO: Odoo MCP server started (DEV_MODE=True, vault=./vault)
```

---

## Scenario 2: Query Invoices (Read — No Approval Needed)

Ask Claude Code or invoke directly:

```
list_invoices(status="posted", limit=10)
```

**Expected DEV_MODE response**:
```
Found 3 invoice(s) with status 'posted':

1. INV/2026/001 | ACME Corp | $1,500.00 USD | 2026-02-01 | not_paid
2. INV/2026/002 | Beta Ltd  | $3,200.00 USD | 2026-02-10 | paid
3. INV/2026/003 | Gamma Inc | $750.00 USD  | 2026-02-15 | in_payment
```

---

## Scenario 3: Create a Customer (Write — No HITL)

```
create_customer(name="NewCorp Ltd", email="billing@newcorp.com", phone="+1-555-0100")
```

**Expected DEV_MODE response**:
```
[DEV_MODE] Customer creation simulated. Mock ID: 9999. Name: NewCorp Ltd
```

**Expected live response**:
```
Customer created successfully. Odoo ID: 42. Name: NewCorp Ltd
```

---

## Scenario 4: Create an Invoice (Full HITL Workflow)

### Step 1 — Generate Draft (Claude Code does this)

Claude Code drafts the invoice and writes:

**`vault/Pending_Approval/ODOO_INVOICE_2026-02-22.md`**
```markdown
---
type: odoo_invoice
status: pending_approval
customer_name: ACME Corp
customer_id: 5
invoice_date: "2026-02-22"
lines:
  - product: "Consulting Services"
    quantity: 10
    price_unit: 150.0
  - product: "Travel Expenses"
    quantity: 1
    price_unit: 200.0
generated_at: "2026-02-22T09:00:00Z"
---

# Invoice Review

Customer: ACME Corp
Date: 2026-02-22
Line 1: Consulting Services × 10 @ $150 = $1,500
Line 2: Travel Expenses × 1 @ $200 = $200
Total: $1,700.00 USD
```

### Step 2 — Human Review

Open Obsidian, review the file in `vault/Pending_Approval/`.

### Step 3 — Approve

Move the file to `vault/Approved/` and update frontmatter:
```yaml
status: approved
approved_at: "2026-02-22T10:15:00Z"
```

### Step 4 — Execute

Ask Claude Code to invoke the tool:
```
create_invoice(customer_id=5, invoice_date="2026-02-22", lines=[...])
```

**Expected DEV_MODE response**:
```
[DEV_MODE] Invoice creation simulated. Mock Odoo ID: 9001.
Approval file moved to vault/Done/.
```

**Expected live response**:
```
Invoice created successfully. Odoo ID: 123. Invoice Ref: INV/2026/004.
Approval file moved to vault/Done/.
```

The done file at `vault/Done/ODOO_INVOICE_2026-02-22.md` will contain:
```yaml
status: done
odoo_invoice_id: 123
odoo_invoice_ref: "INV/2026/004"
completed_at: "2026-02-22T10:15:30Z"
```

---

## Scenario 5: Record a Payment (Full HITL Workflow)

### Step 1 — Generate Draft

**`vault/Pending_Approval/ODOO_PAYMENT_2026-02-22.md`**
```markdown
---
type: odoo_payment
status: pending_approval
invoice_id: 42
invoice_ref: "INV/2026/001"
amount: 1500.0
currency: USD
payment_date: "2026-02-22"
journal: bank
generated_at: "2026-02-22T11:00:00Z"
---

# Payment Review

Invoice: INV/2026/001 (ACME Corp)
Amount: $1,500.00 USD
Date: 2026-02-22
Journal: Bank
```

### Step 2–3 — Review & Approve (same as invoice scenario)

### Step 4 — Execute

```
create_payment(invoice_id=42, amount=1500.0, payment_date="2026-02-22", journal_id=1)
```

**Expected response**:
```
Payment registered successfully. Odoo Payment ID: 87.
Invoice INV/2026/001 is now paid.
Approval file moved to vault/Done/.
```

---

## Scenario 6: CEO Briefing with Financial Summary (DEV_MODE)

The CEO briefing generator calls `get_financial_summary()` from `utils.py`:

**Expected section in `vault/Briefings/CEO_Briefing_2026-02-22.md`**:
```markdown
## Financial Summary (Odoo)

*As of 2026-02-22 09:00 UTC*

- **Monthly Revenue** (February 2026): $12,400.00 USD
- **Outstanding Invoices**: 4 invoices · $7,200.00 USD total
- **Recent Payments** (last 7 days): 2 payments · $3,150.00 USD
- **Account Balance** (Bank): $28,600.00 USD
```

**DEV_MODE label visible**:
```markdown
## Financial Summary (Odoo) ⚠️ DEV_MODE — Mock Data

*As of 2026-02-22 09:00 UTC*
```

---

## Scenario 7: Rate Limit Rejection

After 20 write operations in one hour:

```
create_invoice(...)
→ "Rejected: Rate limit exceeded (20 write ops/hour). Next slot in 1847 seconds."
```

The approval file remains in `vault/Approved/` for retry.

---

## Scenario 8: Odoo Unreachable (Graceful Degradation)

If Odoo is offline when a read tool is called:

```
list_invoices()
→ "Error: Odoo server unreachable — [Errno 111] Connection refused"
```

If the CEO briefing runs while Odoo is offline:
```
## Financial Summary (Odoo)

⚠️ Odoo data unavailable. Last known values shown (from 2026-02-21 09:00 UTC):
- Monthly Revenue: $11,200.00 USD (stale)
- Outstanding Invoices: 3 invoices · $5,700.00 USD (stale)
```

---

## Running Tests

```bash
# Odoo-specific tests only
uv run pytest tests/test_odoo.py -v

# Full regression
uv run pytest

# Linting
uv run ruff check
```
