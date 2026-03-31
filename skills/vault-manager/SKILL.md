---
name: vault-manager
version: 1.1.0
description: |
  Core skill for managing the Obsidian vault lifecycle. Handles file operations,
  status transitions, dashboard updates, and audit logging.

  TRIGGERS: Use this skill when you need to:
  - Check vault status ("what's pending", "vault status", "show inbox")
  - Create action items ("create task", "add action item", "new item")
  - Move files through workflow ("move to approved", "approve plan", "reject")
  - Update dashboard ("refresh dashboard", "update status")
  - Log actions ("log this", "record action")
  - Process inbox ("triage inbox", "process new items")
dependencies: []
permissions:
  - read: vault/**/*.md
  - write: vault/**/*.md
  - write: vault/Logs/**/*.json
sensitivity: low
---

# Vault Manager Skill

Manage the Obsidian vault structure, track items through their lifecycle, update the dashboard, and maintain audit logs.

## Vault Structure

```
vault/
├── Dashboard.md           # Status overview - YOU UPDATE THIS
├── Company_Handbook.md    # Reference only - DO NOT MODIFY
├── Business_Goals.md      # Reference only - DO NOT MODIFY
├── Inbox/                 # Raw items from watchers
├── Needs_Action/          # Items awaiting processing
├── Plans/                 # Documented action plans
├── Pending_Approval/      # Awaiting human approval
├── Approved/              # Ready for MCP execution
├── Rejected/              # Declined by human
├── Done/                  # Completed actions
├── Logs/                  # Audit trail (JSON files)
├── Briefings/             # CEO briefings
└── Accounting/            # Financial records
```

## File Lifecycle

```
Inbox → Needs_Action → Plans → Pending_Approval → Approved → Done
                                      ↓
                                  Rejected
```

## Frontmatter Schemas

### Action File (Inbox/, Needs_Action/)

```yaml
---
type: email | whatsapp | calendar | file | task | payment | social | other
source: gmail_watcher | whatsapp_watcher | calendar_watcher | manual
from: sender@example.com        # Required for email, whatsapp, calendar
subject: "Brief description"    # Required for email, calendar
received: 2025-02-04T14:30:00Z  # Required for email, whatsapp
created: 2025-02-04T14:30:22Z   # When file was created
priority: high | medium | low
status: pending | needs_action | in_progress
tags: [optional, tags]
---
```

### Plan File (Plans/, Pending_Approval/, Approved/)

```yaml
---
created: 2025-02-04T14:30:22Z
status: draft | pending_approval | approved | in_progress | done
objective: "What we're trying to achieve"
action_summary: "Brief description of proposed action"
requires_approval: true | false
sensitivity: low | medium | high
source_file: "original-action-file.md"
risk_assessment: "Potential risks"
rollback_plan: "How to undo if needed"
---
```

### Done File (Done/)

```yaml
---
# Inherits plan fields plus:
completed_at: 2025-02-04T15:05:00Z
result: success | partial | failed
outcome_summary: "What actually happened"
---
```

### Rejected File (Rejected/)

```yaml
---
# Inherits plan fields plus:
rejected_at: 2025-02-04T15:00:00Z
rejection_reason: "Why it was rejected"  # REQUIRED
---
```

## Log Entry Format (JSON)

```json
{
  "timestamp": "2025-02-04T14:30:22Z",
  "correlation_id": "uuid-v4",
  "actor": "vault-manager | gmail_watcher | claude_code | human",
  "action_type": "file_create | file_move | file_update | dashboard_update | external_action | error",
  "target": "path/to/file.md",
  "parameters": {
    "from_folder": "Needs_Action",
    "to_folder": "Plans",
    "reason": "Created action plan"
  },
  "result": "success | failure",
  "duration_ms": 45,
  "error": "optional error message"
}
```

## Operations

### 1. Check Vault Status

**Triggers:** "what's pending", "vault status", "show inbox", "check status"

**Steps:**
1. Count files in each workflow folder
2. Read frontmatter from Needs_Action/ and Plans/
3. Sort by priority (high → medium → low)
4. Format summary

**Output:**
```markdown
## Vault Status

**Inbox:** 0 items
**Needs Action:** 2 items
| Priority | Type | File | Summary |
|----------|------|------|---------|
| HIGH | email | email-client-20250204.md | Contract inquiry |
| LOW | task | task-followup-20250204.md | Weekly review |

**Plans:** 1 item
**Pending Approval:** 0 items
**Done (today):** 3 items
```

### 2. Create Action Item

**Triggers:** "create action", "add task", "new item for"

**Steps:**
1. Determine type from context
2. Generate filename: `{type}-{short-desc}-{timestamp}.md`
3. Create frontmatter with required fields
4. Write file to Needs_Action/
5. Log creation
6. Update dashboard

**File naming:** `{type}-{short-description}-{YYYYMMDDTHHMMSS}.md`

### 3. Move Files

**Triggers:** "move to approved", "approve", "reject", "mark done"

**Status transitions:**
| From | To | New Status | Additional Fields |
|------|----|------------|-------------------|
| Inbox | Needs_Action | `needs_action` | - |
| Needs_Action | Plans | `draft` | - |
| Plans | Pending_Approval | `pending_approval` | - |
| Pending_Approval | Approved | `approved` | `approved_at`, `approved_by` |
| Pending_Approval | Rejected | `rejected` | `rejected_at`, `rejection_reason` |
| Approved | Done | `done` | `completed_at`, `result` |

**Steps:**
1. Read source file
2. Update status in frontmatter
3. Add transition fields (timestamps, etc.)
4. Write to destination folder
5. Delete from source folder
6. Log the move to appropriate Logs/ subfolder
7. Update dashboard

### 4. Update Dashboard

**Triggers:** "update dashboard", "refresh status"

**Sections to update:**
1. **System Status** - DEV_MODE, watcher statuses
2. **Active Tasks** - Top 10 from Needs_Action/ and Plans/
3. **Recent Activity** - Last 10 from Logs/actions/
4. **Alerts** - Errors from last 24h
5. **Statistics** - Today's counts

### 5. Log Action

**Triggers:** automatic after every operation

**Log to:**
- `Logs/actions/` - File operations, external actions
- `Logs/decisions/` - Reasoning traces
- `Logs/errors/` - Failures
- `Logs/audit/` - Security events (approvals, rejections)

**File naming:** `YYYY-MM-DD.json`

## Decision Trees

### Triage Inbox Item

```
1. Read file from Inbox/
2. Has valid frontmatter?
   NO → Generate frontmatter from content
   YES → Parse metadata
3. Determine priority:
   - Payment OR urgent keyword → HIGH
   - VIP sender (check Company_Handbook) → HIGH
   - Deadline < 48h → MEDIUM
   - Otherwise → LOW
4. Move to Needs_Action/ with updated priority
5. Log decision to Logs/decisions/
```

### Create Plan from Action

```
1. Read action from Needs_Action/
2. Analyze against Business_Goals.md
3. Check Company_Handbook.md for rules
4. Determine if approval needed:
   - Payment > $0 → requires_approval: true
   - External send → requires_approval: true
   - Social post → requires_approval: true
   - Archive/organize → requires_approval: false
5. Create plan file with:
   - objective
   - action_summary
   - risk_assessment (if sensitive)
   - rollback_plan (if applicable)
6. Move to Plans/ or Pending_Approval/ based on requires_approval
7. Log decision
```

## Constraints

- **NEVER** modify Company_Handbook.md or Business_Goals.md
- **NEVER** delete files without logging
- **ALWAYS** update Dashboard.md after file operations
- **ALWAYS** log to appropriate Logs/ subfolder
- **ALWAYS** preserve original content when moving
- **MAXIMUM** 10 items in Active Tasks table
- **MAXIMUM** 10 items in Recent Activity table

## Error Handling

1. Log error to `Logs/errors/YYYY-MM-DD.json`
2. Add alert to Dashboard.md
3. Keep file in original location if move fails
4. Never leave vault in inconsistent state

## Examples

### Example 1: Check Status

**User:** "What's pending in the vault?"

**Response:**
```
## Vault Status Report

**Inbox:** 0 items
**Needs Action:** 1 item
| Priority | Type | File | Summary |
|----------|------|------|---------|
| HIGH | email | email-contract-20250204.md | Contract review from VIP |

**Pending Approval:** 0 items
**Done (today):** 2 items

Dashboard updated.
```

### Example 2: Create Task

**User:** "Create a task to follow up with Sarah about the invoice"

**Creates:** `vault/Needs_Action/task-followup-sarah-invoice-20250204T160000.md`

```yaml
---
type: task
source: manual
created: 2025-02-04T16:00:00Z
priority: medium
status: needs_action
tags: [followup, invoice, sarah]
---

# Follow Up: Sarah Invoice

## Summary
Follow up with Sarah regarding the pending invoice discussion.

## Suggested Action
Send email or message to Sarah asking about invoice status.
```

### Example 3: Approve Plan

**User:** "Approve the plan for replying to the contract email"

**Actions:**
1. Find `plan-reply-contract-*.md` in Pending_Approval/
2. Update frontmatter:
   ```yaml
   status: approved
   approved_at: 2025-02-04T16:30:00Z
   approved_by: human
   ```
3. Move to Approved/
4. Log to Logs/audit/
5. Update dashboard

**Response:** "Plan approved and moved to Approved/. Ready for execution."

### Example 4: Reject Plan

**User:** "Reject the bulk email plan - too many recipients"

**Actions:**
1. Find plan in Pending_Approval/
2. Update frontmatter:
   ```yaml
   status: rejected
   rejected_at: 2025-02-04T16:35:00Z
   rejection_reason: "Too many recipients - need to batch"
   ```
3. Move to Rejected/
4. Log to Logs/audit/
5. Update dashboard

**Response:** "Plan rejected. Reason recorded for future learning."
