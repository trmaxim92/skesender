"""Baseline schema marker.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-29

Existing databases already created via SQLAlchemy create_all + lifespan
patches. Stamp this revision on current environments:

  alembic stamp 0001_baseline

Future schema changes: alembic revision --autogenerate -m "..." then upgrade.
"""

from __future__ import annotations

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Intentionally empty: schema already present from app bootstrap.
    pass


def downgrade() -> None:
    pass
