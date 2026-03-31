"""Prompt injector for Ralph Wiggum Loop — builds continuation prompts.

Prepends a summary of previous iteration outputs to the original task prompt
so Claude has context about what has been tried so far.
"""

from __future__ import annotations

from backend.ralph_wiggum import IterationRecord


class PromptInjector:
    """Builds continuation prompts with previous iteration context."""

    @staticmethod
    def build_continuation_prompt(
        original_prompt: str,
        iteration_records: list[IterationRecord],
        max_summary_chars: int = 500,
    ) -> str:
        """Build a prompt with previous iteration context appended.

        If no iteration records exist, returns the original prompt unchanged.
        Otherwise prepends iteration summaries for context continuity.

        Args:
            original_prompt: The original task prompt text.
            iteration_records: List of completed iterations so far.
            max_summary_chars: Maximum characters from each iteration summary.

        Returns:
            The original prompt, or prompt + iteration history if records exist.

        Examples:
            >>> p = PromptInjector.build_continuation_prompt("do task", [])
            >>> p
            'do task'
        """
        if not iteration_records:
            return original_prompt

        lines = [
            original_prompt,
            "",
            "## Previous Iterations (context)",
        ]

        for rec in iteration_records:
            summary = rec.output_summary[:max_summary_chars] if rec.output_summary else "(no output)"
            lines.append(f"Iteration {rec.iteration_number}: {summary}")

        lines.append("")
        lines.append("Continue from where you left off.")

        return "\n".join(lines)
