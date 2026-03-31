---
type: odoo_invoice
status: approved
customer_name: CHANGE_ME
invoice_date: 'CHANGE_ME'
lines:
- product: CHANGE_ME
  quantity: 1
  price_unit: 0.0
approved_at: 'CHANGE_ME'
---
# Invoice Review

**Customer**: CHANGE_ME
**Date**: CHANGE_ME

## Line Items

- CHANGE_ME x 1 @ $0.00

**Estimated Total**: $0.00

---
## How to use:
## 1. Copy this file to vault/Approved/
## 2. Rename it to ODOO_INVOICE_<date>_<name>.md
## 3. Replace all CHANGE_ME with your values
## 4. Run: uv run python -m backend.orchestrator
## 5. Customer is auto-created in Odoo if not exists
## 6. File moves to vault/Done/ when processed
