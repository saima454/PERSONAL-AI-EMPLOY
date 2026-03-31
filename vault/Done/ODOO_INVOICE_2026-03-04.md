---
type: odoo_invoice
status: done
customer_name: sid
invoice_date: '2026-03-04'
lines:
- product: Web Development
  quantity: 5
  price_unit: 30.0
approved_at: '2026-03-04T00:00:00Z'
customer_id: 11
odoo_invoice_id: 5
odoo_invoice_ref: INV/2026/00005
completed_at: '2026-03-03T21:18:34Z'
---
# Invoice Review

**Customer**: sid
**Date**: 2026-03-04

## Line Items

- Web Development x 5 @ $30.00

**Estimated Total**: $150.00

---
## How to use:
## 1. Copy this file to vault/Approved/
## 2. Rename it to ODOO_INVOICE_<date>_<name>.md
## 3. Replace all CHANGE_ME with your values
## 4. Run: uv run python -m backend.orchestrator
## 5. Customer is auto-created in Odoo if not exists
## 6. File moves to vault/Done/ when processed
