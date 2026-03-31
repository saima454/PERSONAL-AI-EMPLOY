# Skill: Odoo Accounting Integration (Gold Tier)

**Version**: 1.0.0
**Tier**: Gold
**MCP Server**: `backend/mcp_servers/odoo/odoo_server.py`

## Overview

Connects the AI Employee to a self-hosted **Odoo Community Edition** instance via XML-RPC for accounting and invoicing operations. Exposes 9 MCP tools: 5 read-only and 3 write tools (2 with HITL approval) plus a financial summary tool for the CEO briefing.

## Trigger Keywords

```
invoice, invoices, customer, customers, balance, payment, payments,
odoo, financial, revenue, outstanding, transactions, journal, accounting
```

## Dependencies

- Odoo Community Edition running at `ODOO_URL` (default: `http://localhost:8069`)
- `.env` configured with `ODOO_URL`, `ODOO_DATABASE`, `ODOO_USERNAME`, `ODOO_API_KEY`
- `VAULT_PATH` directory with `Approved/`, `Done/`, `Rejected/` subdirectories

---

## Tools Reference

### 1. `list_invoices` — List Customer Invoices

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Maximum invoices (1–100) |
| `offset` | int | 0 | Pagination offset |
| `status` | str | `"posted"` | `draft`, `posted`, `paid`, or `all` |

**HITL**: No
**Rate limited**: No
**DEV_MODE**: Returns 3 hardcoded invoices (ACME Corp, Beta Ltd, Gamma Inc)

```
list_invoices(status="paid")
→ "Found 1 invoice(s) with status 'paid':\n1. INV/2026/002 | Beta Ltd | $3200.00 USD | 2026-02-10 | paid"
```

---

### 2. `get_invoice` — Get Invoice Details

| Parameter | Type | Description |
|-----------|------|-------------|
| `invoice_id` | int | Odoo `account.move` record ID |

**HITL**: No | **DEV_MODE**: Returns hardcoded details for ID 1, raises `ValueError` for others.

```
get_invoice(invoice_id=1)
→ "Invoice: INV/2026/001\nCustomer: ACME Corp\n..."
```

---

### 3. `list_customers` — List Customer Records

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | str | `""` | Name/email search (case-insensitive) |
| `limit` | int | 20 | Maximum results (1–50) |

**HITL**: No | **DEV_MODE**: Returns ACME Corp and Beta Ltd.

---

### 4. `get_account_balance` — Get Account Balance

| Parameter | Type | Description |
|-----------|------|-------------|
| `account_id` | int | Odoo `account.account` record ID |

**HITL**: No | **DEV_MODE**: Returns mock Bank account with balance $28,600.00

```
get_account_balance(account_id=10)
→ "Account: 1010 — Bank\nBalance: $28600.00 USD\n(Debit: $45000.00 | Credit: $16400.00)"
```

---

### 5. `list_transactions` — List Journal Entry Lines

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `date_from` | str | 30 days ago | Start date `YYYY-MM-DD` |
| `date_to` | str | `""` | End date `YYYY-MM-DD` |
| `account_id` | int | 0 | Filter by account (0 = all) |
| `limit` | int | 50 | Maximum results (1–200) |

**HITL**: No | **DEV_MODE**: Returns 5 hardcoded journal entries.

---

### 6. `create_invoice` — Create Customer Invoice ⚠️ HITL

| Parameter | Type | Description |
|-----------|------|-------------|
| `customer_id` | int | Odoo `res.partner` ID |
| `invoice_date` | str | Date `YYYY-MM-DD` |
| `lines` | list[dict] | Line items with `product`, `quantity`, `price_unit` |

**HITL**: Yes — requires approval file in `vault/Approved/` with `type: odoo_invoice`
**Rate limited**: Yes (shared 20 ops/hour)
**DEV_MODE**: Returns `odoo_invoice_id: 9001, odoo_invoice_ref: "DEV/2026/001"`

---

### 7. `create_payment` — Register Payment ⚠️ HITL

| Parameter | Type | Description |
|-----------|------|-------------|
| `invoice_id` | int | Odoo `account.move` ID to settle |
| `amount` | float | Payment amount (must be > 0) |
| `payment_date` | str | Date `YYYY-MM-DD` |
| `journal_id` | int | Odoo journal ID (bank/cash) |
| `memo` | str | Optional reference memo |

**HITL**: Yes — requires approval file in `vault/Approved/` with `type: odoo_payment`
**Rate limited**: Yes (shared 20 ops/hour)
**DEV_MODE**: Returns `odoo_payment_id: 8001`

---

### 8. `create_customer` — Create Customer Record

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | — | Customer name (required) |
| `email` | str | `""` | Email address |
| `phone` | str | `""` | Phone number |
| `is_company` | bool | `True` | Business vs. individual |

**HITL**: No — executes immediately (duplicate check prevents redundant creates)
**Rate limited**: Yes (only when a new record is actually created)
**DEV_MODE**: Returns `customer_id: 9999`

---

### 9. `odoo_financial_summary` — CEO Briefing Data

No parameters.

Returns aggregated financial snapshot:
- Monthly revenue (paid invoices, current calendar month)
- Outstanding invoices (count + total)
- Recent payments (last 7 days)
- Main account balance

**HITL**: No | **Rate limited**: No
**DEV_MODE**: Aggregates from mock invoice/transaction/balance data
**Degradation**: Falls back to cached data in `vault/Logs/odoo_briefing_cache.json` if Odoo is unreachable.

```
odoo_financial_summary()
→ "## Financial Summary (Odoo)\n\n*As of 2026-02-22T...*\n- **Monthly Revenue**: $3200.00 USD\n..."
```

---

## HITL Vault Workflow

For `create_invoice` and `create_payment`, approval files must flow through the vault:

```
vault/Pending_Approval/ODOO_INVOICE_YYYY-MM-DD.md   ← AI writes draft
         ↓  (human reviews and moves)
vault/Approved/ODOO_INVOICE_YYYY-MM-DD.md           ← human approves
         ↓  (MCP tool executes + consumes)
vault/Done/ODOO_INVOICE_YYYY-MM-DD.md               ← tool succeeded
    OR
vault/Rejected/ODOO_INVOICE_YYYY-MM-DD.md           ← tool failed / Odoo fault
```

### Approval File Format (Invoice)

```yaml
---
type: odoo_invoice
status: approved
customer_name: "ACME Corp"
customer_id: 5
invoice_date: "2026-02-22"
lines:
  - product: "Consulting Services"
    quantity: 10
    price_unit: 150.0
approved_at: "2026-02-22T09:00:00Z"
---
# Invoice Review
...
```

### Approval File Format (Payment)

```yaml
---
type: odoo_payment
status: approved
invoice_id: 42
invoice_ref: "INV/2026/001"
amount: 1500.0
currency: "USD"
payment_date: "2026-02-22"
journal: "bank"
approved_at: "2026-02-22T09:00:00Z"
---
```

---

## CEO Briefing Integration

The `odoo_financial_summary` tool feeds the daily CEO briefing with:

```markdown
## Financial Summary (Odoo)

*As of 2026-02-22T08:00:00Z*

- **Monthly Revenue**: $3,200.00 USD
- **Outstanding Invoices**: 2 invoices · $2,250.00 USD total
- **Recent Payments** (last 7 days): 1 payments · $3,200.00 USD
- **Account Balance**: $28,600.00 USD
```

Cache file: `vault/Logs/odoo_briefing_cache.json` — used when Odoo is temporarily unreachable.

---

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| `Rejected: No approval file found` | HITL tool called without vault approval | Create and approve an `ODOO_INVOICE_*.md` or `ODOO_PAYMENT_*.md` file |
| `Rate limit exceeded` | >20 write ops in last hour | Wait for the stated seconds; check `vault/Logs/actions/` for recent operations |
| `Odoo server unreachable` | Network/auth failure | Verify `ODOO_URL`, check Odoo is running; financial summary falls back to cache |
| `Invoice ID N not found` | Invalid `invoice_id` parameter | Use `list_invoices` to find valid IDs |
| `Invoice is already fully paid` | Duplicate payment attempt | Check `get_invoice` for payment status before submitting |
| `Authentication failed` | Wrong `ODOO_USERNAME` or `ODOO_API_KEY` | Regenerate API key in Odoo Settings → Technical → API Keys |

---

## Rate Limits

All write operations share a single **20 ops/hour** sliding-window rate limiter.

- Write operations: `create_invoice`, `create_payment`, `create_customer` (new records only)
- Duplicate customer detection does **not** consume a rate limit slot
- Current count resets after 3600 seconds from the oldest recorded write
- Configuration: `config/rate_limits.json` → `odoo.writes_per_hour`

---

## Environment Variables

```bash
ODOO_URL=http://localhost:8069          # Odoo base URL (no trailing slash)
ODOO_DATABASE=ai_employee               # Odoo database name
ODOO_USERNAME=admin@example.com         # Odoo login username
ODOO_API_KEY=your-odoo-api-key-here    # API key from Odoo Settings
ODOO_MAIN_ACCOUNT_ID=1                 # Default account for balance queries
DEV_MODE=true                          # Set false for live Odoo calls
VAULT_PATH=./vault                     # Vault root directory
```

---

## DEV_MODE Behaviour

When `DEV_MODE=true`:
- **Read tools**: Return hardcoded mock data (3 invoices, 2 customers, 1 account, 5 transactions)
- **Write tools**: Simulate success without any Odoo API call
  - `create_invoice` → returns ID 9001, ref `"DEV/2026/001"`
  - `create_payment` → returns ID 8001
  - `create_customer` → returns ID 9999, `created=True`
- **Vault file movements** still execute (approval → done/rejected)
- **Audit logs** still written to `vault/Logs/actions/`

---

## Implementation Files

```
backend/mcp_servers/odoo/
├── __init__.py          # Package marker
├── odoo_server.py       # FastMCP server + 9 tool handlers + OdooRateLimiter
├── odoo_client.py       # OdooClient XML-RPC wrapper (sync, all models)
└── utils.py             # write_invoice_draft, write_payment_draft, get_financial_summary
```
