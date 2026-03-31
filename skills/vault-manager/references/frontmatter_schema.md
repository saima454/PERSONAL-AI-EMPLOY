# Frontmatter Schema Reference

This document defines the YAML frontmatter schemas for all file types in the Personal AI Employee vault.

## Overview

Every markdown file in the vault MUST have valid YAML frontmatter. The schema varies based on the file's location in the workflow.

## Schema Definitions

---

### 1. Action File Schema

**Location:** `vault/Inbox/`, `vault/Needs_Action/`

**Purpose:** Items that need processing by the AI Employee

```yaml
---
# === REQUIRED FIELDS ===
type: email | whatsapp | calendar | file | task | payment | social | other
source: gmail_watcher | whatsapp_watcher | calendar_watcher | manual | <skill-name>
created: 2025-02-04T14:30:22Z    # ISO 8601 UTC
priority: high | medium | low
status: pending | needs_action | in_progress

# === CONDITIONAL FIELDS ===
# Required when type is: email, whatsapp, calendar
from: "sender@example.com"

# Required when type is: email, calendar
subject: "Meeting Request: Q1 Planning"

# Required when type is: email, whatsapp
received: 2025-02-04T14:25:00Z   # When the original item was received

# === OPTIONAL FIELDS ===
id: email-20250204T143022        # Auto-generated: {type}-{timestamp}
tags: [client, urgent, followup]
related: [other-file.md]
due: 2025-02-05T17:00:00Z        # Deadline if applicable
---
```

**Validation Rules:**
- `type` must be one of the allowed values
- `created` must be valid ISO 8601 format
- `from` is required if type is email, whatsapp, or calendar
- `subject` is required if type is email or calendar
- `received` is required if type is email or whatsapp

**Example - Email Action:**
```yaml
---
type: email
source: gmail_watcher
from: john.client@company.com
subject: Contract Review Request
received: 2025-02-04T09:15:00Z
created: 2025-02-04T09:16:00Z
priority: high
status: needs_action
tags: [contract, client, urgent]
---
```

**Example - Manual Task:**
```yaml
---
type: task
source: manual
created: 2025-02-04T14:30:00Z
priority: medium
status: needs_action
tags: [followup]
due: 2025-02-05T12:00:00Z
---
```

---

### 2. Plan File Schema

**Location:** `vault/Plans/`, `vault/Pending_Approval/`, `vault/Approved/`

**Purpose:** Documented action plans created by the AI Employee

```yaml
---
# === REQUIRED FIELDS ===
created: 2025-02-04T14:30:22Z    # When plan was created
status: draft | pending_approval | approved | in_progress
objective: "Reply to client contract inquiry with standard terms"

# === REQUIRED FOR APPROVAL WORKFLOW ===
action_summary: "Send email reply with contract attachment"
requires_approval: true | false
sensitivity: low | medium | high

# === OPTIONAL FIELDS ===
source_file: "email-contract-inquiry-20250204.md"  # Original action file
risk_assessment: "Low risk - standard response"
rollback_plan: "Send correction email if needed"

# === APPROVAL FIELDS (added when approved) ===
approved_at: 2025-02-04T15:00:00Z
approved_by: human              # Always "human" for now

# === REJECTION FIELDS (added when rejected) ===
rejection_reason: "Need to customize terms for this client"
---
```

**Validation Rules:**
- `requires_approval` determines workflow path
- If `sensitivity: high`, `requires_approval` MUST be true
- `approved_at` and `approved_by` added only when status becomes `approved`

**Example - Plan Requiring Approval:**
```yaml
---
created: 2025-02-04T14:35:00Z
status: pending_approval
objective: "Reply to client with contract terms"
action_summary: "Send email with standard contract PDF attached"
requires_approval: true
sensitivity: medium
source_file: "email-contract-inquiry-20250204T091500.md"
risk_assessment: "Standard response, low risk of issues"
rollback_plan: "Send follow-up correction if terms incorrect"
---
```

**Example - Auto-Approved Plan:**
```yaml
---
created: 2025-02-04T14:35:00Z
status: approved
objective: "Archive newsletter email"
action_summary: "Move newsletter to archive folder"
requires_approval: false
sensitivity: low
source_file: "email-newsletter-20250204T080000.md"
---
```

---

### 3. Done File Schema

**Location:** `vault/Done/`

**Purpose:** Successfully completed actions

```yaml
---
# === INHERITED FROM PLAN ===
created: 2025-02-04T14:35:00Z
status: done
objective: "Reply to client with contract terms"
action_summary: "Send email with standard contract PDF attached"
requires_approval: true
sensitivity: medium
source_file: "email-contract-inquiry-20250204T091500.md"
approved_at: 2025-02-04T15:00:00Z
approved_by: human

# === COMPLETION FIELDS (required) ===
completed_at: 2025-02-04T15:05:00Z
result: success | partial | failed

# === OPTIONAL COMPLETION FIELDS ===
execution_log: "vault/Logs/actions/2025-02-04.json#correlation-id-123"
outcome_summary: "Email sent successfully to john.client@company.com"
---
```

**Validation Rules:**
- `completed_at` is required
- `result` is required
- If `result: failed`, should have explanation in body

**Example:**
```yaml
---
created: 2025-02-04T14:35:00Z
status: done
objective: "Reply to client with contract terms"
action_summary: "Send email with standard contract PDF attached"
requires_approval: true
sensitivity: medium
approved_at: 2025-02-04T15:00:00Z
approved_by: human
completed_at: 2025-02-04T15:05:23Z
result: success
execution_log: "vault/Logs/actions/2025-02-04.json#abc-123-def"
outcome_summary: "Email delivered to john.client@company.com at 15:05 UTC"
---
```

---

### 4. Rejected File Schema

**Location:** `vault/Rejected/`

**Purpose:** Plans that were rejected by human review

```yaml
---
# === INHERITED FROM PLAN ===
created: 2025-02-04T14:35:00Z
status: rejected
objective: "Reply to client with contract terms"
action_summary: "Send email with standard contract PDF attached"
requires_approval: true
sensitivity: medium
source_file: "email-contract-inquiry-20250204T091500.md"

# === REJECTION FIELDS (required) ===
rejected_at: 2025-02-04T15:00:00Z
rejection_reason: "Client requires custom terms, not standard contract"

# === OPTIONAL ===
rejected_by: human
---
```

**Validation Rules:**
- `rejected_at` is required
- `rejection_reason` is required and must be non-empty
- Rejection reason helps AI learn and improve future plans

**Example:**
```yaml
---
created: 2025-02-04T14:35:00Z
status: rejected
objective: "Send bulk newsletter to 50 contacts"
action_summary: "Email blast to contact list"
requires_approval: true
sensitivity: high
rejected_at: 2025-02-04T15:10:00Z
rejected_by: human
rejection_reason: "Too many recipients. Need to segment list and send in batches of 10."
---
```

---

### 5. Log Entry Schema (JSON)

**Location:** `vault/Logs/{actions,decisions,errors,audit}/YYYY-MM-DD.json`

**Purpose:** Audit trail for all system actions

```json
{
  "timestamp": "2025-02-04T14:30:22Z",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "actor": "vault-manager",
  "action_type": "file_move",
  "target": "vault/Needs_Action/email-client-20250204.md",
  "parameters": {
    "from_folder": "Inbox",
    "to_folder": "Needs_Action",
    "reason": "Triaged as high priority client email"
  },
  "result": "success",
  "duration_ms": 45,
  "error": null
}
```

**Required Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO 8601 | When action occurred |
| `correlation_id` | UUID v4 | For tracing related events |
| `actor` | string | Who performed the action |
| `action_type` | enum | Type of action |
| `target` | string | File path or identifier |
| `result` | enum | success \| failure |

**Optional Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `parameters` | object | Additional context |
| `duration_ms` | number | Execution time |
| `error` | string | Error message if failure |

**Allowed Actors:**
- `vault-manager` - This skill
- `gmail_watcher` - Email watcher
- `whatsapp_watcher` - WhatsApp watcher
- `calendar_watcher` - Calendar watcher
- `claude_code` - Direct Claude Code action
- `human` - Manual user action
- `mcp_email` - Email MCP server
- `system` - System-level operations

**Allowed Action Types:**
- `file_create` - New file created
- `file_move` - File moved between folders
- `file_update` - File content modified
- `file_delete` - File deleted
- `dashboard_update` - Dashboard.md refreshed
- `external_action` - MCP server executed action
- `error` - Error occurred

**Log File Structure:**
```json
{
  "date": "2025-02-04",
  "entries": [
    { "timestamp": "...", "actor": "...", ... },
    { "timestamp": "...", "actor": "...", ... }
  ]
}
```

---

## File Naming Conventions

| Folder | Pattern | Example |
|--------|---------|---------|
| Inbox/ | `{source}-{type}-{timestamp}.md` | `gmail_watcher-email-20250204T143022.md` |
| Needs_Action/ | `{type}-{short-desc}-{timestamp}.md` | `email-client-inquiry-20250204T143022.md` |
| Plans/ | `plan-{objective-slug}-{timestamp}.md` | `plan-reply-client-20250204T150000.md` |
| Pending_Approval/ | Same as Plans/ | `plan-reply-client-20250204T150000.md` |
| Approved/ | Same as Plans/ | `plan-reply-client-20250204T150000.md` |
| Rejected/ | Same as Plans/ | `plan-reply-client-20250204T150000.md` |
| Done/ | Same as Plans/ | `plan-reply-client-20250204T150000.md` |
| Logs/*/ | `YYYY-MM-DD.json` | `2025-02-04.json` |

**Timestamp Format:** `YYYYMMDDTHHMMSS` (no separators for filenames)

---

## Validation Script Usage

```bash
# Validate a single file
python scripts/validate_frontmatter.py vault/Needs_Action/email-test.md

# Force a specific schema
python scripts/validate_frontmatter.py vault/Inbox/test.md --schema action

# Dry run (no modifications)
python scripts/validate_frontmatter.py vault/Plans/plan-test.md --dry-run
```

**Output:**
```json
{
  "valid": true,
  "file": "vault/Needs_Action/email-test.md",
  "schema": "action",
  "errors": [],
  "warnings": ["Optional field 'tags' is empty"]
}
```
