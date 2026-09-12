"""Export the live FastAPI OpenAPI schema for the web client.

The FastAPI app is the executable API contract; ``docs/api/openapi.yaml`` is
legacy hand-maintained documentation. ``--check`` verifies the checked-in JSON
is current (CI drift gate).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = REPO_ROOT / "docs" / "api" / "openapi.json"


def render() -> str:
    from hr_agents.main import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the checked-in file differs")
    parser.add_argument("--output", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args(argv)

    rendered = render()
    if args.check:
        existing = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if existing != rendered:
            print(f"{args.output} is stale: run scripts/export_openapi.py", file=sys.stderr)
            return 1
        print(f"{args.output} is current")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
