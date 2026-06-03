"""A manual agentic loop: the model drives its own tool use until it's done.

This is the real "agent" tier — the model decides each step (read, write, run,
fix) and we execute its tool calls against a :class:`~architects.tools.Workspace`,
feeding results back until it stops or hits the step budget.
"""

from __future__ import annotations

from typing import Any

from anthropic import AsyncAnthropic

from architects.agents import Architect
from architects.config import Settings
from architects.events import EventHook, RunEvent
from architects.llm import build_system
from architects.tools import TOOL_SCHEMAS, Workspace, dispatch, tool_brief

_TOOL_GUIDANCE = (
    "\n\nYou are working in a real workspace with tools: write_file, read_file, "
    "list_dir, and run_command. Build incrementally and VERIFY your work — "
    "install dependencies and run the code/tests with run_command, read the "
    "output, and fix failures by editing files. Do not claim success until you "
    "have actually run it and seen it pass (or you have exhausted reasonable "
    "attempts). When you are finished, stop and give a one-paragraph summary of "
    "what you built and the final verification status."
)


def _text_of(message: Any) -> str:
    return "".join(b.text for b in message.content if b.type == "text").strip()


async def run_agent(
    client: AsyncAnthropic,
    settings: Settings,
    agent: Architect,
    shared_context: str,
    task: str,
    workspace: Workspace,
    *,
    hook: EventHook,
    max_tokens: int | None = None,
) -> tuple[str, int]:
    """Run one agent to completion in the workspace. Returns (summary, cache_tokens)."""
    await hook(
        RunEvent("agent", f"{agent.title} is working…", agent=agent.key, phase="start")
    )

    system = build_system(shared_context, agent.system_prompt + _TOOL_GUIDANCE)
    messages: list[dict] = [{"role": "user", "content": task}]
    cache_tokens = 0
    steps = 0
    last_text = ""

    for _ in range(settings.max_steps):
        async with client.messages.stream(
            model=settings.model,
            max_tokens=max_tokens or settings.engineering_max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.effort},
            system=system,
            tools=TOOL_SCHEMAS,
            messages=messages,
        ) as stream:
            message = await stream.get_final_message()

        usage = getattr(message, "usage", None)
        if usage is not None:
            cache_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0

        text = _text_of(message)
        if text:
            last_text = text

        # Preserve the full assistant turn (incl. thinking + tool_use blocks).
        messages.append({"role": "assistant", "content": message.content})

        if message.stop_reason == "pause_turn":
            continue  # server-side tool paused; re-send to resume
        if message.stop_reason != "tool_use":
            break  # end_turn / max_tokens / refusal -> done

        tool_results = []
        for block in message.content:
            if block.type != "tool_use":
                continue
            steps += 1
            await hook(
                RunEvent(
                    "tool",
                    f"{agent.title}: {tool_brief(block.name, block.input)}",
                    agent=agent.key,
                    data={"tool": block.name},
                )
            )
            result, is_error = dispatch(workspace, block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                    "is_error": is_error,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    await hook(
        RunEvent(
            "agent",
            f"{agent.title} finished.",
            agent=agent.key,
            phase="done",
            data={"steps": steps},
        )
    )
    return last_text, cache_tokens
