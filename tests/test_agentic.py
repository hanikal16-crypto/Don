"""Offline tests for the autonomous toolset and agent loop (no network)."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from architects.agents import BACKEND_ENGINEER  # noqa: E402
from architects.agent_loop import run_agent  # noqa: E402
from architects.config import Settings  # noqa: E402
from architects.events import RunEvent  # noqa: E402
from architects.tools import Workspace, dispatch  # noqa: E402


# --- Workspace tools --------------------------------------------------------


def test_workspace_write_read_list():
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        ws.write_file("pkg/app.py", "print('hi')")
        assert ws.read_file("pkg/app.py") == "print('hi')"
        listing = ws.list_dir("pkg")
        assert "app.py" in listing


def test_workspace_blocks_escape():
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        try:
            ws.write_file("../escape.py", "x")
        except ValueError:
            return
        raise AssertionError("expected ValueError for path escape")


def test_workspace_run_command():
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d, allow_bash=True)
        out = ws.run_command("echo hello-from-agent")
        assert "exit=0" in out and "hello-from-agent" in out


def test_workspace_run_command_disabled():
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d, allow_bash=False)
        out = ws.run_command("echo nope")
        assert "disabled" in out.lower()


def test_workspace_snapshot_skips_junk():
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        ws.write_file("src/main.py", "x = 1")
        ws.write_file("node_modules/junk.js", "should be skipped")
        paths = {f.path for f in ws.snapshot()}
        assert "src/main.py" in paths
        assert "node_modules/junk.js" not in paths


def test_dispatch_unknown_tool_is_error():
    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        result, is_error = dispatch(ws, "frobnicate", {})
        assert is_error and "unknown tool" in result.lower()


# --- Agent loop with a fake client -----------------------------------------


def _block(**kw):
    return types.SimpleNamespace(**kw)


class _FakeStream:
    def __init__(self, message):
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self._message


class _FakeMessages:
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = 0

    def stream(self, **_kwargs):
        msg = self._scripted[self.calls]
        self.calls += 1
        return _FakeStream(msg)


class _FakeClient:
    def __init__(self, scripted):
        self.messages = _FakeMessages(scripted)


def test_agent_loop_executes_tools_then_finishes():
    scripted = [
        # Turn 1: write a file.
        types.SimpleNamespace(
            stop_reason="tool_use",
            usage=None,
            content=[
                _block(
                    type="tool_use",
                    id="t1",
                    name="write_file",
                    input={"path": "main.py", "content": "print('hi')"},
                )
            ],
        ),
        # Turn 2: run it.
        types.SimpleNamespace(
            stop_reason="tool_use",
            usage=None,
            content=[
                _block(
                    type="tool_use",
                    id="t2",
                    name="run_command",
                    input={"command": "echo ran"},
                )
            ],
        ),
        # Turn 3: done.
        types.SimpleNamespace(
            stop_reason="end_turn",
            usage=None,
            content=[_block(type="text", text="Built and verified.")],
        ),
    ]

    events: list[RunEvent] = []

    async def hook(ev: RunEvent) -> None:
        events.append(ev)

    with tempfile.TemporaryDirectory() as d:
        ws = Workspace(d)
        summary, cache = asyncio.run(
            run_agent(
                _FakeClient(scripted),
                Settings(),
                BACKEND_ENGINEER,
                "shared context",
                "build it",
                ws,
                hook=hook,
            )
        )
        assert summary == "Built and verified."
        assert ws.read_file("main.py") == "print('hi')"
        # Two tool events + start + done.
        tool_events = [e for e in events if e.type == "tool"]
        assert len(tool_events) == 2
        assert any(e.phase == "start" for e in events if e.type == "agent")
        assert any(e.phase == "done" for e in events if e.type == "agent")


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✅ {fn.__name__}")
    print(f"\n{len(fns)} agentic tests passed.")


if __name__ == "__main__":
    _run_all()
