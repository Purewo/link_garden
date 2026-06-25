"""SQLAlchemy ``connect`` listener that applies SQLite PRAGMAs.

The listener is registered against :class:`sqlalchemy.engine.Engine` so any
async engine built on a sync DBAPI (aiosqlite) picks it up automatically. On
non-SQLite dialects it is a no-op.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine


def _set_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """Apply WAL + FK + busy-timeout PRAGMAs on every new SQLite connection."""

    # ``module`` lives on the DBAPI connection across both sqlite3 and aiosqlite.
    module = getattr(type(dbapi_connection), "__module__", "")
    if "sqlite" not in module:
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def install() -> None:
    """Idempotently register the connect listener."""

    if not event.contains(Engine, "connect", _set_sqlite_pragmas):
        event.listen(Engine, "connect", _set_sqlite_pragmas)


__all__ = ["install"]
