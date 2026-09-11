"""Generic row ↔ Pydantic model mapping for the document-style stores.

People, compliance, growth, and offboarding stores persist whole Pydantic
models whose fields mirror table columns one-to-one. Nested models are dumped
to JSON, scalars (dates, UUIDs, enums-as-str) pass through natively.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase as OrmBase
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.session import sync_session_scope


def _db_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_db_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _db_value(item) for key, item in value.items()}
    return value


def _row_values(model: BaseModel, record_cls: type[OrmBase]) -> dict[str, Any]:
    fields = set(type(model).model_fields)
    return {
        column.name: _db_value(getattr(model, column.name))
        for column in record_cls.__table__.columns
        if column.name in fields
    }


def model_from_row[ModelT: BaseModel](model_cls: type[ModelT], row: Any) -> ModelT:
    values: dict[str, Any] = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        values[column.name] = value
    return model_cls.model_validate(values)


def add_model(factory: sessionmaker[Session], model: BaseModel, record_cls: type[OrmBase]) -> None:
    with sync_session_scope(factory) as session:
        session.add(record_cls(**_row_values(model, record_cls)))
        session.flush()


def save_model(factory: sessionmaker[Session], model: BaseModel, record_cls: type[OrmBase]) -> None:
    pk = getattr(model, "id", None)
    with sync_session_scope(factory) as session:
        row = session.get(record_cls, pk)
        if row is None:
            raise KeyError(f"unknown {record_cls.__tablename__} {pk}")
        for name, value in _row_values(model, record_cls).items():
            setattr(row, name, value)
        session.flush()


def get_model[ModelT: BaseModel](
    factory: sessionmaker[Session],
    model_cls: type[ModelT],
    record_cls: type[OrmBase],
    key: Any,
) -> ModelT | None:
    with sync_session_scope(factory) as session:
        row = session.get(record_cls, key)
        return None if row is None else model_from_row(model_cls, row)


def list_models[ModelT: BaseModel](
    factory: sessionmaker[Session],
    model_cls: type[ModelT],
    record_cls: type[OrmBase],
) -> list[ModelT]:
    with sync_session_scope(factory) as session:
        rows = session.execute(select(record_cls)).scalars().all()
        return [model_from_row(model_cls, row) for row in rows]
