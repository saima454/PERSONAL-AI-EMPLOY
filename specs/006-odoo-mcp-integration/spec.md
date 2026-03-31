# Feature Specification: Odoo Accounting MCP Integration

**Feature Branch**: `006-odoo-mcp-integration`
**Created**: 2026-02-21
**Status**: Draft

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Query Financial Data (Priority: P1)

As the AI Employee owner, I want to query my Odoo accounting system for invoices, customers, account balances, and transaction history through the AI Employee, so that I can access financial data without leaving my workflow or logging into Odoo directly.

**Why this priority**: Read-only financial queries are the foundation of all other accounting integrations. They carry zero financial risk, deliver immediate value for daily financial visibility, and are prerequisites for the CEO briefing feature. Without this story, no other story can function.

**Independent Test**: With the Odoo MCP server running and DEV_MODE enabled, invoke `list_invoices`, `get_invoice`, `list_customers`, `get_account_balance`, and `list_transactions` — each returns structured financial data (real from Odoo, or mocked in DEV_MODE) without triggering any write operations or approval flows.

**Acceptance Scenarios**:

1. **Given** Odoo is accessible, **When** I ask the AI Employee to list invoices, **Then** a structured list is returned with invoice number, customer name, amount, currency, date, and status (draft/posted/paid).
2. **Given** a specific invoice ID, **When** I ask the AI Employee to retrieve that invoice, **Then** full invoice details are returned including line items, tax amounts, and payment status.
3. **Given** a customer search query, **When** I ask the AI Employee to list customers, **Then** matching customer records are returned including name, email, and outstanding balance.
4. **Given** I request the account balance for an Odoo account, **When** the MCP tool executes, **Then** the current balance and currency are returned.
5. **Given** I request recent transactions, **When** the MCP tool executes, **Then** a list of journal entries is returned with date, description, debit, credit, and account.
6. **Given** DEV_MODE is enabled, **When** any read tool is invoked, **Then** realistic mock financial data is returned without connecting to the real Odoo instance.

---

### User Story 2 - CEO Daily Briefing Integration (Priority: P2)

As the AI Employee owner, I want the system to automatically include a financial snapshot from Odoo in the daily CEO briefing, so that I receive an at-a-glance summary of revenue, outstanding invoices, recent payments, and cash flow every morning without manual effort.

**Why this priority**: The CEO briefing is the primary daily touchpoint with the AI Employee. Adding Odoo financial data transforms it from a communication summary into a complete business operations dashboard, delivering the "Digital FTE" promise of proactive financial awareness.

**Independent Test**: With the Odoo MCP server configured, trigger the CEO briefing generation — the resulting `vault/Briefings/` document contains a "Financial Summary" section showing: total revenue (current month), count and value of outstanding invoices, recent payments (last 7 days), and an estimated cash position. In DEV_MODE, the section appears with mock figures.

**Acceptance Scenarios**:

1. **Given** the CEO briefing runs daily, **When** Odoo data is available, **Then** the briefing includes a Financial Summary section with: monthly revenue total, outstanding invoice count and total value, payments received in the past 7 days, and current account balance.
2. **Given** Odoo is temporarily unreachable, **When** the briefing runs, **Then** the Financial Summary section notes "Odoo data unavailable — last known values shown" and the briefing still completes with all other sections intact.
3. **Given** DEV_MODE is enabled, **When** the briefing runs, **Then** the Financial Summary section is populated with clearly labelled mock data.

---

### User Story 3 - Create Invoice with Human Approval (Priority: P3)

As the AI Employee owner, I want the AI Employee to draft a new Odoo invoice when I describe what I need to invoice, then route it through the standard HITL approval flow before it is created in Odoo, so that invoice creation is fast but never unauthorized.

**Why this priority**: Invoice creation is a financially consequential write operation. The HITL workflow ensures I review every invoice before it exists in my accounting system, while the AI handles the tedious data entry. This delivers significant time savings with zero financial risk.

**Independent Test**: Ask the AI Employee to create an invoice for a customer — an invoice draft appears in `vault/Pending_Approval/` with `type: odoo_invoice` frontmatter. After manually moving the file to `vault/Approved/`, the MCP action executor creates the invoice in Odoo (or logs the creation in DEV_MODE) and moves the file to `vault/Done/`.

**Acceptance Scenarios**:

1. **Given** I provide customer name, line items, quantities, and unit prices, **When** I ask the AI Employee to create an invoice, **Then** an invoice draft file appears in `vault/Pending_Approval/` with all details formatted for review.
2. **Given** an invoice draft is in `vault/Pending_Approval/`, **When** I approve it by moving it to `vault/Approved/`, **Then** the invoice is created in Odoo via the MCP tool and the file moves to `vault/Done/` with the Odoo invoice ID and creation timestamp.
3. **Given** an invoice draft is in `vault/Pending_Approval/`, **When** I reject it by moving it to `vault/Rejected/`, **Then** no invoice is created in Odoo and the file records the rejection.
4. **Given** DEV_MODE is enabled, **When** an approved invoice file is processed, **Then** the Odoo API call is simulated (not sent) and the Done file records `dev_mode: true`.
5. **Given** the Odoo API rate limit of 20 write operations per hour has been reached, **When** an invoice creation is attempted, **Then** the action is deferred and the user is alerted that the rate limit has been hit.

---

### User Story 4 - Record Payment with Human Approval (Priority: P4)

As the AI Employee owner, I want the AI Employee to prepare payment records in Odoo when I describe a payment received or made, then require my explicit approval before any payment entry is created, so that my financial records remain accurate and all payment entries are intentional.

**Why this priority**: Payment recording directly affects account balances and invoice settlement status. This is the highest-risk write operation in the accounting workflow; the HITL gate is non-negotiable per the constitution's payment safety rules.

**Independent Test**: Ask the AI Employee to record a payment against an invoice — a payment draft appears in `vault/Pending_Approval/` with `type: odoo_payment` frontmatter. After approving, the `create_payment` MCP tool creates the payment record in Odoo (or simulates it in DEV_MODE) and the file moves to `vault/Done/` with the Odoo payment ID.

**Acceptance Scenarios**:

1. **Given** I describe a payment (amount, currency, invoice reference, date), **When** I ask the AI Employee to record it, **Then** a payment draft appears in `vault/Pending_Approval/` with all details for review.
2. **Given** a payment draft is approved, **When** the action executor processes it, **Then** the `create_payment` MCP tool is called and the payment is registered in Odoo, settling the referenced invoice.
3. **Given** a payment draft is approved but the referenced invoice is already fully paid, **When** the tool attempts to register the payment, **Then** the operation fails gracefully with a clear error, the file moves to `vault/Rejected/` with the error reason, and no duplicate payment is created.
4. **Given** DEV_MODE is enabled, **When** a payment is processed, **Then** no real payment is registered in Odoo; the Done file records `dev_mode: true`.

---

### User Story 5 - Create Customer Record (Priority: P5)

As the AI Employee owner, I want the AI Employee to create new customer records in Odoo when I provide customer details, so that I can quickly add contacts to my accounting system during conversations without switching to Odoo manually.

**Why this priority**: Customer creation is a lower-risk write operation — it does not affect financial balances or invoice records. It rounds out the full accounting workflow and enables invoice creation for new customers in one flow.

**Independent Test**: Ask the AI Employee to create a customer with a name and email — the `create_customer` MCP tool executes immediately (no HITL required) and returns the new Odoo customer ID. In DEV_MODE, a simulated ID is returned.

**Acceptance Scenarios**:

1. **Given** I provide a customer name and email, **When** I ask the AI Employee to create the customer, **Then** the `create_customer` MCP tool creates the record in Odoo and returns the new customer ID.
2. **Given** a customer with the same name already exists in Odoo, **When** a create request is made, **Then** the tool returns the existing customer's details and a note that no duplicate was created.
3. **Given** DEV_MODE is enabled, **When** a customer creation is requested, **Then** a simulated customer ID is returned without writing to Odoo.

---

### Edge Cases

- What happens when the Odoo server is unreachable during a write operation that has already been approved — does the file stay in `vault/Approved/` for retry?
- How does the system handle Odoo XML-RPC authentication token expiration mid-session?
- What if a listed invoice was deleted in Odoo between `list_invoices` and `get_invoice` calls?
- What happens when 20 write operations per hour are exhausted — are queued actions held and retried, or rejected with a user alert?
- What if `create_payment` is called with an amount exceeding the invoice balance (overpayment)?

## Requirements *(mandatory)*

### Functional Requirements

**Read Operations — Financial Data Access (US1)**

- **FR-001**: The system MUST expose a `list_invoices` tool that returns a filtered, paginated list of Odoo invoices; each record MUST include invoice number, customer name, total amount, currency, invoice date, due date, and payment status.
- **FR-002**: The system MUST expose a `get_invoice` tool that returns full details for a single invoice by ID or number, including line items, tax amounts, subtotal, and any recorded payments.
- **FR-003**: The system MUST expose a `list_customers` tool that returns customer records matching an optional search term; each record MUST include customer ID, name, email, phone, and outstanding balance.
- **FR-004**: The system MUST expose a `get_account_balance` tool that returns the current debit/credit balance for a specified Odoo account, along with currency.
- **FR-005**: The system MUST expose a `list_transactions` tool that returns journal entries for a specified date range; each entry MUST include date, journal name, description, debit amount, credit amount, and account name.
- **FR-006**: All read tools MUST operate without any approval workflow — they execute immediately upon request.
- **FR-007**: When `DEV_MODE=true`, all read tools MUST return realistic mock financial data without connecting to the Odoo instance.

**CEO Briefing Integration (US2)**

- **FR-008**: The system MUST provide financial summary data — total revenue for the current month, outstanding invoice count and total value, payments received in the past 7 days, and current account balance — for inclusion in the daily CEO briefing.
- **FR-009**: If Odoo is unreachable when the briefing runs, the financial section MUST degrade gracefully by displaying the last cached values with a timestamp and an unavailability notice; the briefing MUST still complete.

**Invoice Creation with HITL (US3)**

- **FR-010**: The system MUST expose a `create_invoice` tool that is exclusively triggered via the HITL vault workflow — it MUST NEVER execute without a corresponding file in `vault/Approved/` with `type: odoo_invoice`.
- **FR-011**: When triggered, `create_invoice` MUST create the invoice in Odoo with the customer, line items, quantities, prices, and tax codes specified in the approval file.
- **FR-012**: On successful creation, the system MUST record the Odoo invoice ID and creation timestamp in the vault Done file and move it from `vault/Approved/` to `vault/Done/`.
- **FR-013**: When `DEV_MODE=true`, `create_invoice` MUST simulate the Odoo API call without creating a real invoice, recording `dev_mode: true` in the Done file.

**Payment Recording with HITL (US4)**

- **FR-014**: The system MUST expose a `create_payment` tool that is exclusively triggered via the HITL vault workflow — it MUST NEVER execute without a corresponding file in `vault/Approved/` with `type: odoo_payment`.
- **FR-015**: When triggered, `create_payment` MUST register the payment in Odoo against the referenced invoice with the specified amount, currency, payment date, and payment method.
- **FR-016**: On successful payment registration, the system MUST record the Odoo payment ID in the vault Done file and move it to `vault/Done/`.
- **FR-017**: If the referenced invoice is already fully paid, `create_payment` MUST abort without creating a duplicate payment, move the file to `vault/Rejected/`, and record the rejection reason.
- **FR-018**: When `DEV_MODE=true`, `create_payment` MUST simulate the Odoo API call without registering a real payment, recording `dev_mode: true` in the Done file.

**Customer Record Creation (US5)**

- **FR-019**: The system MUST expose a `create_customer` tool that creates a new customer record in Odoo with at minimum: name and email address.
- **FR-020**: Before creating a customer, the system MUST check whether a customer with the same name already exists in Odoo; if a match is found, it MUST return the existing record rather than creating a duplicate.
- **FR-021**: When `DEV_MODE=true`, `create_customer` MUST simulate the creation and return a mock customer ID.

**Cross-Cutting: Rate Limiting & Audit Logging**

- **FR-022**: All write tools (`create_invoice`, `create_payment`, `create_customer`) MUST be subject to a shared rate limit of 20 operations per hour; exceeding this limit MUST halt execution and alert the user.
- **FR-023**: Every tool invocation MUST produce an audit log entry recording: timestamp (ISO 8601 UTC), tool name, input parameters (with sensitive values redacted), result status (success/failure), and Odoo response.
- **FR-024**: Odoo credentials (URL, database name, username, password/API key) MUST be stored exclusively in `.env` and MUST NEVER be hardcoded or committed to version control.
- **FR-025**: A skill definition MUST exist at `skills/odoo-integration/SKILL.md` documenting all 8 tools, their triggers, HITL requirements, DEV_MODE behavior, and CEO briefing integration.

### Key Entities

- **OdooInvoice**: A receivable or payable document in Odoo; attributes: invoice number, customer/vendor name, line items (product, quantity, unit price, tax), subtotal, tax total, grand total, currency, invoice date, due date, payment status, Odoo record ID.
- **OdooPayment**: A payment record settling an invoice; attributes: amount, currency, payment date, payment method, invoice reference, Odoo record ID.
- **OdooCustomer**: A business contact (res.partner) in Odoo; attributes: name, email, phone, street address, Odoo partner ID, outstanding receivable balance.
- **OdooAccountBalance**: A point-in-time balance for a chart-of-accounts entry; attributes: account code, account name, debit total, credit total, net balance, currency.
- **OdooTransaction**: A journal entry line item; attributes: date, journal name, description, debit amount, credit amount, account name, account code.
- **OdooInvoiceDraftFile**: A vault Markdown file (`type: odoo_invoice`) flowing through Pending_Approval → Approved → Done or Rejected; carries invoice details for HITL review.
- **OdooPaymentDraftFile**: A vault Markdown file (`type: odoo_payment`) flowing through Pending_Approval → Approved → Done or Rejected; carries payment details for HITL review.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 5 read tools (`list_invoices`, `get_invoice`, `list_customers`, `get_account_balance`, `list_transactions`) return structured results within 5 seconds under normal Odoo load.
- **SC-002**: The daily CEO briefing includes an accurate financial summary (revenue, outstanding invoices, recent payments, account balance) populated from Odoo data with zero manual intervention.
- **SC-003**: If Odoo is unreachable, the CEO briefing completes successfully with a graceful degradation notice — zero briefing failures attributable to Odoo connectivity issues.
- **SC-004**: 100% of `create_invoice` and `create_payment` executions are preceded by a file in `vault/Approved/` — zero unauthorized write operations occur.
- **SC-005**: The write operation rate limit is enforced: no more than 20 `create_*` tool calls succeed per hour across all write tools combined.
- **SC-006**: 100% of tool invocations produce an audit log entry with the required fields (timestamp, tool, status, redacted inputs).
- **SC-007**: In DEV_MODE, all 8 tools complete their full workflows (including file moves for HITL tools) without sending any requests to the live Odoo instance.
- **SC-008**: Test suite covers: all 8 tool invocations (real and mocked), HITL file-move workflow for invoice and payment, rate limit enforcement, duplicate customer detection, DEV_MODE lifecycle for all write tools, and audit log entry creation.

## Assumptions

- Odoo Community Edition is running locally at `http://localhost:8069` with the database named `ai_employee` and is accessible from the development machine at all times during use.
- Odoo user credentials (username and password or API key) with sufficient accounting permissions are available and stored in `.env`.
- The Odoo `account.move`, `account.payment`, `res.partner`, `account.account`, and `account.move.line` models are accessible via the standard Odoo XML-RPC interface using the configured credentials.
- `create_customer` is treated as a lower-risk write operation and does not require the full HITL approval workflow; the creator confirms intent by making the request explicitly.
- The rate limit of 20 write operations per hour applies to the combined total of `create_invoice`, `create_payment`, and `create_customer` calls.
- The CEO briefing generation capability already exists (from a prior or concurrent feature); this feature adds a Financial Summary section to its output.
- For DEV_MODE, mock data representing realistic invoices, customers, balances, and transactions is sufficient; no sandbox Odoo instance is required.

## Scope

### In Scope

- MCP server exposing 8 tools: `list_invoices`, `create_invoice` (HITL), `get_invoice`, `list_customers`, `create_customer`, `get_account_balance`, `list_transactions`, `create_payment` (HITL)
- HITL vault workflow for `create_invoice` and `create_payment` (Pending_Approval → Approved → Done/Rejected)
- CEO Briefing financial summary section integration
- Rate limiting (20 write ops/hour) for all write tools
- Audit logging for all tool invocations
- DEV_MODE support for all 8 tools
- Odoo credential management via `.env`
- `skills/odoo-integration/SKILL.md` skill definition

### Out of Scope

- Odoo CRM module (contacts beyond accounting context)
- Purchase orders, stock management, or inventory tracking
- Odoo payroll or HR module integration
- Multi-company or multi-currency conversion logic
- Odoo reporting generation or custom report creation
- Webhook-based real-time Odoo event monitoring (polling only)
- Mobile notifications for approval requests
- Integration with any Odoo version other than Community Edition
