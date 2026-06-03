"""Offline tests — no API key or network required.

Run with: python -m pytest   (or: python tests/test_offline.py)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from architects.agents import ARCHITECTS, DOMAIN_ARCHITECTS  # noqa: E402
from architects.config import Settings  # noqa: E402
from architects.orchestrator import ArchitectureReview  # noqa: E402
from architects.report import render_markdown  # noqa: E402


def test_five_architects_present():
    expected = {"solution", "data", "security", "observability", "cloud"}
    assert set(ARCHITECTS) == expected
    assert len(DOMAIN_ARCHITECTS) == 4


def test_every_architect_has_a_system_prompt():
    for agent in ARCHITECTS.values():
        assert agent.system_prompt.strip(), f"{agent.key} missing system prompt"
        assert agent.title and agent.emoji and agent.remit


def test_settings_validate_rejects_bad_effort(monkeypatch=None):
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    try:
        Settings(effort="ludicrous").validate()
    except RuntimeError as exc:
        assert "effort" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError for bad effort")
    finally:
        os.environ.pop("ANTHROPIC_API_KEY", None)


def test_settings_validate_requires_api_key():
    os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        Settings().validate()
    except RuntimeError as exc:
        assert "ANTHROPIC_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RuntimeError for missing key")


def test_render_markdown_includes_all_sections():
    review = ArchitectureReview(brief="Build a thing.")
    review.high_level_design = "HLD here."
    review.final_document = "Final doc here."
    review.sections = {a.key: f"{a.title} content" for a in DOMAIN_ARCHITECTS}

    md = render_markdown(review)

    assert "# Architecture Review" in md
    assert "Build a thing." in md
    assert "Final doc here." in md
    for agent in DOMAIN_ARCHITECTS:
        assert agent.title in md


def test_render_markdown_handles_missing_sections():
    review = ArchitectureReview(brief="Brief.")
    md = render_markdown(review)
    assert "_(not generated)_" in md  # graceful placeholder


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✅ {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")


if __name__ == "__main__":
    _run_all()
