"""In-memory run store with replayable SSE event streams.

A single-process store: each run buffers its events so a browser that subscribes
late (SSE has no replay) still receives the full history before tailing live
events. For multi-worker deployments this would move to Redis pub/sub; for the
single-uvicorn-worker default it is exactly what we need.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic

from architects.agents import AGENTS
from architects.config import Settings
from architects.events import RunEvent
from architects.orchestrator import RunResult, run_pipeline

# Sentinel pushed to subscriber queues to signal end-of-stream.
_DONE = object()


@dataclass
class Run:
    id: str
    spec: str
    build: bool
    effort: str | None
    status: str = "pending"  # pending | running | succeeded | failed
    created_at: float = field(default_factory=time.time)
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    result: RunResult | None = None
    error: str | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)


def _agent_meta(key: str | None) -> dict[str, str]:
    agent = AGENTS.get(key or "")
    if agent is None:
        return {}
    return {"title": agent.title, "emoji": agent.emoji}


class RunStore:
    def __init__(self, client: AsyncAnthropic | None = None) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = asyncio.Lock()
        self._client = client

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    async def _publish(self, run: Run, event: dict[str, Any]) -> None:
        async with self._lock:
            run.events.append(event)
            for queue in run.subscribers:
                queue.put_nowait(event)

    async def subscribe(self, run: Run) -> asyncio.Queue:
        """Return a queue preloaded with buffered events, then live ones."""
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            for event in run.events:
                queue.put_nowait(event)
            if run.done.is_set():
                queue.put_nowait(_DONE)
            else:
                run.subscribers.append(queue)
        return queue

    async def _unsubscribe(self, run: Run, queue: asyncio.Queue) -> None:
        async with self._lock:
            if queue in run.subscribers:
                run.subscribers.remove(queue)

    def create(self, spec: str, *, build: bool, effort: str | None) -> Run:
        run = Run(id=uuid.uuid4().hex, spec=spec, build=build, effort=effort)
        self._runs[run.id] = run
        return run

    async def start(self, run: Run) -> None:
        """Launch the pipeline for a run as a background task."""
        asyncio.create_task(self._execute(run))

    async def _execute(self, run: Run) -> None:
        run.status = "running"

        async def hook(event: RunEvent) -> None:
            payload = event.to_dict()
            payload["agent_meta"] = _agent_meta(event.agent)
            await self._publish(run, payload)

        settings = Settings(effort=run.effort) if run.effort else Settings()
        try:
            settings.validate()
            run.result = await run_pipeline(
                run.spec,
                build=run.build,
                settings=settings,
                client=self._client,  # share the app-wide client if provided
                hook=hook,
            )
            run.status = "succeeded"
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            run.status = "failed"
            run.error = str(exc)
            await self._publish(
                run, RunEvent("error", f"Run failed: {exc}").to_dict()
            )
        finally:
            # Close every subscriber stream.
            async with self._lock:
                run.done.set()
                for queue in run.subscribers:
                    queue.put_nowait(_DONE)
                run.subscribers.clear()


def is_done_sentinel(item: Any) -> bool:
    return item is _DONE
