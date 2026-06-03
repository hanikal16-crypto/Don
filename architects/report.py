"""Render an ArchitectureReview into a Markdown report."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from architects.agents import DOMAIN_ARCHITECTS, SOLUTION_ARCHITECT

if TYPE_CHECKING:  # avoid a circular import at runtime
    from architects.codegen import BuildPlan
    from architects.orchestrator import ArchitectureReview


def render_markdown(review: "ArchitectureReview") -> str:
    """Assemble the full review into a single Markdown document."""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    parts: list[str] = [
        "# Architecture Review",
        "",
        f"*Generated {generated} by the Agentic Architects team.*",
        "",
        "## Project brief",
        "",
        review.brief,
        "",
        "---",
        "",
        f"# {SOLUTION_ARCHITECT.emoji} Final architecture",
        "",
        review.final_document or "_(not generated)_",
        "",
        "---",
        "",
        "# Appendix: specialist sections",
        "",
    ]

    parts += [
        f"## {SOLUTION_ARCHITECT.emoji} High-level design",
        "",
        review.high_level_design or "_(not generated)_",
        "",
    ]

    for agent in DOMAIN_ARCHITECTS:
        parts += [
            f"## {agent.emoji} {agent.title}",
            "",
            f"*{agent.remit}*",
            "",
            review.sections.get(agent.key, "_(not generated)_"),
            "",
        ]

    return "\n".join(parts).rstrip() + "\n"


def render_solution_overview(
    plan: "BuildPlan",
    notes: list[str],
    file_paths: list[str],
) -> str:
    """A SOLUTION.md describing the generated repo: stack, layout, how to run."""
    lines: list[str] = [
        "# Generated Solution",
        "",
        "*Built end-to-end by the Agentic Architects engineering crew.*",
        "",
        "## Summary",
        "",
        plan.summary,
        "",
        "## Tech stack",
        "",
        "| Component | Choice |",
        "| --- | --- |",
    ]
    for choice in plan.stack:
        lines.append(f"| {choice.component} | {choice.choice} |")

    lines += ["", "## How to run", "", plan.run_instructions, ""]

    if file_paths:
        lines += ["## Files", ""]
        for path in sorted(file_paths):
            lines.append(f"- `{path}`")
        lines.append("")

    real_notes = [n for n in notes if n.strip()]
    if real_notes:
        lines += ["## Engineer notes", ""]
        for note in real_notes:
            lines += [note.strip(), ""]

    return "\n".join(lines).rstrip() + "\n"
