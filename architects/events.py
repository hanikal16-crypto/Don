"""Progress events emitted during a run.

A single richer event type replaces the old (key, phase) progress hook so the
CLI, the web backend (SSE), and tests can all consume the same stream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class RunEvent:
    """One progress event from the pipeline."""

    type: str  # phase | agent | files | log | complete | error
    message: str
    agent: str | None = None
    phase: str | None = None  # start | done
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "message": self.message,
            "agent": self.agent,
            "phase": self.phase,
            "data": self.data,
        }


# A progress sink: receives each event as it happens.
EventHook = Callable[[RunEvent], Awaitable[None]]


async def noop_hook(_event: RunEvent) -> None:
    return None
