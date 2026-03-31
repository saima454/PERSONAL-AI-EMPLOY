"""Debug script to test Odoo connection and process the invoice."""

import xmlrpc.client
import sys

url = "http://localhost:8069"
db = "ai_employee"
username = "twahasiddqui11@gmail.com"
api_key = "gbch-73bs-d6uv"

# Test authentication
common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
try:
    uid = common.authenticate(db, username, api_key, {})
    print(f"Auth OK: uid={uid}")
except Exception as e:
    print(f"Auth FAILED: {e}")
    sys.exit(1)

if not uid:
    print("Auth returned False/None — credentials are wrong")
    sys.exit(1)

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

# List existing invoices
print("\n--- Existing Invoices ---")
try:
    invoices = models.execute_kw(
        db, uid, api_key, "account.move", "search_read",
        [[["move_type", "=", "out_invoice"]]],
        {"fields": ["id", "name", "partner_id", "amount_total", "state", "payment_state"], "limit": 10},
    )
    print(f"Found {len(invoices)} invoice(s)")
    for inv in invoices:
        partner = inv["partner_id"][1] if inv.get("partner_id") else "Unknown"
        print(f"  [{inv['id']}] {inv['name']} | {partner} | ${inv['amount_total']} | {inv['state']}")
except Exception as e:
    print(f"List invoices failed: {e}")

# Check customer ID 7
print("\n--- Customer Check ---")
try:
    customers = models.execute_kw(
        db, uid, api_key, "res.partner", "search_read",
        [[["id", "=", 7]]],
        {"fields": ["id", "name", "email"], "limit": 1},
    )
    if customers:
        print(f"Customer 7: {customers[0]['name']}")
    else:
        print("Customer ID 7 NOT FOUND")
except Exception as e:
    print(f"Customer check failed: {e}")

# List all partners
print("\n--- All Partners ---")
try:
    partners = models.execute_kw(
        db, uid, api_key, "res.partner", "search_read",
        [[]],
        {"fields": ["id", "name", "is_company", "customer_rank"], "limit": 30, "order": "id asc"},
    )
    for p in partners:
        print(f"  [{p['id']}] {p['name']} (company={p['is_company']}, rank={p.get('customer_rank', 0)})")
except Exception as e:
    print(f"List partners failed: {e}")

# Step 1: Create customer "Test Client Alpha" if not exists
print("\n--- Creating Customer ---")
try:
    existing = models.execute_kw(
        db, uid, api_key, "res.partner", "search_read",
        [[["name", "=ilike", "Test Client Alpha"]]],
        {"fields": ["id", "name"], "limit": 1},
    )
    if existing:
        customer_id = existing[0]["id"]
        print(f"Customer already exists: id={customer_id}")
    else:
        customer_id = models.execute_kw(
            db, uid, api_key, "res.partner", "create",
            [{"name": "Test Client Alpha", "is_company": True, "customer_rank": 1}],
        )
        print(f"Customer CREATED: id={customer_id}")
except Exception as e:
    print(f"Customer creation failed: {e}")
    sys.exit(1)

# Step 2: Create the invoice
print("\n--- Creating Invoice ---")
try:
    invoice_id = models.execute_kw(
        db, uid, api_key, "account.move", "create",
        [{
            "move_type": "out_invoice",
            "partner_id": customer_id,
            "invoice_date": "2026-02-22",
            "invoice_line_ids": [
                (0, 0, {
                    "name": "Consulting Services",
                    "quantity": 10.0,
                    "price_unit": 100.0,
                }),
            ],
        }],
    )
    print(f"Invoice CREATED: id={invoice_id}")

    # Post (confirm) the invoice
    models.execute_kw(db, uid, api_key, "account.move", "action_post", [[invoice_id]], {})
    print(f"Invoice POSTED: id={invoice_id}")

    # Read back the reference
    ref_records = models.execute_kw(
        db, uid, api_key, "account.move", "read",
        [[invoice_id]],
        {"fields": ["name", "amount_total", "state"]},
    )
    if ref_records:
        r = ref_records[0]
        print(f"Invoice ref: {r['name']} | total: ${r['amount_total']} | state: {r['state']}")

    print("\nSUCCESS — Invoice created and posted in Odoo!")
    print(f"Actual customer_id used: {customer_id}")

except xmlrpc.client.Fault as e:
    print(f"Odoo error: {e.faultString}")
except Exception as e:
    print(f"Failed: {e}")
