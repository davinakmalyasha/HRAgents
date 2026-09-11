from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hr_agents.db import tables
from hr_agents.db.base import Base


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    await engine.dispose()


async def test_candidate_round_trip(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    candidate_id = uuid4()
    candidate = tables.Candidate(
        id=candidate_id,
        full_name="Budi Santoso",
        primary_email="budi@example.com",
        consent={"granted": True, "purpose": "recruitment_evaluation"},
        profile={"full_name": "Budi Santoso"},
        field_confidence={},
    )

    async with factory() as session:
        session.add(candidate)
        await session.commit()

    async with factory() as session:
        loaded = await session.get(tables.Candidate, candidate_id)
        assert loaded is not None
        assert loaded.full_name == "Budi Santoso"
        assert loaded.consent["granted"] is True


async def test_job_application_link(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    job = tables.Job(
        id=uuid4(),
        title="Backend Engineer",
        seniority="mid",
        status="open",
        spec={"title": "Backend Engineer"},
    )
    candidate = tables.Candidate(
        id=uuid4(),
        full_name="Siti Rahma",
        consent={"granted": True},
        profile={"full_name": "Siti Rahma"},
        field_confidence={},
    )
    application = tables.Application(
        id=uuid4(),
        candidate_id=candidate.id,
        job_id=job.id,
        status="received",
        source_channel="api",
        idempotency_key="test-key-1",
    )

    async with factory() as session:
        session.add_all([job, candidate, application])
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(tables.Application))
        loaded = result.scalar_one()
        assert loaded.job_id == job.id
        assert loaded.candidate_id == candidate.id


async def test_audit_entry_unique_hash(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    entry = tables.AuditLog(
        entry_id=uuid4(),
        actor={"actor_type": "system", "actor_id": "policy-engine"},
        action="evaluation.scored",
        subject_type="candidate",
        subject_id="candidate-1",
        payload={"s_tech": 0.91},
        prev_hash=None,
        entry_hash="a" * 64,
    )

    async with factory() as session:
        session.add(entry)
        await session.commit()

    async with factory() as session:
        result = await session.execute(select(tables.AuditLog))
        loaded = result.scalar_one()
        assert loaded.action == "evaluation.scored"
        assert loaded.entry_hash == "a" * 64
