# MCP Tool Contracts: Odoo Accounting Integration

**Feature**: 006-odoo-mcp-integration
**Date**: 2026-02-22
**Server Name**: `odoo-mcp-server`
**Transport**: stdio
**Module**: `backend.mcp_servers.odoo.odoo_server`

---

## Tool: `list_invoices`

**User Story**: US1 (P1) — Query Financial Data
**HITL Required**: No
**Rate Limited**: No
**DEV_MODE**: Returns mock data

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | int | No | 20 | Max invoices to return (1–100) |
| `offset` | int | No | 0 | Pagination offset |
| `status` | str | No | `"posted"` | Filter: `draft`, `posted`, `paid`, or `all` |

### Returns
Formatted string with invoice list. Each entry includes:
- Invoice number
- Customer name
- Amount + currency
- Invoice date
- Payment status

### Errors
| Condition | Response |
|-----------|----------|
| Odoo unreachable | `"Error: Odoo server unreachable — {detail}"` |
| Auth failure | `"Error: Odoo authentication failed — check ODOO_* credentials"` |
| No invoices found | `"No invoices found matching criteria."` |

---

## Tool: `get_invoice`

**User Story**: US1 (P1) — Query Financial Data
**HITL Required**: No
**Rate Limited**: No
**DEV_MODE**: Returns mock data

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `invoice_id` | int | Yes | — | Odoo invoice record ID |

### Returns
Formatted string with full invoice details:
- Header: number, customer, dates, totals, status
- Line items: product, quantity, unit price, subtotal
- Payments applied (if any)

### Errors
| Condition | Response |
|-----------|----------|
| Invoice not found | `"Error: Invoice ID {id} not found in Odoo."` |
| Odoo unreachable | `"Error: Odoo server unreachable — {detail}"` |

---

## Tool: `list_customers`

**User Story**: US1 (P1) — Query Financial Data
**HITL Required**: No
**Rate Limited**: No
**DEV_MODE**: Returns mock data

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `search` | str | No | `""` | Name/email search string (case-insensitive) |
| `limit` | int | No | 20 | Max customers to return (1–50) |

### Returns
Formatted string with customer list. Each entry includes:
- Customer ID
- Name
- Email
- Phone (if available)
- Outstanding balance

### Errors
| Condition | Response |
|-----------|----------|
| No matches | `"No customers found matching: {search}"` |
| Odoo unreachable | `"Error: Odoo server unreachable — {detail}"` |

---

## Tool: `create_customer`

**User Story**: US5 (P5) — Create Customer Record
**HITL Required**: No
**Rate Limited**: Yes (shared 20/hour write limit)
**DEV_MODE**: Simulates creation, returns mock ID

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | str | Yes | — | Customer display name |
| `email` | str | No | `""` | Email address |
| `phone` | str | No | `""` | Phone number |
| `is_company` | bool | No | `True` | True for business entities |

### Returns
```
Customer created successfully. Odoo ID: {id}. Name: {name}
```
Or if duplicate found:
```
Customer already exists. Odoo ID: {existing_id}. Name: {name}
```

### Errors
| Condition | Response |
|-----------|----------|
| Empty name | `"Error: Customer name is required."` |
| Rate limit exceeded | `"Rejected: Rate limit exceeded (20 write ops/hour). Next slot in {N} seconds."` |
| Odoo fault | `"Error creating customer: {fault_string}"` |
| DEV_MODE | `"[DEV_MODE] Customer creation simulated. Mock ID: 9999. Name: {name}"` |

---

## Tool: `get_account_balance`

**User Story**: US1 (P1) — Query Financial Data
**HITL Required**: No
**Rate Limited**: No
**DEV_MODE**: Returns mock balance

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `account_id` | int | Yes | — | Odoo account.account record ID |

### Returns
```
Account: {code} — {name}
Balance: {amount} {currency}
(Debit: {debit} | Credit: {credit})
As of: {timestamp}
```

### Errors
| Condition | Response |
|-----------|----------|
| Account not found | `"Error: Account ID {id} not found."` |
| Odoo unreachable | `"Error: Odoo server unreachable — {detail}"` |

---

## Tool: `list_transactions`

**User Story**: US1 (P1) — Query Financial Data
**HITL Required**: No
**Rate Limited**: No
**DEV_MODE**: Returns mock transactions

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `date_from` | str | No | 30 days ago | Start date `YYYY-MM-DD` |
| `date_to` | str | No | today | End date `YYYY-MM-DD` |
| `account_id` | int | No | 0 | Filter by account ID (0 = all accounts) |
| `limit` | int | No | 50 | Max lines to return (1–200) |

### Returns
Formatted string with transaction list. Each entry includes:
- Date
- Journal entry reference
- Account code + name
- Description
- Debit / Credit amount

### Errors
| Condition | Response |
|-----------|----------|
| No transactions | `"No transactions found for the specified criteria."` |
| Invalid date format | `"Error: date_from must be YYYY-MM-DD format."` |
| Odoo unreachable | `"Error: Odoo server unreachable — {detail}"` |

---

## Tool: `create_invoice`

**User Story**: US3 (P3) — Create Invoice with Human Approval
**HITL Required**: Yes — requires approval file in `vault/Approved/` with `type: odoo_invoice`
**Rate Limited**: Yes (shared 20/hour write limit)
**DEV_MODE**: Simulates creation, vault workflow still executes

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `customer_id` | int | Yes | — | Odoo partner ID |
| `invoice_date` | str | Yes | — | Date `YYYY-MM-DD` |
| `lines` | list[dict] | Yes | — | Line items: `{product_id, quantity, price_unit}` |

### Returns
```
Invoice created successfully. Odoo ID: {id}. Invoice Ref: {number}.
Approval file moved to vault/Done/.
```

### Errors
| Condition | Response |
|-----------|----------|
| No approval file | `"Rejected: No approval file found in vault/Approved/ with type: odoo_invoice. Create and approve an ODOO_INVOICE_*.md file first."` |
| Rate limit exceeded | `"Rejected: Rate limit exceeded (20 write ops/hour). Next slot in {N} seconds."` |
| Odoo fault | `"Error creating invoice: {fault_string}"` |
| DEV_MODE | `"[DEV_MODE] Invoice creation simulated. Mock Odoo ID: 9001."` |

---

## Tool: `create_payment`

**User Story**: US4 (P4) — Record Payment with Human Approval
**HITL Required**: Yes — requires approval file in `vault/Approved/` with `type: odoo_payment`
**Rate Limited**: Yes (shared 20/hour write limit)
**DEV_MODE**: Simulates creation, vault workflow still executes

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `invoice_id` | int | Yes | — | Odoo invoice ID to settle |
| `amount` | float | Yes | — | Payment amount (> 0) |
| `payment_date` | str | Yes | — | Date `YYYY-MM-DD` |
| `journal_id` | int | Yes | — | Odoo journal ID (bank/cash) |
| `memo` | str | No | `""` | Payment reference/memo |

### Pre-Condition Checks (before Odoo call)
1. Verify invoice exists and is in `posted` state
2. Verify invoice is not already `paid`
3. Verify approval file exists in `vault/Approved/`

### Returns
```
Payment registered successfully. Odoo Payment ID: {id}.
Invoice {ref} is now {payment_status}.
Approval file moved to vault/Done/.
```

### Errors
| Condition | Response |
|-----------|----------|
| No approval file | `"Rejected: No approval file found in vault/Approved/ with type: odoo_payment."` |
| Invoice already paid | `"Rejected: Invoice {ref} is already paid. No duplicate payment created."` File moved to `vault/Rejected/` with `rejection_reason: already_paid`. |
| Invoice not found | `"Error: Invoice ID {id} not found or not in posted state."` |
| Rate limit exceeded | `"Rejected: Rate limit exceeded (20 write ops/hour). Next slot in {N} seconds."` |
| Odoo fault | `"Error registering payment: {fault_string}"` |
| DEV_MODE | `"[DEV_MODE] Payment registration simulated. Mock Odoo Payment ID: 8001."` |

---

## Shared AppContext (Server Lifespan)

```python
@dataclass
class AppContext:
    client: OdooClient
    rate_limiter: OdooRateLimiter
```

**Startup**: Authenticate with Odoo (or skip in DEV_MODE), initialize rate limiter.
**Shutdown**: Log server shutdown.

---

## Audit Log Format

Every tool invocation writes an entry to `vault/Logs/actions/`:

```python
{
    "timestamp": "2026-02-22T09:00:00Z",    # ISO 8601 UTC
    "correlation_id": "uuid-v4",
    "actor": "odoo_mcp",
    "action_type": "list_invoices",          # Tool name
    "target": "account.move",                # Odoo model or "n/a"
    "result": "success",                     # success|error|dev_mode|rejected|rate_limited
    "duration_ms": 320,
    "parameters": {                          # Redacted (no amounts > $0 logged verbatim)
        "limit": 20,
        "status": "posted",
        "count": 5
    }
}
```
