"""Initial database schema.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-09-25 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

import app.models  # noqa: F401
from app.database.base import Base

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pgvector extension if on postgres
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    Base.metadata.create_all(bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
