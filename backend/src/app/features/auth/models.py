"""ORM model for the ``users`` table.

Per the phase-2 spec (§3.3) the auth model is intentionally narrow: a single
admin row in v1, no relationships, no self-registration. Authorship lives
on the API surface only — when card authorship becomes meaningful in v2 the
relationship can be back-populated without a destructive migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin
from app.core.types import GUID


class User(Base, TimestampMixin):
    """A LinkGarden user.

    The v1 deployment carries exactly one row (the admin), seeded by Alembic
    revision ``0002_seed_admin`` from the ``LG_ADMIN_*`` environment variables.
    The schema is forward-compatible with multi-user setups: ``role`` is a
    string column today and could become a foreign key into a ``roles`` table
    later.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    username: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=False,  # the UNIQUE constraint already provides the index
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="admin",
        server_default="admin",
    )

    # ``created_at`` / ``updated_at`` provided by TimestampMixin.

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"User(id={self.id!s}, username={self.username!r}, role={self.role!r})"


__all__ = ["User"]
