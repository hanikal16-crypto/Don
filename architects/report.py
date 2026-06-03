"""Render an ArchitectureReview into a Markdown report."""

from __future__ import annotations

from datetime import datetime, timezone

from architects.agents import DOMAIN_ARCHITECTS, SOLUTION_ARCHITECT
from architects.orchestrator import ArchitectureReview


def render_markdown(review: ArchitectureReview) -> str:
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
