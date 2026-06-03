"""Coordination logic for the architect agents.

Flow:
    1. The Solution Architect drafts a high-level design from the brief.
    2. The four domain specialists (Data, Security, Observability, Cloud) each
       deep-dive their slice in parallel, given the brief + the high-level design.
    3. The Solution Architect synthesizes everything into a final architecture
       document with a decision log and open risks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from anthropic import AsyncAnthropic

from architects.agents import (
    DOMAIN_ARCHITECTS,
    SOLUTION_ARCHITECT,
    Architect,
)
from architects.config import Settings, build_client

# An optional progress hook: (architect_key, phase) -> awaitable.
# phase is one of: "start", "done".
ProgressHook = Callable[[str, str], Awaitable[None]]


@dataclass
class ArchitectureReview:
    """The full output of a review run."""

    brief: str
    high_level_design: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    final_document: str = ""
    # Cache-read tokens accumulated across all calls, for a quick efficiency read.
    cache_read_tokens: int = 0


async def _noop(_key: str, _phase: str) -> None:
    return None


def _shared_context_block(text: str) -> dict:
    """A cacheable system block holding the context shared across agents.

    Keeping this block byte-identical across the parallel domain calls lets the
    prompt cache serve it once instead of re-reading it four times.
    """
    return {
        "type": "text",
        "text": text,
        "cache_control": {"type": "ephemeral"},
    }


async def _run_agent(
    client: AsyncAnthropic,
    settings: Settings,
    agent: Architect,
    shared_context: str,
    instruction: str,
    review: ArchitectureReview,
) -> str:
    """Run one agent call and return its text output.

    The shared context goes in the first (cached) system block; the agent's
    persona follows it, so the cached prefix is identical across agents.
    """
    system = [
        _shared_context_block(shared_context),
        {"type": "text", "text": agent.system_prompt},
    ]

    async with client.messages.stream(
        model=settings.model,
        max_tokens=settings.max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": settings.effort},
        system=system,
        messages=[{"role": "user", "content": instruction}],
    ) as stream:
        message = await stream.get_final_message()

    usage = getattr(message, "usage", None)
    if usage is not None:
        review.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0

    return "".join(
        block.text for block in message.content if block.type == "text"
    ).strip()


def _format_brief(brief: str) -> str:
    return f"# Project brief\n\n{brief.strip()}\n"


async def run_review(
    brief: str,
    *,
    settings: Settings | None = None,
    client: AsyncAnthropic | None = None,
    progress: ProgressHook | None = None,
) -> ArchitectureReview:
    """Run the full multi-agent architecture review for a project brief."""
    settings = settings or Settings()
    settings.validate()
    owns_client = client is None
    client = client or build_client()
    progress = progress or _noop

    review = ArchitectureReview(brief=brief.strip())

    try:
        # --- Phase 1: Solution Architect drafts the high-level design ---------
        await progress(SOLUTION_ARCHITECT.key, "start")
        review.high_level_design = await _run_agent(
            client,
            settings,
            SOLUTION_ARCHITECT,
            shared_context=_format_brief(brief),
            instruction=(
                "Produce the high-level solution architecture for this brief. "
                "Describe the major components and how they interact, the key "
                "architectural decisions and trade-offs, the integration "
                "approach, and the top cross-cutting risks. Keep it to the "
                "system shape — the Data, Security, Observability, and Cloud "
                "specialists will expand their areas next, so give them a clear "
                "frame to build on."
            ),
            review=review,
        )
        await progress(SOLUTION_ARCHITECT.key, "done")

        # --- Phase 2: domain specialists deep-dive in parallel ---------------
        shared_context = (
            f"{_format_brief(brief)}\n"
            "# High-level design (from the Solution Architect)\n\n"
            f"{review.high_level_design}\n"
        )

        async def run_domain(agent: Architect) -> tuple[str, str]:
            await progress(agent.key, "start")
            text = await _run_agent(
                client,
                settings,
                agent,
                shared_context=shared_context,
                instruction=(
                    f"You are the {agent.title}. Produce your section of the "
                    "architecture, consistent with the high-level design above. "
                    "Flag anywhere you would push back on or change that design."
                ),
                review=review,
            )
            await progress(agent.key, "done")
            return agent.key, text

        results = await asyncio.gather(
            *(run_domain(agent) for agent in DOMAIN_ARCHITECTS)
        )
        review.sections = dict(results)

        # --- Phase 3: Solution Architect synthesizes the final document ------
        await progress(SOLUTION_ARCHITECT.key, "start")
        specialist_input = "\n\n".join(
            f"## {agent.title} section\n\n{review.sections[agent.key]}"
            for agent in DOMAIN_ARCHITECTS
        )
        synthesis_context = (
            f"{_format_brief(brief)}\n"
            "# High-level design\n\n"
            f"{review.high_level_design}\n\n"
            "# Specialist sections\n\n"
            f"{specialist_input}\n"
        )
        review.final_document = await _run_agent(
            client,
            settings,
            SOLUTION_ARCHITECT,
            shared_context=synthesis_context,
            instruction=(
                "Synthesize the high-level design and the four specialist "
                "sections into a single, coherent architecture document. "
                "Reconcile any conflicts between the specialists and state how "
                "you resolved them. Include: an executive summary, the unified "
                "architecture, a numbered decision log (decision → rationale), "
                "the top open risks with mitigations, and a phased delivery "
                "roadmap. Be decisive."
            ),
            review=review,
        )
        await progress(SOLUTION_ARCHITECT.key, "done")

        return review
    finally:
        if owns_client:
            await client.close()
