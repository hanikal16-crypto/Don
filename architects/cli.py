"""Command-line interface for the Agentic Architects team.

Examples:
    python -m architects "Design a multi-tenant SaaS for real-time analytics."
    python -m architects --brief-file brief.md --out output/review.md
    echo "Design a URL shortener" | python -m architects
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from architects.agents import ARCHITECTS
from architects.config import Settings
from architects.orchestrator import run_review
from architects.report import render_markdown


def _read_brief(args: argparse.Namespace) -> str:
    if args.brief_file:
        return Path(args.brief_file).read_text(encoding="utf-8")
    if args.brief:
        return args.brief
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit(
        "No brief provided. Pass it as an argument, via --brief-file, or on stdin."
    )


def _make_progress(stream=sys.stderr):
    async def progress(key: str, phase: str) -> None:
        agent = ARCHITECTS[key]
        if phase == "start":
            print(f"  {agent.emoji}  {agent.title} … working", file=stream, flush=True)
        else:
            print(f"  ✅  {agent.title} done", file=stream, flush=True)

    return progress


async def _amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="architects",
        description=(
            "Run a team of five specialized architect agents (Solution, Data, "
            "Security, Observability, Cloud) over a project brief."
        ),
    )
    parser.add_argument("brief", nargs="?", help="The project brief text.")
    parser.add_argument(
        "--brief-file", help="Path to a file containing the project brief."
    )
    parser.add_argument(
        "-o",
        "--out",
        help="Write the Markdown report to this path (default: stdout).",
    )
    parser.add_argument(
        "--model", help="Override the Claude model (default: claude-opus-4-8)."
    )
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="Override thinking effort (default: high).",
    )
    args = parser.parse_args(argv)

    brief = _read_brief(args).strip()
    if not brief:
        raise SystemExit("The brief is empty.")

    settings = Settings(
        model=args.model or Settings().model,
        effort=args.effort or Settings().effort,
    )

    print("\n🏛️  Agentic Architects — reviewing your brief\n", file=sys.stderr)
    try:
        review = await run_review(
            brief, settings=settings, progress=_make_progress()
        )
    except RuntimeError as exc:  # config/usage errors → friendly message
        print(f"\nError: {exc}", file=sys.stderr)
        return 1

    report = render_markdown(review)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"\n📄  Report written to {out_path}", file=sys.stderr)
    else:
        print(report)

    if review.cache_read_tokens:
        print(
            f"\n♻️  Reused {review.cache_read_tokens:,} cached input tokens.",
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
