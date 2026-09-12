"""Prepare the PostgreSQL test database for the adapter suite.

Creates a non-superuser ``app_test`` role (superusers bypass row-level
security even with ``FORCE``) and grants it ownership-level access to the test
database so ``tests/db`` can create tables and exercise the RLS policies.

Usage:
    HRAGENTS_TEST_DB_ADMIN_URL=postgresql://user:pass@host:5432/db \
        uv run python scripts/prepare_test_db.py
"""

from __future__ import annotations

import os
import sys

import psycopg
from psycopg import sql

ROLE = "app_test"
PASSWORD = "app_test"


def main() -> int:
    admin_url = os.environ.get("HRAGENTS_TEST_DB_ADMIN_URL")
    if not admin_url:
        print("HRAGENTS_TEST_DB_ADMIN_URL is required")
        return 1

    with (
        psycopg.connect(admin_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE,))
        if cursor.fetchone() is None:
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER").format(
                    sql.Identifier(ROLE),
                    sql.Literal(PASSWORD),
                )
            )
        database = connection.info.dbname
        cursor.execute(
            sql.SQL("GRANT ALL ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(ROLE)
            )
        )
        cursor.execute(sql.SQL("GRANT ALL ON SCHEMA public TO {}").format(sql.Identifier(ROLE)))
        cursor.execute(sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(sql.Identifier(ROLE)))
    print(f"prepared role {ROLE!r} on database {database!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
