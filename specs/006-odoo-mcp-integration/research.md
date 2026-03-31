# Research: Odoo Accounting MCP Integration

**Feature**: 006-odoo-mcp-integration
**Date**: 2026-02-22
**Phase**: 0 — Outline & Research

---

## 1. Odoo XML-RPC API Pattern

### Decision
Use Python's standard library `xmlrpc.client` (zero new dependencies) for all Odoo communication. No third-party Odoo client library.

### Rationale
- `xmlrpc.client` is part of Python's standard library — no new `pyproject.toml` dependency
- All required Odoo operations (CRUD on accounting models) are fully supported
- The codebase already avoids unnecessary dependencies (pattern from email server using `google-api-python-client`)
- ERPpeek/odoo-rpc-client add overhead without measurable benefit for the 8 tools required

### Alternatives Considered
| Library | Verdict | Reason Rejected |
|---------|---------|-----------------|
| `ERPpeek` | Rejected | External dependency; more useful for interactive/CLI use than server integration |
| `odoo-rpc-client` | Rejected | External dependency; performance benefits irrelevant at this scale |
| `odoo-client-lib` | Rejected | Official Odoo project but adds external dependency |

---

## 2. Odoo XML-RPC Authentication Flow

### Decision
Two-endpoint authentication: `/xmlrpc/2/common` for `authenticate()` → uid, then `/xmlrpc/2/object` for all data operations via `execute_kw()`.

### Implementation Pattern
```python
import xmlrpc.client

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, username, api_key, {})  # returns int uid

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
result = models.execute_kw(db, uid, api_key, 'account.move', 'search_read',
    [[['move_type', '=', 'out_invoice']]],
    {'fields': ['id', 'name', 'amount_total'], 'limit': 20}
)
```

### Credential Strategy
- `ODOO_URL` — server URL (e.g. `http://localhost:8069`)
- `ODOO_DATABASE` — database name (`ai_employee`)
- `ODOO_USERNAME` — login username
- `ODOO_API_KEY` — API key (preferred over password; generated in Odoo Settings → API Keys)
- All stored in `.env`, loaded via `python-dotenv` at server startup

### Async Execution
`xmlrpc.client.ServerProxy` calls are synchronous. Wrap with `asyncio.to_thread()` (same pattern as email server's `gmail.authenticate`).

---

## 3. Odoo Model Field Mapping

### account.move (Invoices)

| Field | Type | Purpose |
|-------|------|---------|
| `id` | int | Record ID |
| `name` | str | Invoice number (e.g., `INV/2026/001`) |
| `move_type` | str | `out_invoice` = customer invoice |
| `partner_id` | [id, name] | Customer reference |
| `invoice_date` | date str | Invoice date |
| `invoice_date_due` | date str | Due date |
| `amount_total` | float | Grand total |
| `currency_id` | [id, name] | Currency |
| `state` | str | `draft`, `posted`, `cancel` |
| `payment_state` | str | `not_paid`, `in_payment`, `paid` |
| `invoice_line_ids` | list[int] | Line item IDs |

**Domain for customer invoices**: `[['move_type', '=', 'out_invoice']]`

### account.payment (Payments)

| Field | Type | Purpose |
|-------|------|---------|
| `id` | int | Record ID |
| `amount` | float | Payment amount |
| `currency_id` | [id, name] | Currency |
| `partner_id` | [id, name] | Customer/vendor |
| `journal_id` | [id, name] | Payment journal (bank/cash) |
| `date` | date str | Payment date |
| `payment_type` | str | `inbound` (received) / `outbound` (sent) |
| `ref` | str | Reference/memo |
| `state` | str | `draft`, `posted` |

**Create payment pattern**: Create `account.payment`, then call `action_post` to confirm.

### res.partner (Customers)

| Field | Type | Purpose |
|-------|------|---------|
| `id` | int | Partner ID |
| `name` | str | Display name |
| `email` | str | Email address |
| `phone` | str | Phone number |
| `is_company` | bool | True = company record |
| `customer_rank` | int | > 0 means is a customer |

**Duplicate check**: `search` with domain `[['name', '=ilike', name]]` before creating.

### account.account (Chart of Accounts — Balance)

| Field | Type | Purpose |
|-------|------|---------|
| `id` | int | Account ID |
| `code` | str | Account code (e.g., `1000`) |
| `name` | str | Account name |
| `account_type` | str | `asset_cash`, `income`, `expense`, etc. |

**Balance computation**: Query `account.move.line` with `[['account_id', '=', account_id], ['parent_state', '=', 'posted']]`, sum `debit` and `credit`.

### account.move.line (Journal Entry Lines — Transactions)

| Field | Type | Purpose |
|-------|------|---------|
| `id` | int | Line ID |
| `move_id` | [id, name] | Parent journal entry |
| `account_id` | [id, name] | GL account |
| `date` | date str | Entry date |
| `name` | str | Description |
| `debit` | float | Debit amount (0 for credits) |
| `credit` | float | Credit amount (0 for debits) |
| `partner_id` | [id, name] | Optional partner |

---

## 4. HITL Vault Pattern for Write Operations

### Decision
Reuse the existing `find_approval()` / `consume_approval()` pattern from `backend/mcp_servers/approval.py`. Write tools check for an approval file in `vault/Approved/` before executing.

### Invoice HITL File Format
```yaml
---
type: odoo_invoice
status: approved
customer_name: ACME Corp
customer_id: 5
invoice_date: "2026-02-22"
lines:
  - product: "Consulting Services"
    quantity: 10
    price_unit: 150.0
    tax_ids: []
approved_at: "2026-02-22T09:00:00Z"
---
```

### Payment HITL File Format
```yaml
---
type: odoo_payment
status: approved
invoice_id: 42
invoice_ref: "INV/2026/001"
amount: 1500.0
currency: USD
payment_date: "2026-02-22"
journal: bank
approved_at: "2026-02-22T09:00:00Z"
---
```

### Rationale
- Consistent with existing email approval pattern — no new mechanisms needed
- `find_approval()` handles multi-file approval scanning and returns most recent match
- `consume_approval()` updates frontmatter and moves file to `vault/Done/`

---

## 5. Rate Limiting Strategy

### Decision
Use the existing `RateLimiter` class with a new `odoo_write` configuration key in `config/rate_limits.json`. Limit: 20 write operations per hour across `create_invoice`, `create_payment`, and `create_customer` combined.

### Configuration Addition to rate_limits.json
```json
"odoo": {
  "writes_per_hour": 20
}
```

### OdooRateLimiter
Subclass `RateLimiter` to read from `odoo.writes_per_hour` instead of `email.sends_per_hour`. The sliding-window implementation is identical.

### Rationale
- 20/hour is consistent with the spec requirement and safely below Odoo's XML-RPC throughput
- Shared limiter across all 3 write tools prevents burst scenarios
- Reusing existing class avoids duplicating sliding-window logic

---

## 6. Async Wrapping

### Decision
All `xmlrpc.client` calls are synchronous. Wrap with `asyncio.to_thread()` inside the `OdooClient` methods to avoid blocking the MCP event loop.

### Pattern
```python
result = await asyncio.to_thread(
    self._models.execute_kw,
    self._db, self._uid, self._api_key,
    'account.move', 'search_read',
    [domain], options
)
```

### Rationale
Matches the email server's `await asyncio.to_thread(app.gmail.search_messages, ...)` pattern. Keeps the event loop non-blocking while maintaining a clean synchronous OdooClient class.

---

## 7. DEV_MODE Strategy

### Decision
In DEV_MODE (`DEV_MODE=true`):
- All read tools return hard-coded mock data (realistic invoices, customers, balances)
- All write tools skip Odoo API call, simulate success, log `[DEV_MODE]`
- Approval file workflow still executes (file moves, status updates) for HITL tools
- Authentication is skipped; `_uid` is set to a mock value (`1`)

### Mock Data Scope
- 3 mock invoices (1 draft, 1 posted/unpaid, 1 paid)
- 2 mock customers
- 1 mock account balance
- 5 mock transactions

### Rationale
Matches existing email server (`if not DEV_MODE: await asyncio.to_thread(gmail.authenticate)`) and Twitter poster patterns. Enables full workflow testing without a running Odoo instance.

---

## 8. CEO Briefing Integration

### Decision
Add a `get_financial_summary()` helper in `utils.py` that aggregates data from the 5 read tools and returns a structured dict. The CEO briefing generator calls this helper and inserts a "Financial Summary" markdown section.

### Financial Summary Data Structure
```python
{
    "monthly_revenue": float,         # Sum of paid invoices this month
    "outstanding_invoices": {
        "count": int,
        "total_value": float,
    },
    "recent_payments": {
        "count": int,               # Last 7 days
        "total_value": float,
    },
    "account_balance": float,         # Company main account
    "currency": str,                  # e.g. "USD"
    "as_of": str,                     # ISO timestamp
}
```

### Graceful Degradation
Wrap the summary call in try/except. On failure, return `{"error": "Odoo unavailable", "last_known": cached_value}`.

### Rationale
Non-invasive: adds one helper function, no changes to existing orchestrator code. The briefing generator decides how to render the data.

---

## 9. MCP Server Registration

### Decision
Add `"odoo"` entry to `config/mcp.json` with `enabled: true` and `backend.mcp_servers.odoo.odoo_server` as the module path.

### config/mcp.json addition
```json
"odoo": {
  "command": "uv",
  "args": ["run", "python", "-m", "backend.mcp_servers.odoo.odoo_server"],
  "cwd": "${workspaceFolder}",
  "capabilities": [
    "list_invoices", "create_invoice", "get_invoice",
    "list_customers", "create_customer",
    "get_account_balance", "list_transactions", "create_payment"
  ],
  "enabled": true
}
```

---

## 10. Error Handling

| Error | Handling |
|-------|----------|
| `xmlrpc.client.Fault` | Catch, extract `faultString`, return user-friendly message, log full fault |
| `xmlrpc.client.ProtocolError` | Catch, log "Odoo unreachable", return error string |
| Authentication failure (uid=False) | Return "Odoo authentication failed — check credentials" |
| Invoice already paid (payment duplicate) | Check `payment_state` before creating payment; return rejection with reason |
| Rate limit exceeded | Return "Rate limit: 20 write ops/hour. Next slot in N seconds." |
| DEV_MODE write | Skip API call, log `[DEV_MODE]`, simulate success response |
