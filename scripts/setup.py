"""Create the first-run configuration file.

Writes `.env` with one role-bound admin principal, the operator's name, the
business timezone, and the offline model default. Nothing here needs a running
database; start the stack afterwards with ``docker compose up --build``.

    uv run python scripts/setup.py

The generated key is printed once. Paste it into the dashboard sign-in.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hr_agents.setup import (
    DEFAULT_APP_NAME,
    DEFAULT_LLM_MODEL,
    DEFAULT_STORE_BACKEND,
    DEFAULT_TIMEZONE,
    generate_api_key,
    render_env,
    write_env,
)


def _ask(label: str, default: str) -> str:
    answer = input(f"{label} [{default}]: ").strip()
    return answer or default


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the HRAgents first-run .env")
    parser.add_argument("--operator", help="the person who runs this install")
    parser.add_argument("--app-name", help=f"dashboard title (default: {DEFAULT_APP_NAME})")
    parser.add_argument("--timezone", help=f"business timezone (default: {DEFAULT_TIMEZONE})")
    parser.add_argument(
        "--store-backend",
        choices=["postgres", "memory"],
        help=f"persistence backend (default: {DEFAULT_STORE_BACKEND})",
    )
    parser.add_argument(
        "--llm-model",
        help=f"model string; 'test' runs fully offline (default: {DEFAULT_LLM_MODEL})",
    )
    parser.add_argument("--api-key", help="use a specific key instead of generating one")
    parser.add_argument("--env-file", default=".env", help="output path (default: .env)")
    parser.add_argument("--force", action="store_true", help="replace an existing .env")
    args = parser.parse_args()

    operator = args.operator or _ask("Operator name", "")
    if not operator.strip():
        print("error: an operator name is required; the audit chain needs a person.")
        return 2
    app_name = args.app_name or _ask("App name", DEFAULT_APP_NAME)
    timezone = args.timezone or _ask("Business timezone", DEFAULT_TIMEZONE)
    store_backend = args.store_backend or _ask(
        "Store backend (postgres/memory)", DEFAULT_STORE_BACKEND
    )
    llm_model = args.llm_model or _ask("LLM model ('test' runs fully offline)", DEFAULT_LLM_MODEL)
    api_key = args.api_key or generate_api_key()

    try:
        content = render_env(
            operator=operator,
            api_key=api_key,
            app_name=app_name,
            timezone=timezone,
            store_backend=store_backend,
            llm_model=llm_model,
        )
    except ValueError as exc:
        print(f"error: {exc}")
        return 2

    path = Path(args.env_file)
    try:
        write_env(path, content, force=args.force)
    except FileExistsError as exc:
        print(f"error: {exc}")
        return 1

    print(f"Wrote {path} for {operator.strip()} ({timezone}, {store_backend}).")
    print(f"Dashboard API key (shown once): {api_key}")
    print()
    print("Next:")
    print("  docker compose up --build")
    print("  open http://localhost:8000/app and paste the key")
    print("  optional starter content:")
    print("    docker compose exec api uv run python scripts/seed_starters.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
