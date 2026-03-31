"""Ralph Wiggum stop hook — onStop hook for Claude Code.

Invoked by Claude Code's onStop event via .claude/settings.json.
Reads vault/ralph_wiggum/ state and decides whether to block or allow exit.

Input (stdin): JSON payload from Claude Code
Output (stdout): JSON decision {"decision": "block"|"approve", "reason": "..."}
Exit code: always 0 (non-zero exit causes the JSON output to be ignored)
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from backend.ralph_wiggum import HaltReason, LoopStatus
from backend.ralph_wiggum.prompt_injector import PromptInjector
from backend.ralph_wiggum.state_manager import StateManager
from backend.utils.timestamps import now_iso

logger = logging.getLogger(__name__)


def main() -> None:
    """Read stdin JSON, check task state, output block/approve JSON."""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        payload = {}

    # Determine vault path from payload or fallback to cwd
    claude_project_dir = Path(payload.get("claude_project_dir", "."))
    vault_path = claude_project_dir / "vault"

    mgr = StateManager(vault_path)

    # Emergency stop takes absolute priority
    if mgr.emergency_stop_active():
        print(json.dumps({
            "decision": "block",
            "reason": (
                "Emergency stop active (vault/STOP_RALPH exists). "
                "Remove the file to resume: rm vault/STOP_RALPH"
            ),
        }))
        return

    # Find all in-progress tasks
    all_tasks = mgr.load_all_tasks()
    active = [t for t in all_tasks if t.status == LoopStatus.in_progress]

    if not active:
        print(json.dumps({"decision": "approve"}))
        return

    # Use the most recently created task (latest task_id)
    task = active[-1]

    # Check safety limits
    if task.current_iteration >= task.max_iterations:
        task.status = LoopStatus.halted
        task.halt_reason = HaltReason.max_iterations_reached
        task.completed_at = now_iso()
        mgr.update_task(task)
        print(json.dumps({"decision": "approve"}))
        return

    # Task incomplete — increment counter and block exit
    task.current_iteration += 1
    task.last_iteration_at = now_iso()
    mgr.update_task(task)

    # Build continuation context
    continuation = PromptInjector.build_continuation_prompt(
        task.prompt,
        task.iterations,
        max_summary_chars=300,
    )
    # Truncate reason to keep hook response manageable
    reason = (
        f"Task {task.task_id} incomplete. "
        f"Iteration {task.current_iteration}/{task.max_iterations}. "
        f"{continuation[:500]}"
    )

    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
