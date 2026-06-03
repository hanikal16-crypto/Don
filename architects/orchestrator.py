"""Coordination logic for the full agent pipeline.

Two phases:

1. **Design** — the five architects (Solution leads; Data, Security,
   Observability, Cloud run in parallel) turn the spec into an architecture.
2. **Engineering** — a Tech Lead plans the build, then Backend and Frontend
   engineers implement it in parallel and a QA engineer writes tests + CI,
   producing a runnable end-to-end repository.

Progress is reported through an :class:`~architects.events.EventHook` so the
CLI and the web backend (SSE) can render the same live stream.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic

from architects import report
from architects.agents import (
    BACKEND_ENGINEER,
    DOMAIN_ARCHITECTS,
    FRONTEND_ENGINEER,
    QA_ENGINEER,
    SOLUTION_ARCHITECT,
    TECH_LEAD,
    Architect,
)
from architects.codegen import (
    BUILD_PLAN_SCHEMA,
    FILE_BUNDLE_SCHEMA,
    BuildPlan,
    GeneratedFile,
    parse_build_plan,
    parse_file_bundle,
)
from architects.config import Settings, build_client
from architects.events import EventHook, RunEvent, noop_hook
from architects.llm import build_system, run_structured, run_text


# --- Result models ----------------------------------------------------------


@dataclass
class ArchitectureReview:
    """Output of the design phase."""

    brief: str
    high_level_design: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    final_document: str = ""
    cache_read_tokens: int = 0  # kept for backward compatibility


@dataclass
class GeneratedSolution:
    """Output of the engineering phase: a runnable repo."""

    build_plan: BuildPlan | None = None
    files: list[GeneratedFile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RunResult:
    """Everything produced by a single run."""

    brief: str
    review: ArchitectureReview
    solution: GeneratedSolution | None = None
    cache_read_tokens: int = 0


# --- Engine: one place that makes calls and emits events --------------------


class _Engine:
    def __init__(
        self,
        client: AsyncAnthropic,
        settings: Settings,
        hook: EventHook,
    ) -> None:
        self.client = client
        self.settings = settings
        self.hook = hook
        self.cache_read_tokens = 0

    async def emit(self, event: RunEvent) -> None:
        await self.hook(event)

    async def _agent_start(self, agent: Architect) -> None:
        await self.emit(
            RunEvent(
                type="agent",
                message=f"{agent.title} is working…",
                agent=agent.key,
                phase="start",
            )
        )

    async def _agent_done(self, agent: Architect, data: dict | None = None) -> None:
        await self.emit(
            RunEvent(
                type="agent",
                message=f"{agent.title} finished.",
                agent=agent.key,
                phase="done",
                data=data or {},
            )
        )

    async def text(self, agent: Architect, shared: str, instruction: str) -> str:
        await self._agent_start(agent)
        system = build_system(shared, agent.system_prompt)
        out, cache = await run_text(self.client, self.settings, system, instruction)
        self.cache_read_tokens += cache
        await self._agent_done(agent)
        return out

    async def structured(
        self, agent: Architect, shared: str, instruction: str, schema: dict
    ) -> dict:
        await self._agent_start(agent)
        system = build_system(shared, agent.system_prompt)
        data, cache = await run_structured(
            self.client,
            self.settings,
            system,
            instruction,
            schema,
            max_tokens=self.settings.engineering_max_tokens,
        )
        self.cache_read_tokens += cache
        return data  # caller emits its own done event with file counts


# --- Phase helpers ----------------------------------------------------------


def _format_brief(brief: str) -> str:
    return f"# Project specification\n\n{brief.strip()}\n"


async def _run_design(brief: str, engine: _Engine) -> ArchitectureReview:
    review = ArchitectureReview(brief=brief.strip())

    await engine.emit(
        RunEvent("phase", "Designing the architecture", phase="start",
                 data={"phase": "design"})
    )

    # Phase 1 — high-level design.
    review.high_level_design = await engine.text(
        SOLUTION_ARCHITECT,
        _format_brief(brief),
        "Produce the high-level solution architecture for this specification. "
        "Describe the major components and how they interact, the key "
        "architectural decisions and trade-offs, the integration approach, and "
        "the top cross-cutting risks. Keep it to the system shape — the Data, "
        "Security, Observability, and Cloud specialists will expand their areas "
        "next, so give them a clear frame to build on.",
    )

    # Phase 2 — domain specialists in parallel.
    shared = (
        f"{_format_brief(brief)}\n"
        "# High-level design (from the Solution Architect)\n\n"
        f"{review.high_level_design}\n"
    )

    async def run_domain(agent: Architect) -> tuple[str, str]:
        text = await engine.text(
            agent,
            shared,
            f"You are the {agent.title}. Produce your section of the "
            "architecture, consistent with the high-level design above. Flag "
            "anywhere you would push back on or change that design.",
        )
        return agent.key, text

    results = await asyncio.gather(*(run_domain(a) for a in DOMAIN_ARCHITECTS))
    review.sections = dict(results)

    # Phase 3 — synthesis.
    specialist_input = "\n\n".join(
        f"## {a.title} section\n\n{review.sections[a.key]}" for a in DOMAIN_ARCHITECTS
    )
    synthesis_context = (
        f"{_format_brief(brief)}\n"
        f"# High-level design\n\n{review.high_level_design}\n\n"
        f"# Specialist sections\n\n{specialist_input}\n"
    )
    review.final_document = await engine.text(
        SOLUTION_ARCHITECT,
        synthesis_context,
        "Synthesize the high-level design and the four specialist sections into "
        "a single, coherent architecture document. Reconcile any conflicts and "
        "state how you resolved them. Include: an executive summary, the unified "
        "architecture, a numbered decision log (decision → rationale), the top "
        "open risks with mitigations, and a phased delivery roadmap. Be decisive.",
    )

    review.cache_read_tokens = engine.cache_read_tokens
    await engine.emit(
        RunEvent("phase", "Architecture complete", phase="done",
                 data={"phase": "design"})
    )
    return review


def _files_as_text(files: list[GeneratedFile], char_budget: int = 60_000) -> str:
    """Render generated files as context for the QA engineer, within a budget."""
    parts: list[str] = []
    used = 0
    for f in files:
        header = f"\n### `{f.path}`\n```\n"
        body = f.content
        chunk = header + body + "\n```\n"
        if used + len(chunk) > char_budget:
            remaining = max(0, char_budget - used - len(header) - 16)
            chunk = header + body[:remaining] + "\n… (truncated)\n```\n"
            parts.append(chunk)
            break
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts)


def _plan_as_text(plan: BuildPlan) -> str:
    stack = "\n".join(f"- {c.component}: {c.choice}" for c in plan.stack)
    manifest = "\n".join(f"- `{f.path}` ({f.area}) — {f.purpose}" for f in plan.files)
    return (
        f"# Build plan\n\n## Summary\n{plan.summary}\n\n"
        f"## Stack\n{stack}\n\n## File manifest\n{manifest}\n\n"
        f"## How to run\n{plan.run_instructions}\n"
    )


async def _run_engineering(
    brief: str, review: ArchitectureReview, engine: _Engine
) -> GeneratedSolution:
    solution = GeneratedSolution()
    await engine.emit(
        RunEvent("phase", "Building the end-to-end solution", phase="start",
                 data={"phase": "engineering"})
    )

    design_context = (
        f"{_format_brief(brief)}\n"
        f"# Agreed architecture\n\n{review.final_document}\n"
    )

    # Tech Lead → build plan.
    plan_data = await engine.structured(
        TECH_LEAD,
        design_context,
        "Produce the build plan: choose a concrete, conventional stack for a "
        "runnable end-to-end repository (frontend + backend + tests + CI) and a "
        "complete file manifest. Scope it to a coherent vertical slice that "
        "demonstrates the core of the spec end to end. Group files by area "
        "(backend, frontend, tests, ci, docs).",
        BUILD_PLAN_SCHEMA,
    )
    plan = parse_build_plan(plan_data)
    solution.build_plan = plan
    await engine._agent_done(TECH_LEAD, {"files_planned": len(plan.files)})

    # Shared, cached context for the engineers = design + plan.
    eng_context = f"{design_context}\n{_plan_as_text(plan)}"

    async def build(agent: Architect, instruction: str):
        data = await engine.structured(agent, eng_context, instruction, FILE_BUNDLE_SCHEMA)
        bundle = parse_file_bundle(data)
        await engine._agent_done(agent, {"files": len(bundle.files)})
        return bundle

    backend_bundle, frontend_bundle = await asyncio.gather(
        build(
            BACKEND_ENGINEER,
            "Implement every backend and shared-config file from the manifest as "
            "complete, runnable source. Include the dependency manifest. Make the "
            "API contract explicit so the frontend can match it.",
        ),
        build(
            FRONTEND_ENGINEER,
            "Implement every frontend file from the manifest as complete, "
            "runnable source. Call the backend's API exactly as planned, and "
            "handle loading and error states.",
        ),
    )

    code_files = [*backend_bundle.files, *frontend_bundle.files]

    # QA → tests + CI, given the actual code.
    qa_context = (
        f"{eng_context}\n# Implemented source files\n"
        f"{_files_as_text(code_files)}\n"
    )
    qa_data = await engine.structured(
        QA_ENGINEER,
        qa_context,
        "Write the test and CI files from the manifest as complete, runnable "
        "source. Import the actual modules shown above and assert real behavior. "
        "Add a GitHub Actions workflow that installs dependencies and runs both "
        "test suites.",
        FILE_BUNDLE_SCHEMA,
    )
    qa_bundle = parse_file_bundle(qa_data)
    await engine._agent_done(QA_ENGINEER, {"files": len(qa_bundle.files)})

    # Assemble — first writer per path wins; then inject generated docs.
    merged: dict[str, GeneratedFile] = {}
    for f in [*code_files, *qa_bundle.files]:
        merged.setdefault(f.path, f)

    solution.notes = [
        n
        for n in (backend_bundle.notes, frontend_bundle.notes, qa_bundle.notes)
        if n.strip()
    ]

    # Inject the architecture doc and a solution overview (don't clobber).
    docs = {
        "docs/ARCHITECTURE.md": report.render_markdown(review),
        "SOLUTION.md": report.render_solution_overview(
            plan, solution.notes, list(merged)
        ),
    }
    for path, content in docs.items():
        merged.setdefault(path, GeneratedFile(path=path, content=content))

    solution.files = list(merged.values())

    await engine.emit(
        RunEvent(
            "files",
            f"Generated {len(solution.files)} files.",
            data={"count": len(solution.files), "paths": list(merged)},
        )
    )
    await engine.emit(
        RunEvent("phase", "Solution build complete", phase="done",
                 data={"phase": "engineering"})
    )
    return solution


# --- Public API -------------------------------------------------------------


async def run_pipeline(
    brief: str,
    *,
    build: bool = True,
    settings: Settings | None = None,
    client: AsyncAnthropic | None = None,
    hook: EventHook | None = None,
) -> RunResult:
    """Run the design phase and (optionally) the engineering phase."""
    settings = settings or Settings()
    settings.validate()
    owns_client = client is None
    client = client or build_client()
    engine = _Engine(client, settings, hook or noop_hook)

    try:
        review = await _run_design(brief, engine)
        solution = await _run_engineering(brief, review, engine) if build else None
        result = RunResult(
            brief=brief.strip(),
            review=review,
            solution=solution,
            cache_read_tokens=engine.cache_read_tokens,
        )
        await engine.emit(
            RunEvent("complete", "Run complete.",
                     data={"cache_read_tokens": engine.cache_read_tokens})
        )
        return result
    finally:
        if owns_client:
            await client.close()


async def run_review(
    brief: str,
    *,
    settings: Settings | None = None,
    client: AsyncAnthropic | None = None,
    hook: EventHook | None = None,
) -> ArchitectureReview:
    """Design-only convenience wrapper (no code generation)."""
    result = await run_pipeline(
        brief, build=False, settings=settings, client=client, hook=hook
    )
    return result.review
