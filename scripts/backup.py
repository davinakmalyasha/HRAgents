"""Backup and restore drill for a self-hosted instance.

A backup is only real if it can be restored, so this script does both: it dumps
Postgres, then (with ``--verify``) restores the dump into a scratch database and
verifies the audit hash chain inside it. Tamper evidence that has not been
checked after a restore is not evidence.

Usage::

    uv run python scripts/backup.py --output backups/
    uv run python scripts/backup.py --output backups/ --verify
    uv run python scripts/backup.py --restore backups/hragents-2026-09-28T03-00-00Z.sql.gz
"""

from __future__ import annotations

import argparse
import gzip
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine

from hr_agents.config import get_settings


@dataclass
class BackupResult:
    path: Path
    bytes_written: int
    created_at: datetime


def _psql_env(database: str) -> dict[str, str]:
    settings = get_settings()
    url = settings.database_url.replace("+asyncpg", "")
    env = dict(os.environ)
    env["PGPASSWORD"] = url.rsplit("@", 1)[0].rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    env["PGDATABASE"] = database
    return env


def _database_url(database: str) -> str:
    url = get_settings().database_url.replace("+asyncpg", "")
    head, _, _tail = url.rpartition("/")
    return f"{head}/{database}"


def _run(command: list[str], env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else f"exit code {result.returncode}"
        raise SystemExit(f"error: {' '.join(command)} failed: {message}")


def create_backup(output_dir: Path) -> BackupResult:
    """Dump the database to a timestamped gzipped SQL file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")
    target = output_dir / f"hragents-{stamp}.sql.gz"
    with gzip.open(target, "wb") as handle:
        result = subprocess.run(
            ["pg_dump", "--no-owner", "--no-acl", "--dbname", get_settings().database_url],
            stdout=handle,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        detail = (result.stderr or b"").decode("utf-8", errors="ignore").strip()
        raise SystemExit(f"error: pg_dump failed: {detail or 'unknown error'}")
    return BackupResult(
        path=target, bytes_written=target.stat().st_size, created_at=datetime.now(UTC)
    )


def verify_backup(dump: Path, scratch_database: str) -> int:
    """Restore the dump into a scratch database and verify the audit chain.

    Returns the number of invalid audit entries (``-1`` means the chain is
    intact). Any non-``-1`` value is a failed drill.
    """
    _run(["dropdb", "--if-exists", scratch_database], env=_psql_env("postgres"))
    _run(["createdb", scratch_database], env=_psql_env("postgres"))
    try:
        with gzip.open(dump, "rb") as handle:
            result = subprocess.run(
                ["psql", "--quiet", "--dbname", scratch_database, "--set", "ON_ERROR_STOP=1"],
                stdin=handle,
                capture_output=True,
                check=False,
            )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="ignore").strip().splitlines()
            raise SystemExit(f"error: restore failed: {detail[-1] if detail else 'unknown'}")

        from hr_agents.db.session import create_sync_session_factory

        scratch_url = _database_url(scratch_database)
        engine = create_engine(scratch_url, pool_pre_ping=True)
        try:
            from hr_agents.db.audit import DbAuditChain

            chain = DbAuditChain(create_sync_session_factory(engine))
            first_invalid = chain.verify()
        finally:
            engine.dispose()
        print(
            f"audit chain: {'intact' if first_invalid == -1 else f'BROKEN at seq {first_invalid}'}"
        )
        print(f"entries: {chain.entry_count()}")
        return first_invalid
    finally:
        _run(["dropdb", "--if-exists", scratch_database], env=_psql_env("postgres"))


def restore_into(dump: Path, target_database: str) -> None:
    """Restore a dump into the configured database (destructive, explicit)."""
    print(f"restoring {dump} into {target_database} — this replaces the current data")
    _run(["dropdb", "--if-exists", target_database], env=_psql_env("postgres"))
    _run(["createdb", target_database], env=_psql_env("postgres"))
    with gzip.open(dump, "rb") as handle:
        result = subprocess.run(
            ["psql", "--quiet", "--dbname", target_database, "--set", "ON_ERROR_STOP=1"],
            stdin=handle,
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="ignore").strip().splitlines()
        raise SystemExit(f"error: restore failed: {detail[-1] if detail else 'unknown'}")
    print("restore complete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("backups"), help="backup directory")
    parser.add_argument(
        "--verify", action="store_true", help="restore into a scratch db and verify"
    )
    parser.add_argument(
        "--restore", type=Path, default=None, help="restore a dump into the live db"
    )
    parser.add_argument(
        "--scratch-database",
        default="hragents_restore_check",
        help="throwaway database name for the verification drill",
    )
    args = parser.parse_args(argv)

    if args.restore is not None:
        database = get_settings().database_url.rsplit("/", 1)[-1]
        restore_into(args.restore, database)
        return 0

    result = create_backup(args.output)
    print(f"wrote {result.path} ({result.bytes_written} bytes)")

    if args.verify:
        first_invalid = verify_backup(result.path, args.scratch_database)
        if first_invalid != -1:
            print("error: the restored audit chain does not verify", file=sys.stderr)
            return 1
        print("backup verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
