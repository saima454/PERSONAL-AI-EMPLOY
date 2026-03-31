<!--
Sync Impact Report
==================
Version change: 0.0.0 → 1.0.0
Added sections: All (initial constitution)
Modified principles: N/A (new document)
Removed sections: N/A
Templates requiring updates:
  - .specify/templates/plan-template.md: ⚠ pending review for HITL workflow
  - .specify/templates/spec-template.md: ⚠ pending review for skill structure
  - .specify/templates/tasks-template.md: ⚠ pending review for tier progression
Follow-up TODOs: None
-->

# Personal AI Employee Constitution

## Mission Statement

Build a "Digital FTE" (Full-Time Equivalent) - an autonomous AI agent that proactively manages personal and business affairs 24/7 using Claude Code as the executor and Obsidian as the management dashboard.

## Core Principles

### I. Local-First & Privacy-Centric

All sensitive data MUST remain local within the Obsidian vault. This is non-negotiable for user trust and data sovereignty.

**Rules:**
- Credentials MUST NEVER be stored in plain text
- All secrets MUST use environment variables via `.env` files
- `.env` files MUST be in `.gitignore` and NEVER committed
- Audit logging MUST be enabled for ALL external actions
- Logs MUST be retained for minimum 90 days
- No data leaves local environment without explicit user approval

**Rationale:** Users entrust this system with sensitive personal and business data. Privacy violations would destroy trust and potentially expose users to security risks.

### II. Separation of Concerns (Perception → Reasoning → Action)

The system MUST follow a strict three-layer architecture pattern that separates data ingestion, decision-making, and action execution.

**Architecture Layers:**
1. **PERCEPTION (Watchers)**: Python scripts that monitor external sources and create `.md` files in `/vault/Needs_Action/`
2. **REASONING (Claude Code)**: Reads vault, analyzes context, creates Plans in `/vault/Plans/`, requests approvals
3. **ACTION (MCP Servers)**: Execute ONLY approved actions (send email, post content, process payments)

**Rules:**
- Watchers MUST ONLY observe and write to Inbox/Needs_Action - never execute actions
- Claude Code MUST ONLY read, reason, and write plans - never directly execute external actions
- MCP Servers MUST ONLY execute approved actions from `/vault/Approved/`
- Data flow is strictly unidirectional: Perception → Reasoning → Action

**Rationale:** Clear boundaries prevent unauthorized actions, enable auditability, and allow each layer to be tested and secured independently.

### III. Agent Skills as First-Class Citizens

ALL AI functionality MUST be implemented as Agent Skills. Skills transform Claude from a general-purpose assistant into a specialized AI Employee.

**Skill Structure:**
```
skills/
└── <skill-name>/
    ├── SKILL.md           # REQUIRED: Skill definition and instructions
    ├── examples/          # Usage examples
    └── resources/         # Supporting files
```

**SKILL.md Format (Progressive Disclosure):**
1. **Metadata**: Name, version, triggers, dependencies
2. **Body**: Instructions, decision trees, constraints
3. **Resources**: Templates, reference data, examples

**Rules:**
- Every distinct AI capability MUST be a separate skill
- Skills MUST be self-contained and independently testable
- Skills MUST declare their required permissions explicitly
- Skills MUST NOT directly call external APIs - they request actions via MCP

**Rationale:** Skills enable modular development, clear capability boundaries, and systematic expansion of the AI Employee's abilities.

### IV. Human-in-the-Loop (HITL) Safety

Sensitive actions MUST require explicit human approval through a file-based workflow. The AI Employee assists but does not replace human judgment for consequential decisions.

**Approval Workflow:**
```
/vault/Needs_Action/    → Claude creates plan
/vault/Plans/           → Plan documented
/vault/Pending_Approval/→ Awaiting human review
/vault/Approved/        → Human approved, ready for execution
/vault/Rejected/        → Human rejected, with reason
/vault/Done/            → Executed successfully
```

**NEVER Auto-Approve (Requires Human Approval):**
- Payments to NEW recipients (not in approved contacts)
- ANY payment amount > $100 USD equivalent
- Bulk sends (> 5 recipients)
- Account deletions or modifications
- Public posts on social media
- Contracts or agreements
- Any action flagged `sensitivity: high` in skill definition

**Rules:**
- Approval files MUST include: action summary, risk assessment, rollback plan
- Human approval MUST be recorded with timestamp and approval method
- Rejected actions MUST include rejection reason for learning
- Emergency override MUST require secondary confirmation

**Rationale:** Consequential actions require human judgment. The file-based workflow creates an audit trail and allows asynchronous review.

### V. Development Mode Safety

A global `DEV_MODE` flag MUST prevent real external actions during development and testing.

**DEV_MODE Behavior:**
- All external API calls MUST be mocked or logged-only
- Email/messaging actions MUST write to `/vault/Logs/dev_actions.md` instead of sending
- Payment actions MUST ALWAYS fail with clear "DEV_MODE" message
- Social media posts MUST be previewed but never published

**Rules:**
- `DEV_MODE=true` MUST be the default in all `.env.example` files
- Production deployment MUST require explicit `DEV_MODE=false`
- All scripts MUST support `--dry-run` flag regardless of DEV_MODE
- DEV_MODE status MUST be visible in Dashboard.md

**Rationale:** Development and testing must never cause real-world side effects. This protects against accidental emails, payments, or posts.

### VI. Rate Limiting & Resource Guards

All external actions MUST respect rate limits to prevent abuse, runaway processes, and API quota exhaustion.

**Default Rate Limits:**
- Email: Max 10 sends per hour
- Payments: Max 3 transactions per hour
- Social posts: Max 5 posts per platform per day
- API calls: Respect provider limits with 20% safety margin

**Rules:**
- Rate limits MUST be configurable via `/config/rate_limits.json`
- Rate limit violations MUST halt processing and alert user
- Exponential backoff MUST be used for transient failures (start 1s, max 5min)
- Circuit breaker pattern MUST be implemented for repeated failures (5 failures = 15min cooldown)

**Rationale:** Uncontrolled automation can exhaust resources, trigger API bans, or create spam. Guards protect both user and external services.

### VII. Comprehensive Logging & Auditability

Every action taken by the system MUST be logged with sufficient detail for audit and debugging.

**Log Structure:**
```
/vault/Logs/
├── actions/           # External action logs
├── decisions/         # Reasoning traces
├── errors/            # Error logs with stack traces
└── audit/             # Security-relevant events
```

**Log Entry Requirements:**
- Timestamp (ISO 8601 UTC)
- Actor (watcher name, skill name, or "system")
- Action type
- Target (recipient, account, etc.)
- Result (success/failure)
- Duration (ms)
- Correlation ID (for tracing related events)

**Rules:**
- Logs MUST be append-only (no modification of historical logs)
- Sensitive data in logs MUST be redacted (emails → `j***@example.com`)
- Log retention MUST be minimum 90 days
- Logs MUST be queryable via Obsidian search

**Rationale:** Comprehensive logging enables debugging, compliance, and trust verification. Users must be able to understand what the system did and why.

### VIII. Error Handling & Graceful Degradation

The system MUST handle errors gracefully without losing data or entering undefined states.

**Error Handling Hierarchy:**
1. **Retry**: Transient errors (network, timeout) - exponential backoff
2. **Fallback**: Use cached/default data when primary source unavailable
3. **Degrade**: Disable affected feature, continue others
4. **Alert**: Notify user of degraded state
5. **Halt**: Stop processing if data integrity at risk

**Rules:**
- All async operations MUST have timeout (default 30s, max 5min)
- Failed operations MUST be logged with full context
- Partial failures MUST NOT corrupt vault state
- Watchdog process MUST restart failed services
- System MUST be recoverable from any error state

**Rationale:** Autonomous systems must be resilient. Users cannot babysit the system, so it must handle failures intelligently.

## Technical Standards

### Python Development

- Python version: 3.13+
- Package manager: uv (NOT pip)
- Type hints: REQUIRED on all function signatures
- Async/await: REQUIRED for all I/O operations
- Docstrings: REQUIRED for public functions (Google style)

### Code Quality

- Linting: ruff (configured in pyproject.toml)
- Formatting: ruff format
- Testing: pytest with pytest-asyncio
- Coverage: Minimum 70% for core modules

### File Standards

- All vault files: Markdown (.md)
- Configuration: TOML or JSON
- Scripts: Python or PowerShell (Windows)
- Line endings: LF (even on Windows)
- Encoding: UTF-8

## Folder Structure (Canonical)

```
AI_Employee_Hackathon/
├── .claude/                    # Claude Code configuration
│   └── commands/               # Custom slash commands
├── .specify/                   # Spec-Kit Plus files
│   ├── memory/                 # Project memory (constitution, etc.)
│   └── templates/              # Document templates
├── skills/                     # Custom Agent Skills (CRITICAL)
│   └── <skill-name>/
│       ├── SKILL.md            # Skill definition
│       └── resources/          # Supporting files
├── backend/                    # Python backend services
│   ├── watchers/               # Perception layer scripts
│   ├── mcp_servers/            # Action layer (MCP)
│   ├── orchestrator/           # Main orchestration
│   └── utils/                  # Shared utilities
├── vault/                      # Obsidian Vault (LOCAL ONLY)
│   ├── Dashboard.md            # Main status dashboard
│   ├── Company_Handbook.md     # Business context
│   ├── Business_Goals.md       # Current objectives
│   ├── Inbox/                  # Raw incoming items
│   ├── Needs_Action/           # Items requiring processing
│   ├── Plans/                  # Documented plans
│   ├── Pending_Approval/       # Awaiting human approval
│   ├── Approved/               # Ready for execution
│   ├── Rejected/               # Declined with reason
│   ├── Done/                   # Completed actions
│   ├── Logs/                   # System logs
│   ├── Briefings/              # CEO briefings
│   └── Accounting/             # Financial records
├── config/                     # Configuration files
│   ├── .env.example            # Environment template
│   ├── mcp.json                # MCP server config
│   └── rate_limits.json        # Rate limiting config
├── scripts/                    # Utility scripts (PowerShell)
├── docs/                       # Documentation
├── tests/                      # Test suite
├── .gitignore
├── pyproject.toml
└── README.md
```

## Tier Progression

Development MUST follow this incremental tier system. Each tier builds upon the previous.

### Bronze Tier (8-12 hours)
**Goal:** Functional prototype with single watcher

**Deliverables:**
- [ ] Basic vault structure with all folders
- [ ] Dashboard.md with status indicators
- [ ] 1 working watcher (email recommended)
- [ ] 2-3 core skills (triage, summarize, draft-reply)
- [ ] Basic HITL workflow (manual file moves)
- [ ] DEV_MODE fully functional

**Success Criteria:** User can see incoming emails summarized in vault

### Silver Tier (20-30 hours)
**Goal:** Multi-watcher system with MCP actions

**Deliverables:**
- [ ] 2+ watchers (email + calendar or social)
- [ ] MCP server for email sending
- [ ] Automated HITL workflow
- [ ] LinkedIn integration (read)
- [ ] 5+ skills
- [ ] Rate limiting implemented
- [ ] Error recovery for watchers

**Success Criteria:** User can approve and send email replies from vault

### Gold Tier (40+ hours)
**Goal:** Full integration with business tools

**Deliverables:**
- [ ] Odoo integration (invoicing, CRM)
- [ ] Social media posting (LinkedIn, Twitter)
- [ ] Daily CEO briefing generation
- [ ] Payment processing (with strict HITL)
- [ ] 10+ skills
- [ ] Comprehensive logging
- [ ] Watchdog process management

**Success Criteria:** System can draft invoice, get approval, and send

### Platinum Tier (60+ hours)
**Goal:** Production-ready with cloud sync

**Deliverables:**
- [ ] Cloud deployment option
- [ ] Multi-device vault sync
- [ ] Mobile notifications for approvals
- [ ] Advanced analytics dashboard
- [ ] Voice command integration
- [ ] Full audit compliance

**Success Criteria:** System runs 24/7 with minimal human intervention

## Governance

### Constitution Authority
This constitution is the supreme authority for all development decisions. When conflicts arise:
1. Constitution principles override implementation convenience
2. Safety principles (HITL, DEV_MODE) are non-negotiable
3. Architectural patterns can be adapted with documented ADR

### Amendment Process
1. Propose amendment with rationale
2. Document in ADR format
3. Review impact on existing implementation
4. Version bump according to semantic versioning:
   - MAJOR: Principle removal or fundamental change
   - MINOR: New principle or significant expansion
   - PATCH: Clarification or typo fix
5. Update all affected documentation

### Compliance Verification
All code reviews MUST verify:
- [ ] Follows Perception → Reasoning → Action pattern
- [ ] Implements HITL for sensitive actions
- [ ] Respects DEV_MODE flag
- [ ] Has appropriate logging
- [ ] Handles errors gracefully
- [ ] Includes tests

**Version**: 1.0.0 | **Ratified**: 2025-02-04 | **Last Amended**: 2025-02-04
