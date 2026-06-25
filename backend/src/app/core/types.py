"""Cross-dialect SQLAlchemy type decorators.

Currently exposes :class:`GUID`, which stores UUIDs as ``CHAR(36)`` on SQLite
and as native ``UUID`` on PostgreSQL so application code can keep using
``Mapped[uuid.UUID]`` without dialect branches.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR, Dialect
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator, TypeEngine


class GUID(TypeDecorator[uuid.UUID]):
    """Platform-independent UUID column type.

    On PostgreSQL uses ``UUID(as_uuid=True)``. Everywhere else stores a
    canonical lowercase 36-char string. Either way Python sees a
    :class:`uuid.UUID`.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(
        self, value: uuid.UUID | str | None, dialect: Dialect
    ) -> str | uuid.UUID | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        if isinstance(value, uuid.UUID):
            return str(value)
        # Validate any incoming string so we don't silently store garbage.
        return str(uuid.UUID(str(value)))

    def process_result_value(
        self, value: str | uuid.UUID | None, dialect: Dialect
    ) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


__all__ = ["GUID"]
