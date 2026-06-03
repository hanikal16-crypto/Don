"""Offline tests for the FastAPI backend, using a fake pipeline (no network)."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from architects.codegen import BuildPlan, GeneratedFile  # noqa: E402
from architects.events import RunEvent  # noqa: E402
from architects.orchestrator import (  # noqa: E402
    ArchitectureReview,
    GeneratedSolution,
    RunResult,
)


async def _fake_pipeline(brief, *, build, settings, client, hook):
    await hook(RunEvent("phase", "Designing", phase="start"))
    await hook(RunEvent("agent", "Solution working", agent="solution", phase="start"))
    await hook(RunEvent("agent", "Solution done", agent="solution", phase="done"))
    review = ArchitectureReview(
        brief=brief, final_document="# Architecture\n\nIt works."
    )
    solution = None
    if build:
        solution = GeneratedSolution(
            build_plan=BuildPlan(
                summary="A demo app.",
                stack=[],
                files=[],
                run_instructions="uvicorn app:app",
            ),
            files=[GeneratedFile(path="app/main.py", content="print('hi')")],
            notes=["built"],
        )
    await hook(RunEvent("complete", "Run complete."))
    return RunResult(
        brief=brief, review=review, solution=solution, cache_read_tokens=42
    )


def _client(monkeypatch=None):
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    import server.runstore as runstore

    runstore.run_pipeline = _fake_pipeline  # patch out the network
    from fastapi.testclient import TestClient

    import server.app as appmod

    return TestClient(appmod.app)


def test_agents_endpoint():
    with _client() as client:
        data = client.get("/api/agents").json()
        assert len(data["architects"]) == 5
        assert len(data["engineers"]) == 4


def test_full_run_flow():
    with _client() as client:
        # Start a run.
        res = client.post("/api/runs", json={"spec": "Build a thing.", "build": True})
        assert res.status_code == 200
        run_id = res.json()["run_id"]

        # Stream events to completion (this also drives the background task).
        saw_end = False
        saw_agent = False
        with client.stream("GET", f"/api/runs/{run_id}/events") as r:
            for line in r.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                event = json.loads(line[len("data:") :].strip())
                if event.get("type") == "agent":
                    saw_agent = True
                if event.get("type") == "end":
                    saw_end = True
                    break
        assert saw_agent and saw_end

        # Status + artifacts.
        info = client.get(f"/api/runs/{run_id}").json()
        assert info["status"] == "succeeded"
        assert info["has_review"] and info["has_solution"]
        assert info["cache_read_tokens"] == 42

        md = client.get(f"/api/runs/{run_id}/result.md")
        assert md.status_code == 200 and "Architecture" in md.text

        zip_res = client.get(f"/api/runs/{run_id}/download.zip")
        assert zip_res.status_code == 200
        assert zip_res.headers["content-type"] == "application/zip"


def test_missing_run_404():
    with _client() as client:
        assert client.get("/api/runs/nope").status_code == 404


def test_empty_spec_rejected():
    with _client() as client:
        assert client.post("/api/runs", json={"spec": "   "}).status_code == 400


def _run_all():
    fns = [
        v for k, v in globals().items() if k.startswith("test_") and callable(v)
    ]
    for fn in fns:
        fn()
        print(f"  ✅ {fn.__name__}")
    print(f"\n{len(fns)} server tests passed.")


if __name__ == "__main__":
    _run_all()
