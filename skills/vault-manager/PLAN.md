# Vault Manager Skill - Implementation Plan

**Version:** 1.0.0
**Created:** 2025-02-04
**Status:** Ready for Implementation

## Overview

This plan details the technical implementation of the vault-manager skill, which is the foundational skill for the Personal AI Employee system. It manages the Obsidian vault structure, file lifecycle, dashboard updates, and audit logging.

## Constitution Compliance Check

| Principle | Status | Implementation |
|-----------|--------|----------------|
| I. Local-First | ✅ PASS | All operations on local vault files only |
| II. Separation of Concerns | ✅ PASS | Skill is REASONING layer only - no external actions |
| III. Skills as First-Class | ✅ PASS | Self-contained SKILL.md with clear boundaries |
| IV. HITL Safety | ✅ PASS | Respects approval workflow, doesn't bypass |
| V. DEV_MODE | ✅ PASS | No external actions to mock |
| VI. Rate Limiting | N/A | No external API calls |
| VII. Logging | ✅ PASS | Comprehensive audit logging defined |
| VIII. Error Handling | ✅ PASS | Error handling documented |

## Deliverables

### 1. Updated SKILL.md (Refactor Existing)

**Changes Required:**
- Align frontmatter with user's specified schema
- Consolidate frontmatter schemas into dedicated section
- Add trigger conditions more explicitly in description
- Ensure all file type schemas are documented

### 2. scripts/validate_frontmatter.py

**Purpose:** Python script to validate YAML frontmatter against defined schemas

**Features:**
- Validate frontmatter against schema for file type
- Report missing required fields
- Report invalid field values
- Support `--dry-run` flag per constitution
- Return structured JSON output

**Interface:**
```bash
python validate_frontmatter.py <file_path> [--schema <type>] [--dry-run]
```

**Output:**
```json
{
  "valid": true|false,
  "file": "path/to/file.md",
  "schema": "action|plan|log",
  "errors": [],
  "warnings": []
}
```

### 3. references/frontmatter_schema.md

**Purpose:** Human-readable schema documentation for all file types

**Schemas to Document:**

1. **Action File** (Inbox/, Needs_Action/)
2. **Plan File** (Plans/, Pending_Approval/, Approved/)
3. **Done File** (Done/)
4. **Rejected File** (Rejected/)
5. **Log Entry** (Logs/*.json)

## Technical Design

### Frontmatter Schemas

#### Action File Schema (Inbox/, Needs_Action/)

```yaml
---
# Required fields
type: email | whatsapp | calendar | file | task | payment | social | other
source: gmail_watcher | whatsapp_watcher | calendar_watcher | manual | <skill-name>
created: ISO 8601 timestamp (YYYY-MM-DDTHH:MM:SSZ)
priority: high | medium | low
status: pending | needs_action | in_progress

# Conditional fields (based on type)
from: string          # Required for: email, whatsapp, calendar
subject: string       # Required for: email, calendar
received: ISO 8601    # Required for: email, whatsapp

# Optional fields
id: string            # Auto-generated if not provided: {type}-{timestamp}
tags: [string]        # For categorization
related: [string]     # Links to related files
due: ISO 8601         # Deadline if applicable
---
```

#### Plan File Schema (Plans/, Pending_Approval/, Approved/)

```yaml
---
# Required fields
created: ISO 8601 timestamp
status: draft | pending_approval | approved | rejected | in_progress | done
objective: string     # What we're trying to achieve

# Required for approval workflow
action_summary: string     # Brief description of proposed action
requires_approval: true | false
sensitivity: low | medium | high

# Optional fields
source_file: string        # Original action file this plan addresses
risk_assessment: string    # Potential risks
rollback_plan: string      # How to undo if needed
approved_at: ISO 8601      # When human approved
approved_by: string        # Who approved (human identifier)
rejection_reason: string   # If rejected, why
---
```

#### Done File Schema (Done/)

```yaml
---
# Inherits from Plan schema, plus:
completed_at: ISO 8601
result: success | partial | failed
execution_log: string      # Reference to log entry
outcome_summary: string    # What actually happened
---
```

#### Rejected File Schema (Rejected/)

```yaml
---
# Inherits from Plan schema, plus:
rejected_at: ISO 8601
rejected_by: string
rejection_reason: string   # Required - why it was rejected
---
```

### Log Entry Schema (JSON)

```json
{
  "timestamp": "ISO 8601 (required)",
  "correlation_id": "UUID v4 (required)",
  "actor": "claude_code | gmail_watcher | whatsapp_watcher | vault-manager | human (required)",
  "action_type": "file_create | file_move | file_update | dashboard_update | external_action | error (required)",
  "target": "file path or identifier (required)",
  "parameters": {
    "from_folder": "string (for moves)",
    "to_folder": "string (for moves)",
    "fields_changed": ["array of field names (for updates)"],
    "reason": "string"
  },
  "result": "success | failure (required)",
  "duration_ms": "number (optional)",
  "error": "string (required if result=failure)"
}
```

### File Naming Conventions

| Location | Pattern | Example |
|----------|---------|---------|
| Inbox/ | `{source}-{type}-{timestamp}.md` | `gmail_watcher-email-20250204T143022.md` |
| Needs_Action/ | `{type}-{short-desc}-{timestamp}.md` | `email-client-inquiry-20250204T143022.md` |
| Plans/ | `plan-{objective-slug}-{timestamp}.md` | `plan-reply-client-20250204T150000.md` |
| Pending_Approval/ | Same as Plans/ | |
| Approved/ | Same as Plans/ | |
| Rejected/ | Same as Plans/ + rejection timestamp | |
| Done/ | Same as Plans/ + completion timestamp | |
| Logs/ | `YYYY-MM-DD.json` | `2025-02-04.json` |

### Status Transitions

```
┌─────────────────────────────────────────────────────────────────┐
│                      FILE STATUS MACHINE                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [Watcher creates]                                              │
│        │                                                        │
│        ▼                                                        │
│   ┌─────────┐                                                   │
│   │ pending │ (Inbox/)                                          │
│   └────┬────┘                                                   │
│        │ vault-manager triages                                  │
│        ▼                                                        │
│   ┌──────────────┐                                              │
│   │ needs_action │ (Needs_Action/)                              │
│   └──────┬───────┘                                              │
│          │ vault-manager creates plan                           │
│          ▼                                                      │
│   ┌───────────┐     requires_approval=true     ┌──────────────┐ │
│   │  draft    │ ──────────────────────────────▶│pending_approval│
│   │ (Plans/)  │                                │(Pending_Approval)│
│   └─────┬─────┘                                └───────┬───────┘ │
│         │                                             │         │
│         │ requires_approval=false              ┌──────┴──────┐  │
│         │                                      │             │  │
│         ▼                                      ▼             ▼  │
│   ┌───────────┐                          ┌──────────┐ ┌────────┐│
│   │ approved  │◀─────── human approves───│ approved │ │rejected││
│   │(Approved/)│                          │(Approved/)│ │(Rejected)│
│   └─────┬─────┘                          └────┬─────┘ └────────┘│
│         │                                     │                 │
│         │ MCP executes                        │                 │
│         ▼                                     ▼                 │
│   ┌───────────┐                          ┌──────────┐           │
│   │   done    │                          │   done   │           │
│   │  (Done/)  │                          │  (Done/) │           │
│   └───────────┘                          └──────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Dashboard Update Protocol

The Dashboard.md file has specific sections that must be updated:

1. **System Status Table** (line ~15-22)
   - Update DEV_MODE status from environment
   - Update watcher statuses (check if processes running)
   - Update last check timestamp

2. **Active Tasks Table** (line ~30-40)
   - List top 10 items from Needs_Action/ and Plans/
   - Sort by priority (high first), then by created date
   - Format: `| Task | Source | Priority | Status | Created |`

3. **Recent Activity Table** (line ~50-60)
   - Read last 10 entries from Logs/actions/
   - Format: `| Timestamp | Action | Target | Result |`

4. **Alerts Section** (line ~70-85)
   - Check Logs/errors/ for entries from last 24 hours
   - Categorize as Critical, Warning, Info

5. **Statistics Table** (line ~95-105)
   - Count files in each folder for today
   - Calculate from log entries

### validate_frontmatter.py Design

```python
"""
Validate YAML frontmatter in vault markdown files.

Usage:
    python validate_frontmatter.py <file_path> [--schema <type>] [--dry-run]

Arguments:
    file_path   Path to the markdown file to validate
    --schema    Override auto-detected schema (action|plan|done|rejected)
    --dry-run   Only report, don't modify anything

Output:
    JSON object with validation results
"""

# Schema definitions as Python dicts
SCHEMAS = {
    "action": {
        "required": ["type", "source", "created", "priority", "status"],
        "optional": ["id", "from", "subject", "received", "tags", "related", "due"],
        "enums": {
            "type": ["email", "whatsapp", "calendar", "file", "task", "payment", "social", "other"],
            "source": ["gmail_watcher", "whatsapp_watcher", "calendar_watcher", "manual"],
            "priority": ["high", "medium", "low"],
            "status": ["pending", "needs_action", "in_progress"]
        },
        "conditional": {
            "from": {"when": {"type": ["email", "whatsapp", "calendar"]}},
            "subject": {"when": {"type": ["email", "calendar"]}},
            "received": {"when": {"type": ["email", "whatsapp"]}}
        }
    },
    "plan": {
        "required": ["created", "status", "objective"],
        "optional": ["action_summary", "requires_approval", "sensitivity", "source_file",
                    "risk_assessment", "rollback_plan", "approved_at", "approved_by", "rejection_reason"],
        "enums": {
            "status": ["draft", "pending_approval", "approved", "rejected", "in_progress", "done"],
            "sensitivity": ["low", "medium", "high"]
        }
    },
    "done": {
        "required": ["created", "status", "objective", "completed_at", "result"],
        "optional": ["execution_log", "outcome_summary"],
        "enums": {
            "result": ["success", "partial", "failed"]
        }
    },
    "rejected": {
        "required": ["created", "status", "objective", "rejected_at", "rejection_reason"],
        "optional": ["rejected_by"]
    }
}

# Auto-detect schema based on file path
def detect_schema(file_path: str) -> str:
    if "/Inbox/" in file_path or "/Needs_Action/" in file_path:
        return "action"
    elif "/Done/" in file_path:
        return "done"
    elif "/Rejected/" in file_path:
        return "rejected"
    else:  # Plans/, Pending_Approval/, Approved/
        return "plan"
```

## Implementation Tasks

### Task 1: Update SKILL.md
- [ ] Align frontmatter with specified format
- [ ] Add all frontmatter schemas in dedicated section
- [ ] Expand trigger conditions in description
- [ ] Add file naming conventions
- [ ] Add status transition diagram

### Task 2: Create references/frontmatter_schema.md
- [ ] Document all 5 schema types
- [ ] Include examples for each
- [ ] Add validation rules
- [ ] Add conditional field requirements

### Task 3: Create scripts/validate_frontmatter.py
- [ ] Implement schema validation logic
- [ ] Support all 4 file type schemas
- [ ] Add `--dry-run` flag support
- [ ] Output JSON results
- [ ] Add type hints (per constitution)
- [ ] Add docstrings (Google style)

### Task 4: Test the Skill
- [ ] Create sample files in each folder
- [ ] Test frontmatter validation
- [ ] Test status transitions
- [ ] Verify dashboard update protocol

## Dependencies

- Python 3.13+ (per constitution)
- PyYAML (for frontmatter parsing) - add to pyproject.toml
- No external API dependencies

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Frontmatter parsing errors | Files become unreadable | Validate before write, keep backups |
| Dashboard corruption | User loses visibility | Atomic writes, validate structure |
| Log file growth | Disk space | Implement rotation (90 day retention per constitution) |

## Success Criteria

1. **SKILL.md** is under 500 lines and self-contained
2. **validate_frontmatter.py** validates all schema types correctly
3. **frontmatter_schema.md** documents all fields clearly
4. Sample files can be created and moved through workflow
5. Dashboard updates correctly reflect vault state

## Next Steps

After implementation:
1. Create `email-triage` skill (depends on vault-manager)
2. Create `gmail-watcher` (Python script in backend/watchers/)
3. Test end-to-end flow: Watcher → Vault → Skill → Dashboard
