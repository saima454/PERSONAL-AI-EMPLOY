# Tasks: Odoo Accounting MCP Integration

**Input**: Design documents from `/specs/006-odoo-mcp-integration/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/tools.md ✓, quickstart.md ✓

**Organization**: Tasks organized by user story — each story is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no competing writes)
- **[Story]**: Maps to user story (US1–US5) from spec.md
- Setup/Foundational/Polish phases have no story label

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package skeleton, config entries, environment variables — all zero-risk changes to non-Python files.

- [X] T001 Create `backend/mcp_servers/odoo/__init__.py` as empty package marker (enables `python -m backend.mcp_servers.odoo.odoo_server`)
- [X] T002 Add `"odoo": {"writes_per_hour": 20}` key to the root object in `config/rate_limits.json` (alongside existing `"email"`, `"payments"`, `"social"`, `"api_calls"` keys)
- [X] T003 [P] Update `config/.env.example` ODOO section (lines 144–147): fill in descriptive comments and example values — `ODOO_URL=http://localhost:8069`, `ODOO_DATABASE=ai_employee`, `ODOO_USERNAME=admin@example.com`, `ODOO_API_KEY=your-odoo-api-key-here` (generated in Odoo Settings → Technical → API Keys)
- [X] T004 [P] Add `"odoo"` entry to `config/mcp.json` inside `"mcpServers"` — `command: "uv"`, `args: ["run", "python", "-m", "backend.mcp_servers.odoo.odoo_server"]`, `capabilities: ["list_invoices","create_invoice","get_invoice","list_customers","create_customer","get_account_balance","list_transactions","create_payment"]`, `enabled: true`, `_comment: "Odoo accounting MCP server — Gold tier"`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that ALL user stories depend on. No US implementation can begin before this phase is complete.

**⚠️ CRITICAL**: Complete T005–T007 before starting any US phase.

- [X] T005 Create `backend/mcp_servers/odoo/odoo_client.py` with the `OdooClient` class:
  - `__init__(self, url: str, db: str, username: str, api_key: str, dev_mode: bool = False)` — store params, create two `xmlrpc.client.ServerProxy` instances: `self._common = ServerProxy(f"{url}/xmlrpc/2/common")` and `self._models = ServerProxy(f"{url}/xmlrpc/2/object")`; set `self._uid: int | None = None`
  - `authenticate(self) -> int` — if `self._dev_mode`: set `self._uid = 1`, return 1; else call `self._common.authenticate(db, username, api_key, {})`, raise `ConnectionError("Odoo authentication failed")` if result is `False`; catch `xmlrpc.client.ProtocolError` and re-raise as `ConnectionError`
  - `_execute_kw(self, model, method, args, kwargs=None)` — call `self._models.execute_kw(self._db, self._uid, self._api_key, model, method, args, kwargs or {})`; catch `xmlrpc.client.Fault` and re-raise preserving `faultString`; catch `xmlrpc.client.ProtocolError` and re-raise as `ConnectionError("Odoo unreachable")`

- [X] T006 Create `backend/mcp_servers/odoo/odoo_server.py` with the server scaffold:
  - Import: `from backend.mcp_servers.rate_limiter import RateLimiter`
  - `class OdooRateLimiter(RateLimiter)` — override `_load_config(self, config_path)` to read `data.get("odoo", {}).get("writes_per_hour", 20)` into `self.max_sends`, same `window_seconds = 3600`
  - `@dataclass class AppContext` — fields: `client: OdooClient`, `rate_limiter: OdooRateLimiter`
  - `@asynccontextmanager async def app_lifespan(_server)` — read env vars (`ODOO_URL`, `ODOO_DATABASE`, `ODOO_USERNAME`, `ODOO_API_KEY`, `DEV_MODE`, `VAULT_PATH`); create `OdooClient`; if not `DEV_MODE`: `await asyncio.to_thread(client.authenticate)`; create `OdooRateLimiter()`; log startup; yield `AppContext`; log shutdown
  - `mcp = FastMCP("odoo-mcp-server", instructions="...", lifespan=app_lifespan)`
  - `def _log_tool_action(action_type, target, result, cid, duration_ms=0, parameters=None)` — writes to `vault/Logs/actions/` via `log_action()` with `actor="odoo_mcp"` (mirrors email_server.py pattern)
  - `def main()` — `mcp.run(transport="stdio")`; `if __name__ == "__main__": main()`
  - Module-level constants: `DEV_MODE`, `VAULT_PATH` (loaded from env at import time with `load_dotenv()`)

- [X] T007 Create `backend/mcp_servers/odoo/utils.py` with vault helper functions:
  - `write_invoice_draft(vault_path: str, customer_name: str, customer_id: int, invoice_date: str, lines: list[dict]) -> Path` — write `vault/Pending_Approval/ODOO_INVOICE_{today}.md` with YAML frontmatter: `type: odoo_invoice`, `status: pending_approval`, `customer_name`, `customer_id`, `invoice_date`, `lines` (list of `{product, quantity, price_unit}`), `generated_at: now_iso()`; body is a human-readable invoice summary (customer, date, line items, estimated total); return `Path` of created file
  - `write_payment_draft(vault_path: str, invoice_id: int, invoice_ref: str, amount: float, currency: str, payment_date: str, journal: str) -> Path` — write `vault/Pending_Approval/ODOO_PAYMENT_{today}.md` with frontmatter: `type: odoo_payment`, `status: pending_approval`, `invoice_id`, `invoice_ref`, `amount`, `currency`, `payment_date`, `journal`, `generated_at: now_iso()`; return `Path`

**Checkpoint**: T005–T007 complete. OdooClient, server scaffold, and utils are ready. All US phases can begin.

---

## Phase 3: User Story 1 — Query Financial Data (Priority: P1) 🎯 MVP

**Goal**: All 5 read tools operational — no Odoo approval workflow required.

**Independent Test**: With `DEV_MODE=true`, invoke all 5 read MCP tools and receive structured mock financial data. No vault files should be created. Audit log entries appear in `vault/Logs/actions/`.

### Implementation for User Story 1

- [X] T008 [US1] Add `list_invoices(self, limit: int = 20, offset: int = 0, status: str = "posted") -> list[dict]` to `OdooClient` in `backend/mcp_servers/odoo/odoo_client.py`:
  - Build domain: `[['move_type','=','out_invoice']]`; if `status != "all"`: append `['state','=',status]` (where `"paid"` maps to `['payment_state','=','paid']`)
  - Call `self._execute_kw('account.move', 'search_read', [domain], {'fields': ['id','name','partner_id','amount_total','currency_id','invoice_date','invoice_date_due','state','payment_state'], 'limit': limit, 'offset': offset, 'order': 'invoice_date desc'})`
  - Normalize each record: extract `partner_id[1]` as `customer_name`, `currency_id[1]` as `currency`
  - DEV_MODE: return `[{"id": 1, "number": "INV/2026/001", "customer_name": "ACME Corp", "amount_total": 1500.0, "currency": "USD", "invoice_date": "2026-02-01", "status": "posted", "payment_status": "not_paid"}, {"id": 2, "number": "INV/2026/002", "customer_name": "Beta Ltd", "amount_total": 3200.0, "currency": "USD", "invoice_date": "2026-02-10", "status": "posted", "payment_status": "paid"}, {"id": 3, "number": "INV/2026/003", "customer_name": "Gamma Inc", "amount_total": 750.0, "currency": "USD", "invoice_date": "2026-02-15", "status": "posted", "payment_status": "in_payment"}]`

- [X] T009 [P] [US1] Add `get_invoice(self, invoice_id: int) -> dict` to `OdooClient` in `backend/mcp_servers/odoo/odoo_client.py`:
  - Call `self._execute_kw('account.move', 'read', [[invoice_id]], {'fields': ['id','name','partner_id','amount_total','amount_untaxed','amount_tax','currency_id','invoice_date','invoice_date_due','state','payment_state','invoice_line_ids']})`
  - If result empty: raise `ValueError(f"Invoice ID {invoice_id} not found")`
  - DEV_MODE: return hardcoded dict with `id=1, number="INV/2026/001", customer_name="ACME Corp", amount_total=1500.0, lines=[{"product": "Consulting Services", "qty": 10, "price_unit": 150.0, "subtotal": 1500.0}]`

- [X] T010 [P] [US1] Add `list_customers(self, search: str = "", limit: int = 20) -> list[dict]` to `OdooClient` in `backend/mcp_servers/odoo/odoo_client.py`:
  - Domain: if `search`: `[['name','ilike',search]]`; else: `[['customer_rank','>',0]]`
  - Call `self._execute_kw('res.partner', 'search_read', [domain], {'fields': ['id','name','email','phone','customer_rank'], 'limit': limit, 'order': 'name asc'})`
  - DEV_MODE: return `[{"id": 5, "name": "ACME Corp", "email": "billing@acme.com", "phone": "+1-555-0100", "customer_rank": 3}, {"id": 7, "name": "Beta Ltd", "email": "accounts@beta.com", "phone": "+1-555-0200", "customer_rank": 1}]`

- [X] T011 [P] [US1] Add `get_account_balance(self, account_id: int) -> dict` to `OdooClient` in `backend/mcp_servers/odoo/odoo_client.py`:
  - Read account: `self._execute_kw('account.account', 'read', [[account_id]], {'fields': ['id','code','name','account_type']})`; raise `ValueError` if empty
  - Sum journal lines: `self._execute_kw('account.move.line', 'read_group', [[['account_id','=',account_id],['parent_state','=','posted']]], {'fields': ['debit:sum','credit:sum'], 'groupby': []})`
  - Return `{"account_id": ..., "code": ..., "name": ..., "debit": ..., "credit": ..., "balance": debit - credit, "currency": "USD"}`
  - DEV_MODE: return `{"account_id": 10, "code": "1010", "name": "Bank", "debit": 45000.0, "credit": 16400.0, "balance": 28600.0, "currency": "USD"}`

- [X] T012 [P] [US1] Add `list_transactions(self, date_from: str = "", date_to: str = "", account_id: int = 0, limit: int = 50) -> list[dict]` to `OdooClient` in `backend/mcp_servers/odoo/odoo_client.py`:
  - Build domain: `[['parent_state','=','posted']]`; if `date_from`: append `['date','>=',date_from]`; if `date_to`: append `['date','<=',date_to]`; if `account_id > 0`: append `['account_id','=',account_id]`
  - Call `self._execute_kw('account.move.line', 'search_read', [domain], {'fields': ['id','date','name','account_id','move_id','debit','credit','partner_id'], 'limit': limit, 'order': 'date desc'})`
  - Normalize: extract `account_id[1]` as `account_name`, `account_id[0]` as `account_code` from `account_id` tuple, `move_id[1]` as `journal_entry`, `partner_id[1]` as `partner_name`
  - DEV_MODE: return 5 hardcoded transaction dicts with realistic accounting entries (debit/credit, dates)

- [X] T013 [US1] Register `@mcp.tool() async def list_invoices(limit: int = 20, offset: int = 0, status: str = "posted") -> str` in `backend/mcp_servers/odoo/odoo_server.py`:
  - Get `app: AppContext` from `mcp.get_context()`; create `cid = correlation_id()`; record `start = time.time()`
  - Validate `limit = max(1, min(100, limit))`; validate `status in ("draft", "posted", "paid", "all")`
  - Call `results = await asyncio.to_thread(app.client.list_invoices, limit, offset, status)`
  - Format output: "Found N invoice(s) with status '{status}':\n\n1. {number} | {customer} | ${amount} {currency} | {date} | {payment_status}\n..."
  - Call `_log_tool_action("list_invoices", "account.move", "success", cid, duration_ms, {"count": len(results), "status": status})`
  - On `ConnectionError`: log error, return `"Error: Odoo server unreachable — {detail}"`

- [X] T014 [P] [US1] Register `@mcp.tool() async def get_invoice(invoice_id: int) -> str` in `backend/mcp_servers/odoo/odoo_server.py`:
  - Call `asyncio.to_thread(app.client.get_invoice, invoice_id)`; format multi-line output with header (number, customer, dates, totals, status) and line items table; handle `ValueError` for not-found; log action

- [X] T015 [P] [US1] Register `@mcp.tool() async def list_customers(search: str = "", limit: int = 20) -> str` in `backend/mcp_servers/odoo/odoo_server.py`:
  - Call `asyncio.to_thread(app.client.list_customers, search, limit)`; format numbered list with id, name, email, phone; handle empty result; log action

- [X] T016 [P] [US1] Register `@mcp.tool() async def get_account_balance(account_id: int) -> str` in `backend/mcp_servers/odoo/odoo_server.py`:
  - Call `asyncio.to_thread(app.client.get_account_balance, account_id)`; format: "Account: {code} — {name}\nBalance: {balance} {currency}\n(Debit: {debit} | Credit: {credit})\nAs of: {timestamp}"; handle `ValueError`; log action

- [X] T017 [P] [US1] Register `@mcp.tool() async def list_transactions(date_from: str = "", date_to: str = "", account_id: int = 0, limit: int = 50) -> str` in `backend/mcp_servers/odoo/odoo_server.py`:
  - Validate date format if provided (must match `YYYY-MM-DD`); default `date_from` to 30 days ago if empty; call `asyncio.to_thread(app.client.list_transactions, ...)`; format table with date, entry ref, account, description, debit, credit; log action

**Checkpoint**: All 5 read tools respond to MCP calls in DEV_MODE. Audit logs appear in vault. User Story 1 fully functional.

---

## Phase 4: User Story 2 — CEO Daily Briefing Integration (Priority: P2)

**Goal**: `get_financial_summary()` helper aggregates Odoo data; stale-data cache enables graceful degradation.

**Independent Test**: Call `get_financial_summary(client)` with DEV_MODE OdooClient — returns dict with `monthly_revenue`, `outstanding_invoices`, `recent_payments`, `account_balance`. Call with broken client — returns dict with `"error"` key and last cached values loaded from `vault/Logs/odoo_briefing_cache.json`.

### Implementation for User Story 2

- [X] T018 [US2] Add `get_financial_summary(client: OdooClient, vault_path: str) -> dict` to `backend/mcp_servers/odoo/utils.py`:
  - Collect current month `date_from` (first day of current month) and today's date
  - Call `client.list_invoices(limit=100, status="posted")` → filter records where `payment_status == "paid"` and `invoice_date` starts with current month → sum `amount_total` → `monthly_revenue`
  - From same list: filter `payment_status in ("not_paid", "in_payment")` → count and sum → `outstanding_invoices: {"count": N, "total_value": X}`
  - Call `client.list_transactions(date_from=7_days_ago, limit=200)` → filter lines where `credit > 0` on a bank/cash account → count and sum credits → `recent_payments: {"count": N, "total_value": X}`
  - Call `client.get_account_balance(account_id=1)` (use account_id=1 as default bank account; configurable via `ODOO_MAIN_ACCOUNT_ID` env var) → `account_balance` and `currency`
  - Wrap entire body in `try/except Exception` — on failure, load cache via `load_cached_summary(vault_path)`, return `{"error": "Odoo unavailable", "last_known": cached or {}, "as_of": now_iso()}`
  - On success: build result dict, call `cache_financial_summary(vault_path, result)`, return result with `"as_of": now_iso()`

- [X] T019 [US2] Add `cache_financial_summary(vault_path: str, summary: dict) -> None` and `load_cached_summary(vault_path: str) -> dict | None` to `backend/mcp_servers/odoo/utils.py`:
  - Cache path: `Path(vault_path) / "Logs" / "odoo_briefing_cache.json"`
  - `cache_financial_summary`: create parent dirs if needed; write `json.dumps({"data": summary, "cached_at": now_iso()})` to path
  - `load_cached_summary`: if path exists, read and parse JSON, return dict; on any error return `None`

**Checkpoint**: `get_financial_summary()` returns data in DEV_MODE and degrades gracefully with cached fallback when Odoo unavailable.

---

## Phase 5: User Story 3 — Create Invoice with Human Approval (Priority: P3)

**Goal**: Full HITL workflow for invoice creation — draft → Pending_Approval → Approved → Done (or Rejected).

**Independent Test**: Place `vault/Approved/ODOO_INVOICE_test.md` with `type: odoo_invoice, status: approved` frontmatter and valid `customer_id`, `invoice_date`, `lines` fields. Call `create_invoice` MCP tool. In DEV_MODE: file moves to `vault/Done/` with `status: done, dev_mode: true, odoo_invoice_id: 9001`. In DEV_MODE with no approval file: tool returns rejection message, no file movement.

### Implementation for User Story 3

- [X] T020 [US3] Add `create_invoice(self, customer_id: int, invoice_date: str, lines: list[dict]) -> tuple[int, str]` to `OdooClient` in `backend/mcp_servers/odoo/odoo_client.py`:
  - DEV_MODE: log `[DEV_MODE] Simulating invoice creation`, return `(9001, "DEV/2026/001")`
  - Build `invoice_line_ids`: `[(0, 0, {"name": line.get("product", "Service"), "quantity": line["quantity"], "price_unit": line["price_unit"]}) for line in lines]`
  - Call `self._execute_kw('account.move', 'create', [{"move_type": "out_invoice", "partner_id": customer_id, "invoice_date": invoice_date, "invoice_line_ids": invoice_line_ids}])` → returns `invoice_id`
  - Post the invoice: `self._execute_kw('account.move', 'action_post', [[invoice_id]], {})` — posts draft to confirmed state
  - Read back the invoice number: `self._execute_kw('account.move', 'read', [[invoice_id]], {'fields': ['name']})` → `invoice_ref = result[0]["name"]`
  - Return `(invoice_id, invoice_ref)`

- [X] T021 [US3] Register `@mcp.tool() async def create_invoice(customer_id: int, invoice_date: str, lines: list[dict]) -> str` in `backend/mcp_servers/odoo/odoo_server.py`:
  - Approval check: `approval = find_approval(VAULT_PATH, "odoo_invoice")`; if `None`: log rejected, return rejection message with instructions to create `ODOO_INVOICE_*.md` file
  - Rate limit check: `allowed, wait = app.rate_limiter.check()`; if not allowed: log rate_limited, return rate limit message (do NOT consume approval)
  - Execute: `invoice_id, invoice_ref = await asyncio.to_thread(app.client.create_invoice, customer_id, invoice_date, lines)`
  - On success: call `app.rate_limiter.record_send()`, update approval file frontmatter with `{"status": "done", "odoo_invoice_id": invoice_id, "odoo_invoice_ref": invoice_ref, "dev_mode": DEV_MODE}`, call `consume_approval(approval["path"], VAULT_PATH)`, log success, return success message
  - On `xmlrpc.client.Fault as e`: call `_reject_approval_file(approval["path"], e.faultString)`, log error, return error message

- [X] T022 [US3] Add `_reject_approval_file(file_path: Path, reason: str) -> None` helper to `backend/mcp_servers/odoo/odoo_server.py`:
  - Update frontmatter: `update_frontmatter(file_path, {"status": "rejected", "rejection_reason": reason[:200], "rejected_at": now_iso()})`
  - Move file to `vault/Rejected/`: `shutil.move(str(file_path), str(Path(VAULT_PATH) / "Rejected" / file_path.name))`
  - Log the rejection; import `shutil` at top of file

**Checkpoint**: Full invoice HITL lifecycle works in DEV_MODE: approval file → Done with Odoo ID.

---

## Phase 6: User Story 4 — Record Payment with Human Approval (Priority: P4)

**Goal**: Full HITL workflow for payment recording — HITL gate, pre-condition check (already paid), approve and register in Odoo.

**Independent Test**: Place `vault/Approved/ODOO_PAYMENT_test.md` with `type: odoo_payment, status: approved`, `invoice_id: 1`, `amount: 1500.0`, `payment_date: 2026-02-22`, `journal: bank`. Call `create_payment` tool in DEV_MODE. File moves to `vault/Done/` with `status: done, dev_mode: true, odoo_payment_id: 8001`. Test already-paid scenario: OdooClient raises `ValueError("already_paid")` → file moves to `vault/Rejected/` with `rejection_reason: already_paid`.

### Implementation for User Story 4

- [X] T023 [US4] Add `create_payment(self, invoice_id: int, amount: float, payment_date: str, journal_id: int, memo: str = "") -> int` to `OdooClient` in `backend/mcp_servers/odoo/odoo_client.py`:
  - DEV_MODE: log `[DEV_MODE] Simulating payment creation`, return `8001`
  - Pre-condition: read invoice: `self._execute_kw('account.move', 'read', [[invoice_id]], {'fields': ['payment_state','partner_id','name']})`; if empty: raise `ValueError(f"Invoice {invoice_id} not found")`; if `payment_state == 'paid'`: raise `ValueError("already_paid")`
  - Create payment: `self._execute_kw('account.payment', 'create', [{"payment_type": "inbound", "partner_id": invoice["partner_id"][0], "amount": amount, "date": payment_date, "journal_id": journal_id, "ref": memo or invoice["name"]}])` → returns `payment_id`
  - Post payment: `self._execute_kw('account.payment', 'action_post', [[payment_id]], {})`
  - Return `payment_id`

- [X] T024 [US4] Register `@mcp.tool() async def create_payment(invoice_id: int, amount: float, payment_date: str, journal_id: int, memo: str = "") -> str` in `backend/mcp_servers/odoo/odoo_server.py`:
  - Validate `amount > 0`; if not: return `"Error: Payment amount must be greater than 0."`
  - Approval check: `find_approval(VAULT_PATH, "odoo_payment")`; if None: return rejection message
  - Rate limit check: if over limit: return rate limit message (do NOT consume approval)
  - Execute: `payment_id = await asyncio.to_thread(app.client.create_payment, invoice_id, amount, payment_date, journal_id, memo)`
  - On success: call `app.rate_limiter.record_send()`, update approval frontmatter with `{"status": "done", "odoo_payment_id": payment_id, "dev_mode": DEV_MODE}`, call `consume_approval(...)`, log success, return success message
  - On `ValueError("already_paid")`: call `_reject_approval_file(approval["path"], "already_paid")`, return `"Rejected: Invoice is already fully paid. No duplicate payment created."`
  - On `ValueError` (other): call `_reject_approval_file(...)`, return error message
  - On `xmlrpc.client.Fault`: call `_reject_approval_file(...)`, return error message

- [X] T025 [US4] Add `from backend.utils.frontmatter import update_frontmatter` import and `import shutil` to `backend/mcp_servers/odoo/odoo_server.py` if not already present; verify `_reject_approval_file` correctly handles `vault/Rejected/` directory creation (`Path.mkdir(parents=True, exist_ok=True)`) and file naming conflicts (append `_{timestamp}` suffix if file already exists at destination)

**Checkpoint**: Payment HITL lifecycle works in DEV_MODE. Already-paid scenario correctly moves file to Rejected/.

---

## Phase 7: User Story 5 — Create Customer Record (Priority: P5)

**Goal**: `create_customer` tool creates Odoo partner records; duplicate detection prevents duplicate entries.

**Independent Test**: Call `create_customer(name="NewCorp", email="billing@newcorp.com")` in DEV_MODE → returns mock ID 9999, no Odoo call. Call `create_customer` twice with same name in live mode → second call returns existing ID with "already exists" message, not a new record.

### Implementation for User Story 5

- [X] T026 [US5] Add `create_customer(self, name: str, email: str = "", phone: str = "", is_company: bool = True) -> tuple[int, bool]` to `OdooClient` in `backend/mcp_servers/odoo/odoo_client.py`:
  - DEV_MODE: return `(9999, True)` (simulated create, no API call)
  - Duplicate check: `existing = self._execute_kw('res.partner', 'search_read', [[['name','=ilike',name]]], {'fields': ['id','name','email'], 'limit': 1})`; if `existing`: return `(existing[0]["id"], False)` (False = not newly created)
  - Create: `new_id = self._execute_kw('res.partner', 'create', [{"name": name, "email": email or False, "phone": phone or False, "is_company": is_company, "customer_rank": 1}])`
  - Return `(new_id, True)` (True = newly created)

- [X] T027 [US5] Register `@mcp.tool() async def create_customer(name: str, email: str = "", phone: str = "", is_company: bool = True) -> str` in `backend/mcp_servers/odoo/odoo_server.py`:
  - Validate `name` non-empty: if not name.strip(): return `"Error: Customer name is required."`
  - Rate limit check: if over limit: log rate_limited, return rate limit message
  - Execute: `customer_id, created = await asyncio.to_thread(app.client.create_customer, name, email, phone, is_company)`
  - If `created`: call `app.rate_limiter.record_send()`, log success, return `"Customer created successfully. Odoo ID: {customer_id}. Name: {name}"`
  - If not `created`: log duplicate found (do NOT record rate limit hit — no write occurred), return `"Customer already exists. Odoo ID: {customer_id}. Name: {name}"`
  - On `xmlrpc.client.Fault`: log error, return `"Error creating customer: {fault_string}"`

**Checkpoint**: create_customer responds correctly in DEV_MODE, handles duplicates gracefully, rate-limits new creates.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Tests, skill definition, E2E validation, regression — bring the implementation to production quality.

- [X] T028 [P] Create `tests/test_odoo.py` with 6 test classes targeting ≥ 40 tests:
  - **TestOdooClient** (~10 tests): `test_authenticate_dev_mode_sets_uid_1`, `test_authenticate_failure_raises_connection_error`, `test_list_invoices_dev_mode_returns_3_records`, `test_get_invoice_not_found_raises_value_error`, `test_list_customers_dev_mode_returns_2_records`, `test_get_account_balance_dev_mode`, `test_list_transactions_dev_mode_returns_5_records`, `test_create_invoice_dev_mode_returns_mock_id`, `test_create_payment_already_paid_raises_value_error`, `test_create_customer_dev_mode_returns_mock_id`
  - **TestOdooServer_Read** (~8 tests): `test_list_invoices_tool_dev_mode_returns_formatted_string`, `test_get_invoice_tool_dev_mode`, `test_list_customers_tool_dev_mode`, `test_get_account_balance_tool_dev_mode`, `test_list_transactions_tool_dev_mode`, `test_list_invoices_audit_log_called`, `test_list_invoices_connection_error_returns_error_string`, `test_list_invoices_no_results_message`
  - **TestOdooServer_Write** (~10 tests): `test_create_invoice_no_approval_returns_rejection`, `test_create_invoice_with_approval_dev_mode_success`, `test_create_invoice_rate_limited_does_not_consume_approval`, `test_create_invoice_odoo_fault_moves_to_rejected`, `test_create_payment_no_approval_returns_rejection`, `test_create_payment_already_paid_moves_to_rejected`, `test_create_payment_dev_mode_success`, `test_create_customer_success_dev_mode`, `test_create_customer_duplicate_no_rate_limit_hit`, `test_create_customer_empty_name_returns_error`
  - **TestOdooRateLimiter** (~5 tests): `test_reads_odoo_writes_per_hour_from_config`, `test_allows_under_limit`, `test_rejects_at_limit`, `test_window_expiry_resets_count`, `test_default_limit_20_when_config_missing`
  - **TestOdooUtils** (~8 tests): `test_write_invoice_draft_creates_file_in_pending_approval`, `test_write_invoice_draft_frontmatter_fields`, `test_write_payment_draft_creates_file`, `test_get_financial_summary_dev_mode`, `test_get_financial_summary_on_client_error_returns_cached`, `test_cache_financial_summary_writes_json`, `test_load_cached_summary_returns_dict`, `test_load_cached_summary_returns_none_if_missing`
  - Use `unittest.mock.patch` and `MagicMock` to mock `OdooClient` methods and `mcp.get_context()` (follow email_server test pattern)

- [X] T029 Run `uv run pytest tests/test_odoo.py -v` and fix all failures until all tests pass

- [X] T030 [P] Run `uv run ruff check` and fix all linting violations (check especially: unused imports ARG, SIM105 try/except/pass, B006 mutable defaults in function signatures)

- [X] T031 Run `uv run pytest` (full regression) — fix any failures caused by new code; all previously-passing tests must continue to pass

- [X] T032 [P] Create `skills/odoo-integration/SKILL.md` documenting all 8 tools:
  - Metadata: name, version, triggers (keywords: invoice, customer, balance, payment, odoo, financial), dependencies (Odoo running, `.env` configured)
  - For each tool: what it does, parameters, HITL requirement (yes/no), DEV_MODE behavior, example invocation
  - HITL vault workflow section: diagram showing Pending_Approval → Approved → Done/Rejected for create_invoice and create_payment
  - CEO Briefing section: how to invoke get_financial_summary and format the output
  - Error handling table: 6 error types with resolution steps
  - Rate limits section: 20 write ops/hour, how to check current count

- [X] T033 E2E DEV_MODE validation:
  - Create `vault/Approved/ODOO_INVOICE_E2E_test.md` with frontmatter: `type: odoo_invoice, status: approved, customer_name: "Test Corp", customer_id: 1, invoice_date: "2026-02-22", lines: [{product: "Test Service", quantity: 1, price_unit: 100.0}], approved_at: "2026-02-22T09:00:00Z"`
  - Run `uv run python -c "from backend.mcp_servers.odoo.utils import write_invoice_draft; ..."` or execute the poster standalone to trigger the create_invoice HITL flow
  - Verify `vault/Done/ODOO_INVOICE_E2E_test.md` exists with `status: done, dev_mode: true, odoo_invoice_id: 9001`
  - Confirm all 38 tasks are marked `[X]` in this tasks.md after successful E2E validation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 ✓ — BLOCKS all user story phases
- **Phase 3 (US1)**: Depends on Phase 2 — US1 is the P1 MVP and foundation for US2
- **Phase 4 (US2)**: Depends on Phase 2 + US1 (reads US1 client methods for aggregation)
- **Phase 5 (US3)**: Depends on Phase 2 only — independent of US1/US2
- **Phase 6 (US4)**: Depends on Phase 2 + US3 (shares `_reject_approval_file` helper)
- **Phase 7 (US5)**: Depends on Phase 2 only — fully independent
- **Phase 8 (Polish)**: Depends on all US phases complete

### User Story Dependencies

- **US1 (P1)**: Start after Phase 2 — no other US dependencies
- **US2 (P2)**: Start after US1 (uses `list_invoices`, `list_transactions`, `get_account_balance`)
- **US3 (P3)**: Start after Phase 2 — independent of US1/US2
- **US4 (P4)**: Start after US3 (`_reject_approval_file` helper defined in T022)
- **US5 (P5)**: Start after Phase 2 — fully independent

### Within Each User Story

- OdooClient methods (T008–T012, T020, T023, T026) can run in parallel [P] within their story
- MCP tool registrations (T013–T017, T021, T024, T027) depend on their corresponding client methods
- Utils additions (T018–T019) depend on US1 client methods being available

### Parallel Opportunities

Within Phase 3 (US1):
```
# Parallel: all 5 OdooClient read methods
T008 list_invoices  ||  T009 get_invoice  ||  T010 list_customers  ||  T011 get_account_balance  ||  T012 list_transactions

# Sequential: MCP tools depend on client methods
→ T013 list_invoices tool (depends on T008)
   T014 get_invoice tool  ||  T015 list_customers tool  ||  T016 balance tool  ||  T017 transactions tool (each depends on its T0XX)
```

Within Phase 8 (Polish):
```
T028 create tests  ||  T032 create SKILL.md  (different files, parallel)
→ T029 run tests (depends on T028)
   T030 ruff check  (parallel with T029 after T028)
→ T031 full regression (depends on T029 + T030)
→ T033 E2E validation (depends on T031)
```

---

## Parallel Example: User Story 1

```bash
# Step 1: Add all 5 OdooClient read methods simultaneously (different regions of same file)
T008: Add list_invoices() to odoo_client.py
T009: Add get_invoice() to odoo_client.py
T010: Add list_customers() to odoo_client.py
T011: Add get_account_balance() to odoo_client.py
T012: Add list_transactions() to odoo_client.py

# Step 2: Register all 5 MCP tools simultaneously (different functions in odoo_server.py)
T013: @mcp.tool() list_invoices
T014: @mcp.tool() get_invoice
T015: @mcp.tool() list_customers
T016: @mcp.tool() get_account_balance
T017: @mcp.tool() list_transactions
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T004)
2. Complete Phase 2: Foundational (T005–T007) — **CRITICAL BLOCKER**
3. Complete Phase 3: US1 — Query Financial Data (T008–T017)
4. **STOP AND VALIDATE**: `uv run python -m backend.mcp_servers.odoo.odoo_server` starts; all 5 read tools return data in DEV_MODE
5. Optional demo: connect MCP server and invoke `list_invoices` from Claude Code

### Incremental Delivery

1. Setup + Foundational → OdooClient + server scaffold ready
2. US1 → 5 read tools working → **MVP!** CEO can query invoices, customers, balances
3. US2 → Financial summary for CEO briefing
4. US3 → Invoice creation with HITL approval
5. US4 → Payment registration with HITL approval
6. US5 → Customer creation (no HITL)
7. Polish → Tests, SKILL.md, E2E validation

---

## Notes

- `xmlrpc.client` is Python stdlib — zero new dependencies to install
- All write operations share a single `OdooRateLimiter` instance (20/hour combined)
- HITL tools (`create_invoice`, `create_payment`) reuse existing `find_approval()` + `consume_approval()` from `backend/mcp_servers/approval.py`
- `_reject_approval_file()` helper (T022) handles file moves to `vault/Rejected/` — reused by US4 (T025)
- DEV_MODE: OdooClient returns hardcoded data; write tools simulate success without API calls; vault file moves still execute
- Logging: all `xmlrpc.client` calls go to stderr (stdout reserved for MCP JSON-RPC) — same as email_server
- Commit after each phase checkpoint (T007, T017, T019, T022, T025, T027, T033)
