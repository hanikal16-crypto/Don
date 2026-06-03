"""Run every offline test module without needing pytest.

    python tests/run_all.py
"""

from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MODULES = ["tests.test_offline", "tests.test_codegen", "tests.test_server"]


def main() -> int:
    for name in MODULES:
        print(f"\n=== {name} ===")
        module = importlib.import_module(name)
        module._run_all()
    print("\nAll offline test modules passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
