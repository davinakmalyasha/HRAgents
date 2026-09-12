"""Verify the persisted audit chain (ops cron / post-deploy check).

Exit code 0 when the chain is intact, 1 when the first invalid sequence is found
or the store backend is not Postgres. Run with ``HRAGENTS_STORE_BACKEND=postgres``.
"""

from __future__ import annotations

import sys

from hr_agents.config import get_settings
from hr_agents.db import create_sync_engine, create_sync_session_factory
from hr_agents.db.audit import DbAuditChain


def main() -> int:
    settings = get_settings()
    if settings.store_backend != "postgres":
        print("audit verification requires HRAGENTS_STORE_BACKEND=postgres")
        return 1
    engine = create_sync_engine(settings)
    try:
        chain = DbAuditChain(create_sync_session_factory(engine))
        invalid_seq = chain.verify()
        if invalid_seq == -1:
            print(f"audit chain intact ({len(chain.entries)} entries)")
            return 0
        print(f"AUDIT CHAIN BROKEN at seq {invalid_seq}")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
