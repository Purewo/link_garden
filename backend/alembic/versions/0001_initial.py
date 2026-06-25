"""Initial schema: users + cards.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-25 00:00:00.000000

Creates the two v1 tables, their indexes, and the partial unique slug index
keyed on non-archived rows. Constraint names follow the naming convention
configured in ``app.core.db.NAMING_CONVENTION``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.types import GUID

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``users`` + ``cards`` with all indexes and constraints."""

    op.create_table(
        "users",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default="admin",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )

    op.create_table(
        "cards",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("group", sa.String(length=32), nullable=True),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("cover", sa.String(length=512), nullable=True),
        sa.Column("url", sa.String(length=2048), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_cards"),
        sa.CheckConstraint(
            "category IN ('external', 'local')",
            # The naming convention (``ck_%(table_name)s_%(constraint_name)s``)
            # turns this into ``ck_cards_category``.
            name="category",
        ),
    )

    # Default-empty-list for tags on insert is handled at the ORM layer; the
    # DB-side default would require a JSON literal that SQLite and PostgreSQL
    # disagree on, so it is deliberately omitted here.

    # Indexes on cards. The slug index is partial on ``archived = 0`` so
    # archived rows can carry a previously-used slug for history without
    # blocking republication.
    op.create_index(
        "ix_cards_slug_active",
        "cards",
        ["slug"],
        unique=True,
        sqlite_where=sa.text("archived = 0"),
        postgresql_where=sa.text("archived = false"),
    )
    op.create_index(
        "ix_cards_archived_created_at",
        "cards",
        ["archived", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_cards_category",
        "cards",
        ["category"],
        unique=False,
    )
    op.create_index(
        "ix_cards_group",
        "cards",
        ["group"],
        unique=False,
    )


def downgrade() -> None:
    """Drop everything created in ``upgrade``."""

    op.drop_index("ix_cards_group", table_name="cards")
    op.drop_index("ix_cards_category", table_name="cards")
    op.drop_index("ix_cards_archived_created_at", table_name="cards")
    op.drop_index("ix_cards_slug_active", table_name="cards")
    op.drop_table("cards")
    op.drop_table("users")
