# Implementation Plan: Odoo Accounting MCP Integration

**Branch**: `006-odoo-mcp-integration` | **Date**: 2026-02-22 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-odoo-mcp-integration/spec.md`

## Summary

Build an MCP server that exposes 8 accounting tools backed by Odoo Community Edition via Python's standard-library `xmlrpc.client`. Read tools (5) execute immediately; write tools (3) enforce HITL approval via the existing vault file workflow. All tools are rate-limited (20 writes/hour shared), audit-logged, and support DEV_MODE. Integrates with the daily CEO briefing via a `get_financial_summary()` helper.

---

## Technical Context

**Language/Version**: Python 3.13+
**Primary Dependencies**: `xmlrpc.client` (stdlib — no new dependency), `mcp[cli]` (existing), `python-dotenv` (existing), existing `backend.mcp_servers.approval`, `backend.mcp_servers.rate_limiter`, `backend.utils.*`
**Storage**: No new storage — Odoo is the data owner; vault filesystem for HITL draft files (existing pattern)
**Testing**: pytest + pytest-asyncio (existing)
**Target Platform**: Local Python server, stdio MCP transport
**Performance Goals**: Read tools < 5s per Odoo response (SC-001); write tool approval check < 1s (local file scan)
**Constraints**: DEV_MODE=true default; rate limit 20 writes/hour; no new PyPI dependencies beyond existing ones
**Scale/Scope**: Single user, single Odoo instance; up to 200 invoices/transactions per query (paginated)

---

## Constitution Check

### Gate 1: HITL Safety (Principle IV)
- ✅ `create_invoice` — requires approval file in `vault/Approved/` with `type: odoo_invoice`
- ✅ `create_payment` — requires approval file in `vault/Approved/` with `type: odoo_payment`
- ✅ `create_customer` — lower-risk operation; HITL not required (same rationale as creating a Gmail draft)
- ✅ All HITL tools call `find_approval()` + `consume_approval()` from existing `approval.py`

### Gate 2: Privacy & Secrets (Principle I)
- ✅ `ODOO_URL`, `ODOO_DATABASE`, `ODOO_USERNAME`, `ODOO_API_KEY` in `.env` only
- ✅ `config/odoo_session/` (if added) → added to `.gitignore`
- ✅ Audit logs redact financial amounts > threshold (amounts logged as ranges, not verbatim)
- ✅ No credentials in code, test files, or committed config

### Gate 3: DEV_MODE (Principle V)
- ✅ All 8 tools check `DEV_MODE` and return mock data / simulate writes
- ✅ DEV_MODE default is `true` in `.env.example`
- ✅ HITL vault workflow (file moves) still executes in DEV_MODE for write tools

### Gate 4: Rate Limiting (Principle VI)
- ✅ Shared `OdooRateLimiter` across `create_invoice`, `create_payment`, `create_customer`
- ✅ Limit: 20 writes/hour (sliding window, same algorithm as existing RateLimiter)
- ✅ `config/rate_limits.json` extended with `odoo.writes_per_hour: 20`

### Gate 5: Audit Logging (Principle VII)
- ✅ Every tool invocation → `vault/Logs/actions/` entry via `log_action()`
- ✅ Log fields: timestamp, correlation_id, actor, action_type, target, result, duration_ms, parameters
- ✅ Sensitive values (amounts, customer names) redacted in log parameters

### Gate 6: Error Handling (Principle VIII)
- ✅ `xmlrpc.client.Fault` → caught, user-friendly message returned, full fault logged
- ✅ `xmlrpc.client.ProtocolError` → caught, "Odoo unreachable" returned
- ✅ Authentication failure → logged, clear error returned, server still starts
- ✅ CEO briefing degrades gracefully when Odoo unreachable (last-known cached values or notice)

**Constitution Check Result**: ✅ ALL GATES PASS — No violations

---

## Project Structure

### Documentation (this feature)

```text
specs/006-odoo-mcp-integration/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0: Odoo XML-RPC patterns, design decisions
├── data-model.md        # Phase 1: Entity definitions and vault file formats
├── quickstart.md        # Phase 1: Integration scenarios and test flows
├── contracts/
│   └── tools.md         # Phase 1: MCP tool contracts (8 tools)
├── checklists/
│   └── requirements.md  # Spec quality checklist (all passing)
└── tasks.md             # Phase 2 output (/sp.tasks — NOT created by /sp.plan)
```

### Source Code

```text
backend/
├── mcp_servers/
│   ├── odoo/                        # NEW: Odoo MCP server package
│   │   ├── __init__.py              # NEW: Package marker
│   │   ├── odoo_server.py           # NEW: FastMCP server + 8 tool definitions
│   │   ├── odoo_client.py           # NEW: OdooClient class (XML-RPC wrapper)
│   │   └── utils.py                 # NEW: Draft writers, financial summary helper
│   ├── approval.py                  # EXISTING: Reused (find_approval, consume_approval)
│   └── rate_limiter.py              # EXISTING: Subclassed for OdooRateLimiter
├── utils/
│   ├── logging_utils.py             # EXISTING: Reused (log_action)
│   ├── frontmatter.py               # EXISTING: Reused (update_frontmatter)
│   └── timestamps.py                # EXISTING: Reused (now_iso)

skills/
└── odoo-integration/
    └── SKILL.md                     # NEW: Skill definition (all 8 tools)

tests/
└── test_odoo.py                     # NEW: Comprehensive tests (target: 40+ tests)

config/
├── .env.example                     # MODIFIED: Complete ODOO_* section
├── mcp.json                         # MODIFIED: Add odoo server entry (enabled: true)
└── rate_limits.json                 # MODIFIED: Add odoo.writes_per_hour: 20
```

---

## Architecture Detail

### Layer 1: OdooClient (`odoo_client.py`)

Thin synchronous wrapper around `xmlrpc.client.ServerProxy`. All methods are synchronous; callers wrap with `asyncio.to_thread()`.

```python
class OdooClient:
    def __init__(self, url: str, db: str, username: str, api_key: str) -> None
    def authenticate(self) -> int                   # returns uid; raises on failure
    def list_invoices(self, limit, offset, status) -> list[dict]
    def get_invoice(self, invoice_id: int) -> dict
    def list_customers(self, search: str, limit: int) -> list[dict]
    def create_customer(self, name, email, phone, is_company) -> int
    def get_account_balance(self, account_id: int) -> dict
    def list_transactions(self, date_from, date_to, account_id, limit) -> list[dict]
    def create_invoice(self, customer_id, invoice_date, lines) -> tuple[int, str]  # (id, ref)
    def create_payment(self, invoice_id, amount, payment_date, journal_id, memo) -> int
```

**DEV_MODE**: OdooClient is instantiated normally but `authenticate()` sets `_uid = 1` (mock) and skips real network call. All `execute_kw()` calls are skipped in DEV_MODE; methods return mock data directly.

### Layer 2: OdooRateLimiter (`rate_limiter.py` subclass)

```python
class OdooRateLimiter(RateLimiter):
    """Sliding-window rate limiter for Odoo write operations."""
    # Reads from config/rate_limits.json: odoo.writes_per_hour (default: 20)
    # Shared across create_invoice, create_payment, create_customer
```

### Layer 3: odoo_server.py (FastMCP tools)

Follows `email_server.py` structure exactly:
- `AppContext` dataclass with `client: OdooClient` and `rate_limiter: OdooRateLimiter`
- `@asynccontextmanager app_lifespan` initializes both, skips auth in DEV_MODE
- 8 `@mcp.tool()` decorated async functions
- Each tool: validate inputs → DEV_MODE check → (approval check for HITL tools) → (rate limit check for write tools) → `asyncio.to_thread(client.method)` → audit log → return formatted string

### Layer 4: utils.py (Vault Helpers)

```python
def write_invoice_draft(vault_path, customer_name, customer_id, invoice_date, lines) -> Path
def write_payment_draft(vault_path, invoice_id, invoice_ref, amount, currency, payment_date, journal) -> Path
def get_financial_summary(client: OdooClient) -> dict  # aggregates 5 read calls
```

---

## Key Technical Decisions

### TD-01: stdlib xmlrpc.client over third-party libraries
- **Decision**: Use `xmlrpc.client` (Python stdlib)
- **Rationale**: Zero new runtime dependencies; adequate for all 8 operations; consistent with codebase philosophy of minimal external dependencies
- **Alternatives**: ERPpeek (rejected — external dep), odoo-rpc-client (rejected — external dep)

### TD-02: Subclass existing RateLimiter
- **Decision**: `OdooRateLimiter(RateLimiter)` reads `odoo.writes_per_hour` from `rate_limits.json`
- **Rationale**: Avoids duplicating sliding-window logic; single config file for all rate limits
- **Alternatives**: New standalone class (rejected — duplication); parameter-driven base class (over-engineering)

### TD-03: HITL via existing approval.py
- **Decision**: Reuse `find_approval()` + `consume_approval()` for both HITL tools
- **Rationale**: Pattern is proven, tested, and follows vault file convention exactly
- **Alternatives**: Database-backed approval queue (rejected — violates local-first principle)

### TD-04: create_customer without HITL
- **Decision**: `create_customer` is a write operation but does not require HITL
- **Rationale**: Creating a contact record has no financial impact; no balance is affected; reversible (can be archived in Odoo); no constitution requirement for HITL on non-financial writes
- **Alternatives**: Require HITL for all writes (rejected — adds unnecessary friction for low-risk operation)

### TD-05: Mock data in OdooClient for DEV_MODE
- **Decision**: `OdooClient` methods return hardcoded mock dicts when `DEV_MODE=True`
- **Rationale**: Simplest approach — no separate mock class; tests can patch individual methods; no Odoo instance needed for development
- **Alternatives**: Separate `MockOdooClient` class (rejected — over-engineering for initial implementation)

---

## CEO Briefing Integration

The `get_financial_summary()` function in `utils.py` aggregates:
1. `list_invoices(status="posted", limit=100)` → filter for this month → sum paid amounts
2. `list_invoices(status="posted", limit=100)` → filter `not_paid` → count + sum
3. `list_transactions(date_from=7_days_ago)` → filter payment journals → count + sum
4. `get_account_balance(main_account_id)` → cash/bank balance

The CEO briefing generator (separate feature/skill) calls this function and inserts the result as a markdown section. No changes to the existing briefing generator architecture.

**Cache strategy**: Store last successful summary in `vault/Logs/odoo_briefing_cache.json` (timestamp + data). On Odoo failure, read cache and display with staleness notice.

---

## File Naming Conventions

| File Pattern | Location | Trigger |
|-------------|----------|---------|
| `ODOO_INVOICE_{YYYY-MM-DD}.md` | `vault/Pending_Approval/` | Claude generates invoice draft |
| `ODOO_INVOICE_{YYYY-MM-DD}.md` | `vault/Approved/` | Human approves |
| `ODOO_INVOICE_{YYYY-MM-DD}.md` | `vault/Done/` | Invoice created in Odoo |
| `ODOO_INVOICE_{YYYY-MM-DD}.md` | `vault/Rejected/` | Human rejects or HITL fails |
| `ODOO_PAYMENT_{YYYY-MM-DD}.md` | Same vault flow | Same pattern for payments |

---

## Complexity Tracking

No constitution violations. No complexity exceptions required.

---

## Test Coverage Plan

Target: 40+ tests across 5 test classes.

| Class | Tests | Coverage |
|-------|-------|---------|
| `TestOdooClient` | ~10 | authenticate, list_invoices, get_invoice, list_customers, create_customer, get_account_balance, list_transactions, create_invoice, create_payment, duplicate check |
| `TestOdooServer_Read` | ~8 | All 5 read tools: DEV_MODE mock, Odoo unreachable error, no results, audit log called |
| `TestOdooServer_Write` | ~10 | create_invoice/payment HITL flow: no approval → rejected, approval found → success, rate limited, DEV_MODE lifecycle |
| `TestOdooRateLimiter` | ~5 | reads config, allows under limit, rejects over limit, window expiry |
| `TestOdooUtils` | ~8 | write_invoice_draft creates file, write_payment_draft creates file, get_financial_summary aggregates correctly, graceful degradation on client error |
| `TestOdooIntegration` | ~5 | mcp.json has odoo entry, HITL file format validates, end-to-end approval workflow |
