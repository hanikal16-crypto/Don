"""Client-side tools that let an agent act on a real workspace.

The engineering agents drive an autonomous loop: they read, write, list, and
run code in a workspace directory and iterate on failures — like a developer.
File operations are confined to the workspace root; ``run_command`` executes
in that directory.

Security note: ``run_command`` runs arbitrary shell commands with the host's
privileges. That is the point (the agent builds and debugs real code), but it
means you should run the platform in a disposable container. Set
``ARCHITECT_DISABLE_BASH=1`` to turn command execution off (the agent can still
read/write files but cannot run them).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from architects.codegen import GeneratedFile, safe_relpath

# Directories and files not worth snapshotting back out of the workspace.
_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".next",
    "target",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".gradle",
    "coverage",
}
_MAX_FILE_BYTES = 256 * 1024
_MAX_OUTPUT_CHARS = 8000


class Workspace:
    """A sandboxed working directory for an agent's tools."""

    def __init__(
        self,
        root: str | Path,
        *,
        allow_bash: bool = True,
        bash_timeout: int = 180,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.allow_bash = allow_bash
        self.bash_timeout = bash_timeout

    def _resolve(self, rel: str) -> Path:
        target = (self.root / safe_relpath(rel)).resolve()
        if not str(target).startswith(str(self.root)):
            raise ValueError(f"Path escapes the workspace: {rel!r}")
        return target

    # --- tool implementations ---------------------------------------------

    def write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            return f"Error: no such file: {path}"
        return target.read_text(encoding="utf-8", errors="replace")

    def list_dir(self, path: str = ".") -> str:
        target = self._resolve(path) if path not in ("", ".") else self.root
        if not target.exists():
            return f"Error: no such directory: {path}"
        entries = []
        for child in sorted(target.iterdir()):
            if child.name in _SKIP_DIRS:
                entries.append(f"{child.name}/ (skipped)")
            elif child.is_dir():
                entries.append(f"{child.name}/")
            else:
                entries.append(child.name)
        return "\n".join(entries) or "(empty)"

    def run_command(self, command: str) -> str:
        if not self.allow_bash:
            return (
                "Error: command execution is disabled "
                "(ARCHITECT_DISABLE_BASH is set). You can read/write files but "
                "cannot run commands."
            )
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=self.bash_timeout,
            )
        except subprocess.TimeoutExpired:
            return f"Error: command timed out after {self.bash_timeout}s: {command}"
        out = (proc.stdout or "") + (
            f"\n[stderr]\n{proc.stderr}" if proc.stderr else ""
        )
        out = out.strip()
        if len(out) > _MAX_OUTPUT_CHARS:
            out = out[:_MAX_OUTPUT_CHARS] + "\n… (output truncated)"
        return f"exit={proc.returncode}\n{out}" if out else f"exit={proc.returncode}"

    # --- snapshot ----------------------------------------------------------

    def snapshot(self) -> list[GeneratedFile]:
        """Read every (text, in-budget) file back out as GeneratedFiles."""
        files: list[GeneratedFile] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # skip binaries / unreadable files
            files.append(GeneratedFile(path=rel.as_posix(), content=content))
        return files


# --- Tool schemas + dispatch ------------------------------------------------

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "write_file",
        "description": "Create or overwrite a file in the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative path."},
                "content": {"type": "string", "description": "Full file contents."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "list_dir",
        "description": "List the contents of a workspace directory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Defaults to the root."}
            },
            "required": [],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run a shell command in the workspace (install deps, run tests, etc.). "
            "Use this to verify your work and debug failures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]


def dispatch(workspace: Workspace, name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute a tool call; return (result_text, is_error)."""
    try:
        if name == "write_file":
            return workspace.write_file(tool_input["path"], tool_input["content"]), False
        if name == "read_file":
            return workspace.read_file(tool_input["path"]), False
        if name == "list_dir":
            return workspace.list_dir(tool_input.get("path", ".")), False
        if name == "run_command":
            return workspace.run_command(tool_input["command"]), False
        return f"Error: unknown tool {name!r}", True
    except Exception as exc:  # noqa: BLE001 - surface to the model so it can adapt
        return f"Error running {name}: {exc}", True


def tool_brief(name: str, tool_input: dict) -> str:
    """A short human-readable description of a tool call, for progress logs."""
    if name == "run_command":
        return f"$ {tool_input.get('command', '')}"
    if name in ("write_file", "read_file"):
        return f"{name} {tool_input.get('path', '')}"
    if name == "list_dir":
        return f"list_dir {tool_input.get('path', '.')}"
    return name
