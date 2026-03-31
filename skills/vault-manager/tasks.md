# Vault Manager Skill - Implementation Tasks

**Feature:** vault-manager skill (Bronze Tier - Part 1)
**Created:** 2025-02-04
**Status:** COMPLETE

## Overview

This document contains the actionable tasks for implementing the vault-manager skill. Tasks are organized by phase and can be executed sequentially or in parallel where marked.

## Task Summary

| Phase | Tasks | Parallel | Description |
|-------|-------|----------|-------------|
| 1 | 3 | 2 | Setup & Dependencies |
| 2 | 5 | 3 | Core Implementation |
| 3 | 4 | 2 | Sample Files & Testing |
| 4 | 2 | 0 | Polish & Documentation |
| **Total** | **14** | **7** | |

---

## Phase 1: Setup & Dependencies

**Goal:** Prepare project for vault-manager implementation

### Tasks

- [x] T001 Add PyYAML dependency to `pyproject.toml` in project dependencies
- [x] T002 [P] Create `backend/utils/__init__.py` with empty module
- [x] T003 [P] Create `skills/vault-manager/scripts/__init__.py` with empty module

### Completion Criteria
- `uv sync` runs without errors
- All `__init__.py` files exist

---

## Phase 2: Core Implementation

**Goal:** Implement the validate_frontmatter.py script and supporting utilities

### Tasks

- [x] T004 Create `backend/utils/frontmatter.py` with YAML parsing utilities
  - Function: `parse_frontmatter(file_path: str) -> dict`
  - Function: `update_frontmatter(file_path: str, updates: dict) -> None`
  - Function: `extract_frontmatter(content: str) -> tuple[dict, str]`
  - Include type hints and Google-style docstrings

- [x] T005 [P] Create `backend/utils/timestamps.py` with ISO 8601 utilities
  - Function: `now_iso() -> str` - Current UTC timestamp
  - Function: `parse_iso(timestamp: str) -> datetime`
  - Function: `format_filename_timestamp() -> str` - Format for filenames (YYYYMMDDTHHMMSS)

- [x] T006 [P] Create `backend/utils/uuid_utils.py` with UUID generation
  - Function: `correlation_id() -> str` - Generate UUID v4

- [x] T007 Create `skills/vault-manager/scripts/validate_frontmatter.py`
  - Implement schema definitions (action, plan, done, rejected)
  - Implement `detect_schema(file_path: str) -> str`
  - Implement `validate(file_path: str, schema: str | None) -> dict`
  - Support `--schema` flag to override detection
  - Support `--dry-run` flag per constitution
  - Output JSON with: valid, file, schema, errors, warnings
  - Include type hints and Google-style docstrings

- [x] T008 [P] Create `backend/utils/logging_utils.py` for audit logging
  - Function: `log_action(log_dir: str, entry: dict) -> None`
  - Function: `read_recent_logs(log_dir: str, count: int) -> list[dict]`
  - Append to daily JSON files (YYYY-MM-DD.json)
  - Handle file creation if not exists

### Completion Criteria
- All utility modules have type hints
- `validate_frontmatter.py --help` shows usage
- Running validator on empty file returns structured JSON error

---

## Phase 3: Sample Files & Testing

**Goal:** Create sample vault files and verify skill operations work

### Tasks

- [x] T009 Create sample action file `vault/Needs_Action/task-test-vault-manager-20250204T170000.md`
  - Valid frontmatter with all required fields
  - Body with Summary, Details, Suggested Action sections

- [x] T010 [P] Create sample plan file `vault/Plans/plan-test-approval-workflow-20250204T170500.md`
  - Valid plan frontmatter with requires_approval: true
  - Include objective, action_summary, risk_assessment

- [x] T011 Create test script `tests/test_validate_frontmatter.py`
  - Test: valid action file passes validation
  - Test: missing required field fails validation
  - Test: invalid enum value fails validation
  - Test: schema auto-detection by path
  - Test: --dry-run flag behavior

- [x] T012 [P] Create test script `tests/test_frontmatter_utils.py`
  - Test: parse_frontmatter extracts YAML correctly
  - Test: update_frontmatter modifies only specified fields
  - Test: handles files without frontmatter gracefully

### Completion Criteria
- `uv run pytest tests/` passes all tests
- Sample files validate successfully with validate_frontmatter.py

---

## Phase 4: Polish & Documentation

**Goal:** Final cleanup and verification

### Tasks

- [x] T013 Verify SKILL.md is under 500 lines and contains all required sections
  - Frontmatter schemas documented
  - All triggers listed
  - Examples for each operation
  - Decision trees complete

- [x] T014 Run full validation cycle
  - Validate all sample files
  - Test status transition (move sample from Needs_Action to Plans)
  - Verify dashboard update instructions are clear

### Completion Criteria
- `wc -l skills/vault-manager/SKILL.md` returns < 500
- All sample files pass validation
- Manual review confirms skill is usable

---

## Dependencies Graph

```
Phase 1 (Setup)
    │
    ├── T001 (pyproject.toml) ─────────────────────┐
    │                                              │
    ├── T002 [P] (backend/utils/__init__)          │
    │                                              │
    └── T003 [P] (scripts/__init__)                │
                                                   │
Phase 2 (Core) ◄───────────────────────────────────┘
    │
    ├── T004 (frontmatter.py) ─────────────────────┐
    │                                              │
    ├── T005 [P] (timestamps.py)                   │
    │                                              │
    ├── T006 [P] (uuid_utils.py)                   │
    │                                              ├──► T007 (validate_frontmatter.py)
    └── T008 [P] (logging_utils.py)                │
                                                   │
Phase 3 (Testing) ◄────────────────────────────────┘
    │
    ├── T009 (sample action file)
    │
    ├── T010 [P] (sample plan file)
    │
    ├── T011 (test_validate_frontmatter.py) ◄── T007
    │
    └── T012 [P] (test_frontmatter_utils.py) ◄── T004
                                                   │
Phase 4 (Polish) ◄─────────────────────────────────┘
    │
    ├── T013 (verify SKILL.md)
    │
    └── T014 (full validation cycle)
```

---

## Parallel Execution Guide

### Batch 1 (Setup - can run together)
```
T002 + T003  # Both are __init__.py files
```

### Batch 2 (Utilities - can run together)
```
T005 + T006 + T008  # Independent utility modules
```

### Batch 3 (Testing - can run together)
```
T010 + T012  # Sample plan + utility tests
```

---

## Implementation Strategy

### MVP Scope (Minimum for Bronze Tier)
1. Complete Phase 1 (Setup)
2. Complete T004, T007 from Phase 2 (frontmatter parsing + validation)
3. Complete T009, T011 from Phase 3 (one sample file + basic tests)

**MVP Deliverables:**
- Working `validate_frontmatter.py` script
- One valid sample file
- Basic test coverage

### Full Implementation
Complete all phases for production-ready vault-manager skill.

---

## Files to Create/Modify

| Task | File Path | Action |
|------|-----------|--------|
| T001 | `pyproject.toml` | Modify (add PyYAML) |
| T002 | `backend/utils/__init__.py` | Create |
| T003 | `skills/vault-manager/scripts/__init__.py` | Create |
| T004 | `backend/utils/frontmatter.py` | Create |
| T005 | `backend/utils/timestamps.py` | Create |
| T006 | `backend/utils/uuid_utils.py` | Create |
| T007 | `skills/vault-manager/scripts/validate_frontmatter.py` | Create |
| T008 | `backend/utils/logging_utils.py` | Create |
| T009 | `vault/Needs_Action/task-test-vault-manager-*.md` | Create |
| T010 | `vault/Plans/plan-test-approval-workflow-*.md` | Create |
| T011 | `tests/test_validate_frontmatter.py` | Create |
| T012 | `tests/test_frontmatter_utils.py` | Create |
| T013 | `skills/vault-manager/SKILL.md` | Verify |
| T014 | N/A | Manual verification |

---

## Notes

- All Python code must follow constitution standards:
  - Type hints required
  - Google-style docstrings required
  - Async/await for I/O (where applicable)
- PyYAML is safe for our use case (local files only, no untrusted input)
- validate_frontmatter.py should be runnable standalone or importable
