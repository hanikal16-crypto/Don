"""Low-level Claude calls shared by the orchestrator and codegen.

Two call shapes, both streamed (so large `max_tokens` stays under the SDK's
HTTP timeout):

- `run_text`        -> free-form prose (architecture sections, synthesis)
- `run_structured`  -> JSON validated against a json_schema (build plan, files)

Each returns the value plus the number of cache-read input tokens, so callers
can report prompt-cache reuse.
"""

from __future__ import annotations

import json
from typing import Any

from anthropic import AsyncAnthropic

from architects.config import Settings


def build_system(shared_context: str, persona: str) -> list[dict]:
    """System blocks: a cached shared-context block, then the agent persona.

    Keeping the shared block byte-identical across agents lets the prompt cache
    serve it once instead of re-billing it per agent.
    """
    return [
        {
            "type": "text",
            "text": shared_context,
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": persona},
    ]


def _cache_read(message: Any) -> int:
    usage = getattr(message, "usage", None)
    if usage is None:
        return 0
    return getattr(usage, "cache_read_input_tokens", 0) or 0


def _text_of(message: Any) -> str:
    return "".join(
        block.text for block in message.content if block.type == "text"
    ).strip()


async def run_text(
    client: AsyncAnthropic,
    settings: Settings,
    system: list[dict],
    instruction: str,
) -> tuple[str, int]:
    async with client.messages.stream(
        model=settings.model,
        max_tokens=settings.max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": settings.effort},
        system=system,
        messages=[{"role": "user", "content": instruction}],
    ) as stream:
        message = await stream.get_final_message()
    return _text_of(message), _cache_read(message)


async def run_structured(
    client: AsyncAnthropic,
    settings: Settings,
    system: list[dict],
    instruction: str,
    schema: dict,
    *,
    max_tokens: int | None = None,
) -> tuple[dict, int]:
    async with client.messages.stream(
        model=settings.model,
        max_tokens=max_tokens or settings.max_tokens,
        thinking={"type": "adaptive"},
        output_config={
            "effort": settings.effort,
            "format": {"type": "json_schema", "schema": schema},
        },
        system=system,
        messages=[{"role": "user", "content": instruction}],
    ) as stream:
        message = await stream.get_final_message()

    text = _text_of(message)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - model-dependent
        raise ValueError(
            f"Expected JSON from the model but could not parse it: {exc}"
        ) from exc
    return data, _cache_read(message)
