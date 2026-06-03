"""Models, schemas, and file I/O for the generated end-to-end solution.

The engineering crew returns structured JSON (validated here with Pydantic);
this module also turns the validated files into a directory on disk or an
in-memory zip for download. No network calls live here, so it is fully
unit-testable offline.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from pathlib import Path

from pydantic import BaseModel, Field

# --- Models -----------------------------------------------------------------


class StackChoice(BaseModel):
    component: str
    choice: str


class PlannedFile(BaseModel):
    path: str
    area: str  # backend | frontend | tests | ci | docs
    purpose: str


class BuildPlan(BaseModel):
    summary: str
    stack: list[StackChoice]
    files: list[PlannedFile]
    run_instructions: str


class GeneratedFile(BaseModel):
    path: str
    content: str


class FileBundle(BaseModel):
    files: list[GeneratedFile] = Field(default_factory=list)
    notes: str = ""


# --- JSON schemas for structured outputs ------------------------------------

BUILD_PLAN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "stack": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "component": {"type": "string"},
                    "choice": {"type": "string"},
                },
                "required": ["component", "choice"],
                "additionalProperties": False,
            },
        },
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "area": {"type": "string"},
                    "purpose": {"type": "string"},
                },
                "required": ["path", "area", "purpose"],
                "additionalProperties": False,
            },
        },
        "run_instructions": {"type": "string"},
    },
    "required": ["summary", "stack", "files", "run_instructions"],
    "additionalProperties": False,
}

FILE_BUNDLE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["files", "notes"],
    "additionalProperties": False,
}


# --- Validation -------------------------------------------------------------


def parse_build_plan(data: dict) -> BuildPlan:
    return BuildPlan.model_validate(data)


def parse_file_bundle(data: dict) -> FileBundle:
    bundle = FileBundle.model_validate(data)
    bundle.files = [
        GeneratedFile(path=safe_relpath(f.path), content=f.content)
        for f in bundle.files
        if f.path.strip()
    ]
    return bundle


# --- Path safety + file I/O -------------------------------------------------


def safe_relpath(path: str) -> str:
    """Normalize a model-provided path to a safe, repo-relative POSIX path.

    Strips leading slashes and drive letters, collapses ``..`` traversal, and
    rejects anything that would escape the target directory.
    """
    cleaned = path.strip().replace("\\", "/")
    # Drop a leading drive letter (e.g. "C:/...") and any leading slashes.
    if len(cleaned) > 1 and cleaned[1] == ":":
        cleaned = cleaned[2:]
    cleaned = cleaned.lstrip("/")
    normalized = posixpath.normpath(cleaned)
    if normalized.startswith("..") or normalized == "." or posixpath.isabs(normalized):
        raise ValueError(f"Unsafe file path from model: {path!r}")
    return normalized


def write_solution(files: list[GeneratedFile], dest: str | Path) -> Path:
    """Write generated files under ``dest`` and return the directory."""
    root = Path(dest)
    root.mkdir(parents=True, exist_ok=True)
    for f in files:
        target = root / safe_relpath(f.path)
        # Defense in depth: ensure the resolved path stays inside root.
        if not str(target.resolve()).startswith(str(root.resolve())):
            raise ValueError(f"Refusing to write outside the solution dir: {f.path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, encoding="utf-8")
    return root


def zip_solution(files: list[GeneratedFile]) -> bytes:
    """Pack generated files into an in-memory zip archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.writestr(safe_relpath(f.path), f.content)
    return buffer.getvalue()
