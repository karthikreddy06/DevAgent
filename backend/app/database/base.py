"""SQLAlchemy declarative base, naming conventions and shared column mixins."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.ids import new_id

# Deterministic constraint names keep Alembic autogenerate stable across runs.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every DevAgent table."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUIDv7 primary key (time-ordered, index friendly, unguessable)."""

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=new_id)


class TimestampMixin:
    """``created_at`` / ``updated_at`` maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


def enum_column(enum_class: type[PyEnum], name: str, *, length: int = 48) -> SAEnum:
    """A portable enum column.

    Enums are stored as VARCHAR with a CHECK constraint rather than a native
    PostgreSQL enum type: adding a value later is then a trivial migration
    instead of an ``ALTER TYPE`` dance (ADR-0006).
    """
    return SAEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        length=length,
        values_callable=lambda members: [str(member.value) for member in members],
    )


def json_dict(value: Any) -> dict[str, Any]:
    """Normalise an arbitrary JSONB result to a plain dict."""
    if isinstance(value, dict):
        return dict(value)
    return {}
