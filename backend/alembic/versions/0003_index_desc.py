"""Recreate the (archived, created_at) index with DESC ordering.

Revision ID: 0003_index_desc
Revises: 0002_seed_admin
Create Date: 2026-06-25 00:00:02.000000

The hot list endpoint orders ``ORDER BY created_at DESC, id DESC``. The
original index was ascending which forced SQLite to perform a reverse
walk + temp B-tree. Re-create the index with the matching descending
order so the planner can use it directly.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_index_desc"
down_revision: str | None = "0002_seed_admin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the ascending index and rebuild it with DESC ordering."""

    op.drop_index("ix_cards_archived_created_at", table_name="cards")
    # SQLite + PostgreSQL both accept ``ORDER BY`` clauses inside
    # ``CREATE INDEX``. We use ``sa.text`` so SQLAlchemy passes the
    # ``created_at DESC`` fragment through unmodified instead of trying
    # to bind it as a column name.
    op.execute(
        "CREATE INDEX ix_cards_archived_created_at "
        "ON cards (archived, created_at DESC)"
    )


def downgrade() -> None:
    """Restore the original ascending index."""

    op.drop_index("ix_cards_archived_created_at", table_name="cards")
    op.create_index(
        "ix_cards_archived_created_at",
        "cards",
        ["archived", "created_at"],
        unique=False,
    )
