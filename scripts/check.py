"""Run the verified gate: ruff lint, format check, mypy, pytest with coverage.

Usage:
    uv run python scripts/check.py

The pytest invocation carries the same coverage floor CI enforces, so the local
gate cannot pass what CI fails.
"""

from __future__ import annotations

import subprocess
import sys

COMMANDS: list[list[str]] = [
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."],
    ["mypy"],
    ["pytest", "--cov", "--cov-report=term-missing", "--cov-fail-under=90"],
]


def main() -> int:
    for command in COMMANDS:
        print(f"\n==> {' '.join(command)}", flush=True)
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
