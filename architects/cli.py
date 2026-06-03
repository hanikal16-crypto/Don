"""Command-line interface for the Agentic Architects.

Examples:
    # Design + build a full e2e repo into ./output/<name>/
    python -m architects "Design a multi-tenant SaaS for real-time analytics."

    # Design only (no code generation)
    python -m architects --no-build --brief-file examples/brief-analytics-saas.md

    # Pick where the generated repo and the architecture doc go
    python -m architects --brief-file spec.md --out-dir build/myapp --report review.md
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from architects.agents import AGENTS
from architects.codegen import write_solution
from architects.config import Settings
from architects.events import RunEvent
from architects.orchestrator import run_pipeline
from architects.report import render_markdown


def _read_brief(args: argparse.Namespace) -> str:
    if args.brief_file:
        return Path(args.brief_file).read_text(encoding="utf-8")
    if args.brief:
        return args.brief
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit(
        "No spec provided. Pass it as an argument, via --brief-file, or on stdin."
    )


def _make_hook(stream=sys.stderr):
    async def hook(event: RunEvent) -> None:
        if event.type == "phase":
            mark = "✓" if event.phase == "done" else "▶"
            print(f"\n{mark} {event.message}", file=stream, flush=True)
        elif event.type == "agent":
            agent = AGENTS.get(event.agent or "")
            emoji = agent.emoji if agent else "•"
            if event.phase == "start":
                print(f"   {emoji}  {event.message}", file=stream, flush=True)
            else:
                extra = ""
                if event.data.get("files"):
                    extra = f" ({event.data['files']} files)"
                elif event.data.get("files_planned"):
                    extra = f" ({event.data['files_planned']} files planned)"
                print(f"   ✅  {event.message}{extra}", file=stream, flush=True)
        elif event.type == "files":
            print(f"   📦  {event.message}", file=stream, flush=True)
        elif event.type == "error":
            print(f"   ⚠️  {event.message}", file=stream, flush=True)

    return hook


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="architects",
        description=(
            "Design (5 architects) and build (engineering crew) an end-to-end "
            "solution from a specification."
        ),
    )
    parser.add_argument("brief", nargs="?", help="The specification text.")
    parser.add_argument("--brief-file", help="Path to a file containing the spec.")
    parser.add_argument(
        "--build",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate the end-to-end repo (default: on; use --no-build for "
        "design only).",
    )
    parser.add_argument(
        "--out-dir",
        default="output/solution",
        help="Where to write the generated repo (default: output/solution).",
    )
    parser.add_argument(
        "--report",
        help="Also write the architecture document (markdown) to this path.",
    )
    parser.add_argument("--model", help="Override the Claude model.")
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="Override thinking effort (default: high).",
    )
    args = parser.parse_args(argv)

    brief = _read_brief(args).strip()
    if not brief:
        raise SystemExit("The spec is empty.")

    base = Settings()
    settings = Settings(
        model=args.model or base.model,
        effort=args.effort or base.effort,
    )

    print("\n🏛️  Agentic Architects — designing", end="", file=sys.stderr)
    print(" and building your solution\n" if args.build else " your architecture\n",
          file=sys.stderr)

    try:
        result = await run_pipeline(
            brief, build=args.build, settings=settings, hook=_make_hook()
        )
    except RuntimeError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    # Architecture document.
    report_md = render_markdown(result.review)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(report_md, encoding="utf-8")
        print(f"\n📄  Architecture written to {args.report}", file=sys.stderr)
    elif not args.build:
        print("\n" + report_md)

    # Generated repo.
    if result.solution and result.solution.files:
        out_dir = write_solution(result.solution.files, args.out_dir)
        print(
            f"\n📦  Generated {len(result.solution.files)} files in {out_dir}/",
            file=sys.stderr,
        )
        if result.solution.build_plan:
            print("    Run instructions are in SOLUTION.md.", file=sys.stderr)

    if result.cache_read_tokens:
        print(
            f"\n♻️  Reused {result.cache_read_tokens:,} cached input tokens.",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return asyncio.run(_amain(argv))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
