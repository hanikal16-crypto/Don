"""Offline tests for code generation models, path safety, and packaging."""

from __future__ import annotations

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from architects.agents import AGENTS, ENGINEERS  # noqa: E402
from architects.codegen import (  # noqa: E402
    GeneratedFile,
    parse_build_plan,
    parse_file_bundle,
    safe_relpath,
    write_solution,
    zip_solution,
)


def test_engineering_crew_present():
    keys = {a.key for a in ENGINEERS}
    assert keys == {"techlead", "backend", "frontend", "qa"}
    # AGENTS combines architects + engineers.
    assert len(AGENTS) == 9


def test_safe_relpath_normalizes_and_blocks_traversal():
    assert safe_relpath("/backend/app.py") == "backend/app.py"
    assert safe_relpath("a/b/../c.py") == "a/c.py"
    for bad in ["../../etc/passwd", "/etc/passwd/../../x", "..", "C:/Windows/x"]:
        try:
            result = safe_relpath(bad)
        except ValueError:
            continue
        # If it didn't raise, it must at least not escape the root.
        assert not result.startswith("..") and not result.startswith("/"), bad


def test_parse_file_bundle_sanitizes_paths():
    bundle = parse_file_bundle(
        {
            "files": [
                {"path": "/backend/main.py", "content": "x = 1"},
                {"path": "  ", "content": "ignored"},  # blank path dropped
            ],
            "notes": "ok",
        }
    )
    assert len(bundle.files) == 1
    assert bundle.files[0].path == "backend/main.py"
    assert bundle.notes == "ok"


def test_parse_build_plan():
    plan = parse_build_plan(
        {
            "summary": "A small app.",
            "stack": [{"component": "backend", "choice": "FastAPI"}],
            "files": [
                {"path": "backend/main.py", "area": "backend", "purpose": "entry"}
            ],
            "run_instructions": "uvicorn ...",
        }
    )
    assert plan.stack[0].choice == "FastAPI"
    assert plan.files[0].area == "backend"


def test_zip_solution_roundtrips():
    files = [
        GeneratedFile(path="backend/main.py", content="print('hi')"),
        GeneratedFile(path="frontend/index.html", content="<h1>hi</h1>"),
    ]
    data = zip_solution(files)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert names == {"backend/main.py", "frontend/index.html"}
        assert zf.read("backend/main.py").decode() == "print('hi')"


def test_write_solution_writes_files(tmp_path=None):
    import tempfile

    files = [GeneratedFile(path="a/b/c.txt", content="hello")]
    with tempfile.TemporaryDirectory() as d:
        root = write_solution(files, d)
        assert (root / "a" / "b" / "c.txt").read_text() == "hello"


def _run_all():
    fns = [
        v
        for k, v in globals().items()
        if k.startswith("test_") and callable(v)
    ]
    for fn in fns:
        fn()
        print(f"  ✅ {fn.__name__}")
    print(f"\n{len(fns)} codegen tests passed.")


if __name__ == "__main__":
    _run_all()
