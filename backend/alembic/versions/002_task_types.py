"""Add support for expanded task types: bug_fix, refactor, test, documentation.

Revision ID: 002_task_types
Revises: 001_initial_schema
Create Date: 2026-09-29 17:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "002_task_types"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_task_type")
        op.execute(
            "ALTER TABLE tasks ADD CONSTRAINT ck_tasks_task_type "
            "CHECK (type IN ('bug', 'bug_fix', 'feature', 'refactor', 'test', 'documentation', 'docs', 'question', 'security'))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS ck_tasks_task_type")
        op.execute(
            "ALTER TABLE tasks ADD CONSTRAINT ck_tasks_task_type "
            "CHECK (type IN ('bug', 'feature', 'question', 'security', 'docs'))"
        )
