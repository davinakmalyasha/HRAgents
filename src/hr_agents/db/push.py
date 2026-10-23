"""Postgres-backed Web Push subscriptions.

Overrides only the persistence primitives; selection and delivery stay in
``services.push`` so the in-memory and database paths answer the same questions.
"""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import tables as t
from hr_agents.db.mapping import (
    add_model,
    delete_model,
    get_model,
    list_models,
    model_from_row,
    save_model,
)
from hr_agents.db.session import sync_session_scope
from hr_agents.models import PushSubscription
from hr_agents.services.push import PushStore


class DbPushStore(PushStore):
    """Subscriptions in ``push_subscriptions``."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add(self, subscription: PushSubscription) -> None:
        add_model(self._session_factory, subscription, t.PushSubscriptionRecord)

    def save(self, subscription: PushSubscription) -> None:
        save_model(self._session_factory, subscription, t.PushSubscriptionRecord)

    def get(self, subscription_id: UUID) -> PushSubscription | None:
        return get_model(
            self._session_factory,
            PushSubscription,
            t.PushSubscriptionRecord,
            subscription_id,
        )

    def list_all(self) -> list[PushSubscription]:
        records = list_models(self._session_factory, PushSubscription, t.PushSubscriptionRecord)
        return sorted(records, key=lambda item: (item.created_at, item.id))

    def for_actor(self, actor_id: str) -> list[PushSubscription]:
        row = t.PushSubscriptionRecord
        with sync_session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    select(row).where(row.actor_id == actor_id).order_by(row.created_at, row.id)
                )
                .scalars()
                .all()
            )
            return [model_from_row(PushSubscription, item) for item in rows]

    def for_endpoint(self, actor_id: str, endpoint: str) -> PushSubscription | None:
        row = t.PushSubscriptionRecord
        with sync_session_scope(self._session_factory) as session:
            record = (
                session.execute(
                    select(row).where(row.actor_id == actor_id, row.endpoint == endpoint)
                )
                .scalars()
                .first()
            )
            return None if record is None else model_from_row(PushSubscription, record)

    def for_roles(self, roles: Collection[str]) -> list[PushSubscription]:
        wanted = sorted(set(roles))
        if not wanted:
            return []
        row = t.PushSubscriptionRecord
        with sync_session_scope(self._session_factory) as session:
            rows = (
                session.execute(
                    select(row).where(row.role.in_(wanted)).order_by(row.created_at, row.id)
                )
                .scalars()
                .all()
            )
            return [model_from_row(PushSubscription, item) for item in rows]

    def delete(self, subscription_id: UUID) -> bool:
        return delete_model(self._session_factory, t.PushSubscriptionRecord, subscription_id)
