# Data Model: Odoo Accounting MCP Integration

**Feature**: 006-odoo-mcp-integration
**Date**: 2026-02-22
**Phase**: 1 — Design & Contracts

---

## Overview

This feature introduces no new persistent storage beyond the vault file system. All accounting data is owned by the Odoo instance. The MCP server holds only:
1. A live XML-RPC connection (in-memory, per server process)
2. A sliding-window rate limiter (in-memory, per server process)
3. Vault Markdown files for the HITL approval workflow (file system)

---

## Domain Entities

### OdooInvoice

**Source**: `account.move` in Odoo (read via XML-RPC)
**Direction**: Read-only from MCP perspective (write via HITL)

| Field | Type | Validation | Notes |
|-------|------|-----------|-------|
| `odoo_id` | int | > 0 | Odoo record ID |
| `number` | str | non-empty | Invoice number (e.g., `INV/2026/001`) |
| `customer_name` | str | non-empty | Resolved from `partner_id[1]` |
| `customer_id` | int | > 0 | Odoo partner ID |
| `amount_total` | float | ≥ 0 | Grand total |
| `currency` | str | non-empty | Currency symbol/code |
| `invoice_date` | str | ISO date | `YYYY-MM-DD` format |
| `due_date` | str \| None | ISO date or null | `invoice_date_due` |
| `status` | str | draft\|posted\|cancel | `state` field in Odoo |
| `payment_status` | str | not_paid\|in_payment\|paid | `payment_state` field |

**State Machine**:
```
draft → posted → (not_paid → in_payment → paid)
draft → cancel
```

---

### OdooPayment

**Source**: `account.payment` in Odoo (read/write via XML-RPC)
**Direction**: Read-only query; write requires HITL approval

| Field | Type | Validation | Notes |
|-------|------|-----------|-------|
| `odoo_id` | int | > 0 | Odoo record ID |
| `amount` | float | > 0 | Payment amount |
| `currency` | str | non-empty | Currency code |
| `partner_name` | str | non-empty | Resolved from `partner_id[1]` |
| `journal` | str | non-empty | Payment journal (bank/cash) |
| `date` | str | ISO date | Payment date `YYYY-MM-DD` |
| `payment_type` | str | inbound\|outbound | Direction of payment |
| `reference` | str \| None | any | Memo/reference |
| `status` | str | draft\|posted | Payment state |

---

### OdooCustomer

**Source**: `res.partner` in Odoo (read/write via XML-RPC)
**Direction**: Read and create (no HITL required for create)

| Field | Type | Validation | Notes |
|-------|------|-----------|-------|
| `odoo_id` | int | > 0 | Odoo partner ID |
| `name` | str | non-empty, ≤ 255 chars | Display name (required for create) |
| `email` | str \| None | valid email format or null | Email address |
| `phone` | str \| None | any or null | Phone number |
| `is_company` | bool | true\|false | True for business records |
| `customer_rank` | int | ≥ 0 | > 0 means linked to invoices as customer |

**Duplicate Rule**: Before creating, search `[['name', '=ilike', name]]`. If match found, return existing record (no duplicate created).

---

### OdooAccount

**Source**: `account.account` in Odoo (read-only via XML-RPC)
**Direction**: Read-only

| Field | Type | Validation | Notes |
|-------|------|-----------|-------|
| `odoo_id` | int | > 0 | Odoo account ID |
| `code` | str | non-empty | Account code (e.g., `1000`) |
| `name` | str | non-empty | Account name (e.g., `Cash`) |
| `account_type` | str | any | `asset_cash`, `income`, etc. |
| `balance` | float | any | Computed: sum(debit) - sum(credit) |
| `currency` | str | non-empty | Currency code |

**Balance Computation**: Aggregated from `account.move.line` where `account_id = id` and `parent_state = posted`.

---

### OdooTransaction

**Source**: `account.move.line` in Odoo (read-only via XML-RPC)
**Direction**: Read-only

| Field | Type | Validation | Notes |
|-------|------|-----------|-------|
| `odoo_id` | int | > 0 | Line ID |
| `date` | str | ISO date | Entry date |
| `journal_entry` | str | non-empty | Parent entry name (e.g., `INV/2026/001`) |
| `account_code` | str | non-empty | Account code |
| `account_name` | str | non-empty | Account name |
| `description` | str \| None | any | Line description |
| `debit` | float | ≥ 0 | Debit amount (0 if credit) |
| `credit` | float | ≥ 0 | Credit amount (0 if debit) |
| `partner_name` | str \| None | any | Optional partner |

---

## Vault File Entities

### OdooInvoiceDraftFile

**Location**: `vault/Pending_Approval/ODOO_INVOICE_{YYYY-MM-DD}.md` → `vault/Approved/` → `vault/Done/` or `vault/Rejected/`

| Field | Type | Purpose |
|-------|------|---------|
| `type` | str | Always `odoo_invoice` |
| `status` | str | `pending_approval` → `approved` → `done`\|`rejected` |
| `customer_name` | str | Human-readable customer name |
| `customer_id` | int | Odoo partner ID |
| `invoice_date` | str | ISO date |
| `lines` | list | Line items: `{product, quantity, price_unit}` |
| `generated_at` | str | ISO timestamp of draft creation |
| `approved_at` | str \| None | ISO timestamp when user approved |
| `odoo_invoice_id` | int \| None | Set after successful Odoo creation |
| `odoo_invoice_ref` | str \| None | Set after successful Odoo creation |
| `completed_at` | str \| None | ISO timestamp of execution |
| `dev_mode` | bool \| None | True if executed in DEV_MODE |
| `rejection_reason` | str \| None | Set when rejected |

**State transitions**:
```
Pending_Approval (pending_approval)
    ↓ human approves (file move)
Approved (approved)
    ↓ action executor runs create_invoice
Done (done) — odoo_invoice_id set
    OR
Rejected (rejected) — rejection_reason set
```

---

### OdooPaymentDraftFile

**Location**: `vault/Pending_Approval/ODOO_PAYMENT_{YYYY-MM-DD}.md` → `vault/Approved/` → `vault/Done/` or `vault/Rejected/`

| Field | Type | Purpose |
|-------|------|---------|
| `type` | str | Always `odoo_payment` |
| `status` | str | `pending_approval` → `approved` → `done`\|`rejected` |
| `invoice_id` | int | Odoo invoice ID being settled |
| `invoice_ref` | str | Human-readable invoice reference |
| `amount` | float | Payment amount |
| `currency` | str | Currency code |
| `payment_date` | str | ISO date |
| `journal` | str | Payment journal name (bank/cash) |
| `generated_at` | str | ISO timestamp of draft creation |
| `approved_at` | str \| None | ISO timestamp when user approved |
| `odoo_payment_id` | int \| None | Set after successful Odoo creation |
| `completed_at` | str \| None | ISO timestamp of execution |
| `dev_mode` | bool \| None | True if executed in DEV_MODE |
| `rejection_reason` | str \| None | Set when rejected (e.g., `already_paid`) |

---

## In-Memory State

### OdooClient (runtime, per MCP server process)

| Attribute | Type | Purpose |
|-----------|------|---------|
| `_url` | str | Odoo base URL |
| `_db` | str | Database name |
| `_username` | str | Login username |
| `_api_key` | str | API key (not stored in logs) |
| `_uid` | int \| None | Authenticated user ID (set on authenticate()) |
| `_common` | ServerProxy | XML-RPC common endpoint proxy |
| `_models` | ServerProxy | XML-RPC object endpoint proxy |

### OdooRateLimiter (runtime, per MCP server process)

| Attribute | Type | Purpose |
|-----------|------|---------|
| `_write_timestamps` | deque[float] | Sliding window of write op timestamps |
| `max_writes` | int | Max writes per hour (default: 20) |
| `window_seconds` | int | Window size in seconds (3600) |

---

## Relationships

```
OdooInvoice ←→ OdooCustomer     (M:1 via customer_id)
OdooPayment ←→ OdooCustomer     (M:1 via partner_id)
OdooTransaction ←→ OdooAccount  (M:1 via account_id)

OdooInvoiceDraftFile → OdooInvoice   (created on execution)
OdooPaymentDraftFile → OdooPayment   (created on execution)
OdooPaymentDraftFile → OdooInvoice   (settles via invoice_id)
```
