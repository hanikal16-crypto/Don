"""FastAPI backend for the Agentic Architects platform.

Run it with:
    uvicorn server.app:app --reload

Endpoints:
    GET  /                         -> the SPA
    GET  /api/agents               -> the agent roster (for UI labels)
    POST /api/runs                 -> start a run, returns {run_id}
    GET  /api/runs/{id}            -> run status + summary
    GET  /api/runs/{id}/events     -> SSE progress stream
    GET  /api/runs/{id}/result.md  -> architecture document (markdown)
    GET  /api/runs/{id}/solution.md-> generated-solution overview (markdown)
    GET  /api/runs/{id}/files      -> list of generated file paths
    GET  /api/runs/{id}/download.zip -> the generated repo as a zip
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from architects.agents import ALL_ARCHITECTS, ENGINEERS
from architects.codegen import zip_solution
from architects.config import build_client
from architects.report import render_markdown, render_solution_overview
from server.runstore import Run, RunStore, is_done_sentinel

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Share one client across runs (connection pool + prompt cache) when a key
    # is available; otherwise let each run build its own and fail with a clear
    # message via Settings.validate().
    client = build_client() if os.getenv("ANTHROPIC_API_KEY") else None
    app.state.store = RunStore(client=client)
    try:
        yield
    finally:
        if client is not None:
            await client.close()


app = FastAPI(title="Agentic Architects", lifespan=lifespan)


class CreateRunRequest(BaseModel):
    spec: str = Field(..., min_length=1)
    build: bool = True
    effort: str | None = None


def _store() -> RunStore:
    return app.state.store


def _require_run(run_id: str) -> Run:
    run = _store().get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.get("/api/agents")
async def agents() -> dict:
    def shape(group):
        return [
            {"key": a.key, "title": a.title, "emoji": a.emoji, "remit": a.remit}
            for a in group
        ]

    return {"architects": shape(ALL_ARCHITECTS), "engineers": shape(ENGINEERS)}


@app.post("/api/runs")
async def create_run(req: CreateRunRequest) -> dict:
    spec = req.spec.strip()
    if not spec:
        raise HTTPException(status_code=400, detail="spec is empty")
    run = _store().create(spec, build=req.build, effort=req.effort)
    await _store().start(run)
    return {"run_id": run.id}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = _require_run(run_id)
    files: list[str] = []
    has_solution = False
    if run.result and run.result.solution:
        files = [f.path for f in run.result.solution.files]
        has_solution = True
    return {
        "id": run.id,
        "status": run.status,
        "build": run.build,
        "error": run.error,
        "has_review": bool(run.result and run.result.review.final_document),
        "has_solution": has_solution,
        "files": sorted(files),
        "cache_read_tokens": run.result.cache_read_tokens if run.result else 0,
    }


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    run = _require_run(run_id)
    store = _store()

    async def gen():
        queue = await store.subscribe(run)
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # heartbeat keeps proxies open
                    continue
                if is_done_sentinel(item):
                    yield f"data: {json.dumps({'type': 'end'})}\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            await store._unsubscribe(run, queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _completed_result(run: Run):
    if run.status != "succeeded" or run.result is None:
        raise HTTPException(status_code=409, detail=f"run is {run.status}")
    return run.result


@app.get("/api/runs/{run_id}/result.md")
async def result_markdown(run_id: str) -> Response:
    result = _completed_result(_require_run(run_id))
    return Response(render_markdown(result.review), media_type="text/markdown")


@app.get("/api/runs/{run_id}/solution.md")
async def solution_markdown(run_id: str) -> Response:
    result = _completed_result(_require_run(run_id))
    if not result.solution or not result.solution.build_plan:
        raise HTTPException(status_code=404, detail="no generated solution")
    md = render_solution_overview(
        result.solution.build_plan,
        result.solution.notes,
        [f.path for f in result.solution.files],
    )
    return Response(md, media_type="text/markdown")


@app.get("/api/runs/{run_id}/files")
async def list_files(run_id: str) -> dict:
    result = _completed_result(_require_run(run_id))
    if not result.solution:
        return {"files": []}
    return {
        "files": [
            {"path": f.path, "bytes": len(f.content.encode("utf-8"))}
            for f in sorted(result.solution.files, key=lambda f: f.path)
        ]
    }


@app.get("/api/runs/{run_id}/download.zip")
async def download_zip(run_id: str) -> Response:
    result = _completed_result(_require_run(run_id))
    if not result.solution or not result.solution.files:
        raise HTTPException(status_code=404, detail="no generated solution")
    data = zip_solution(result.solution.files)
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="solution-{run_id}.zip"'},
    )


# Serve the SPA last so /api/* routes take precedence.
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
