"""Initial schema.

Creates the full baseline schema from the ORM metadata. Subsequent migrations
should be generated with ``alembic revision --autogenerate`` and will contain
explicit per-change operations.

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from quantbot.infrastructure.db import models  # noqa: F401 - register tables
from quantbot.infrastructure.db.database import Base

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all baseline tables and indexes from the ORM metadata."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """Drop all baseline tables."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
