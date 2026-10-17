"""Generic row ↔ Pydantic model mapping for the document-style stores.

People, compliance, growth, and offboarding stores persist whole Pydantic
models whose fields mirror table columns one-to-one. Nested models are dumped
to JSON, scalars (dates, UUIDs, enums-as-str) pass through natively.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase as OrmBase
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.session import sync_session_scope
from hr_agents.errors import StaleRecordError


def _db_value(value: Any, *, nested: bool = False) -> Any:
    """Coerce one model value for a row column.

    ``nested`` marks values inside a dict/list -- i.e. bound for a JSON column,
    which (unlike a Numeric column) cannot carry a Decimal and has no json.dumps
    fallback of its own. There, every scalar is converted the way JSON would
    have carried it: Decimal to float (the number FastAPI already produced for
    the in-memory stores' responses), datetimes and dates to ISO strings, UUIDs
    to their canonical string. Top-level values pass through untouched so a
    Numeric column receives the exact Decimal.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_db_value(item, nested=True) for item in value]
    if isinstance(value, dict):
        return {key: _db_value(item, nested=True) for key, item in value.items()}
    if nested:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
    return value


def _row_values(model: BaseModel, record_cls: type[OrmBase]) -> dict[str, Any]:
    fields = set(type(model).model_fields)
    return {
        column.name: _db_value(getattr(model, column.name))
        for column in record_cls.__table__.columns
        if column.name in fields
    }


def model_from_row[ModelT: BaseModel](model_cls: type[ModelT], row: Any) -> ModelT:
    fields = set(model_cls.model_fields)
    values: dict[str, Any] = {}
    for column in row.__table__.columns:
        if column.name not in fields:
            continue
        value = getattr(row, column.name)
        if isinstance(value, datetime) and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        values[column.name] = value
    return model_cls.model_validate(values)


def add_model(factory: sessionmaker[Session], model: BaseModel, record_cls: type[OrmBase]) -> None:
    with sync_session_scope(factory) as session:
        session.add(record_cls(**_row_values(model, record_cls)))
        session.flush()


def check_version(row: Any, model: object) -> None:
    """The optimistic-concurrency check, for hand-written persist paths.

    `save_model` runs this itself. Adapters that copy columns by hand -- the
    on-demand services each have their own `_save_*` -- call it before copying, so
    every guarded writer refuses a stale write the same way and names the same two
    numbers.

    `model` is any object with `id` and `version` attributes: pydantic models get
    them from `Versioned`, and the recruitment records are dataclasses whose field
    plays the same role. A model without a `version` is not guarded; that is a
    statement about which adapters have been converted, not a claim that the rest
    are safe.
    """
    expected = getattr(model, "version", None)
    if expected is None:
        return
    # `version` lives on the tenant mixin, which the declarative base does not
    # declare; the alias keeps the attribute access checked without annotating the
    # generic layer with a column every table has.
    versioned_row: Any = row
    versioned_model: Any = model
    stored = int(versioned_row.version)
    if stored != expected:
        raise StaleRecordError(
            f"{type(row).__tablename__} {getattr(model, 'id', '?')} changed after this "
            f"copy was read (stored version {stored}, this copy holds {expected}); "
            "reload and decide again"
        )
    versioned_row.version = stored + 1
    # Keep the caller's instance current so a second save in the same unit of work
    # compares against what it just wrote.
    versioned_model.version = stored + 1


def save_model(factory: sessionmaker[Session], model: BaseModel, record_cls: type[OrmBase]) -> None:
    """Write a model back, refusing to overwrite a row that moved underneath it.

    The version check is what turns a lost update into a conflict: the model
    carries the version it was read at, the row carries the current one, and a
    mismatch means somebody else saved in between. Silently writing would discard
    their change -- and on a step completion or a mid-loop erasure, nobody would
    ever find out.
    """
    pk = getattr(model, "id", None)
    with sync_session_scope(factory) as session:
        row = session.get(record_cls, pk)
        if row is None:
            raise KeyError(f"unknown {record_cls.__tablename__} {pk}")
        check_version(row, model)
        for name, value in _row_values(model, record_cls).items():
            if name == "version":
                continue
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


def delete_model(
    factory: sessionmaker[Session],
    record_cls: type[OrmBase],
    model_id: Any,
) -> bool:
    """Delete one row by primary key. True when a row was actually removed.

    The return value is the point: a purge handler that reported a deletion it
    did not perform would put a false statement in the audit chain, and "the row
    was already gone" is a different outcome from "I removed it".
    """
    with sync_session_scope(factory) as session:
        row = session.get(record_cls, model_id)
        if row is None:
            return False
        session.delete(row)
        return True
