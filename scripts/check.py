"""Run the verified gate: ruff lint, format check, mypy, pytest.

Usage:
    uv run python scripts/check.py
"""

from __future__ import annotations

import subprocess
import sys

COMMANDS: list[list[str]] = [
    ["ruff", "check", "."],
    ["ruff", "format", "--check", "."],
    ["mypy"],
    ["pytest"],
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
