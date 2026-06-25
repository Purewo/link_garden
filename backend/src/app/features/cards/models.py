"""ORM model for the ``cards`` table.

Per the phase-2 spec (§3.3): ``cards.id`` is an immutable ``uuid4`` primary
key; ``cards.slug`` is a regenerable URL handle that is unique only among
non-archived rows (partial unique index). ``tags`` is JSON. The
``category↔(url|body)`` coupling is enforced at the service layer, not in the
DB, so legacy rows can be migrated without lying about which constraint
holds.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.core.types import GUID

# Partial-unique predicate for the slug index. SQLite ``sqlite_where`` and
# PostgreSQL ``postgresql_where`` accept a textual SQL expression; using
# :func:`text` keeps it dialect-portable (both backends evaluate the same
# fragment because ``archived`` is a real boolean on both).
_SLUG_ACTIVE_PREDICATE = text("archived = 0")


class Card(Base, TimestampMixin):
    """A LinkGarden card (external link or in-site markdown article).

    Storage notes:
    - ``id`` is the canonical handle for mutating endpoints.
    - ``slug`` is the URL-facing handle for read endpoints; a partial unique
      index keeps it unique among non-archived rows so an archived twin can
      coexist with a re-published replacement.
    - ``body`` stores the raw markdown source verbatim (H1 stripping happens
      at render time, never on disk). ``body_html`` caches the sanitized
      render and is rewritten by the service layer on every mutation that
      touches ``body`` or ``category``.
    - ``tags`` is a JSON array; the workload (single-admin blog, dozens of
      tags, single ``DISTINCT`` query) does not justify a join table.
    """

    __tablename__ = "cards"
    __table_args__ = (
        # Service layer enforces external⇒url / local⇒body, but the storage
        # type is constrained to keep accidental writes from corrupting the
        # category surface.
        CheckConstraint(
            "category IN ('external', 'local')",
            # Naming convention renders this as ``ck_cards_category``.
            name="category",
        ),
        # Partial unique index: a slug is unique among non-archived cards.
        # SQLite supports this via ``sqlite_where``; PostgreSQL natively via
        # ``postgresql_where``. Naming convention turns this into
        # ``ix_cards_slug_active``.
        Index(
            "ix_cards_slug_active",
            "slug",
            unique=True,
            sqlite_where=_SLUG_ACTIVE_PREDICATE,
            postgresql_where=_SLUG_ACTIVE_PREDICATE,
        ),
        Index(
            "ix_cards_archived_created_at",
            "archived",
            "created_at",
        ),
        Index("ix_cards_category", "category"),
        Index("ix_cards_group", "group"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    # ``group`` is a SQL reserved word; SQLAlchemy auto-quotes because the
    # column name matches. The Python attribute stays ``group`` to match the
    # API surface (CardCreate.group, etc.).
    group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    cover: Mapped[str | None] = mapped_column(String(512), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    # ``created_at`` / ``updated_at`` provided by TimestampMixin.

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"Card(id={self.id!s}, slug={self.slug!r}, "
            f"category={self.category!r}, archived={self.archived!r})"
        )


__all__ = ["Card"]
