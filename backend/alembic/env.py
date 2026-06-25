"""Alembic environment for the LinkGarden async stack.

Runs migrations against either an async or sync DB URL. The "online" path
uses :meth:`AsyncConnection.run_sync` per the published SQLAlchemy 2.0 +
Alembic cookbook; the "offline" path emits raw SQL for review or for
DB-less environments. ``render_as_batch=True`` is enabled when the dialect
is SQLite so column-altering migrations work despite SQLite's missing
``ALTER`` support.

This module imports every feature's models package explicitly: if you add a
new model module, add the import here so ``--autogenerate`` sees it.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, async_engine_from_config

from alembic import context

# Make ``src/`` importable so the app's modules resolve when alembic is run
# from the backend root (``cd backend && alembic upgrade head``). The legacy
# ``backend/app.py`` Flask script must not shadow the new ``app`` package, so
# we both prepend ``src`` and drop any earlier ``backend`` entry that points
# at the legacy module path.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SRC = _BACKEND_ROOT / "src"
_SRC_STR = str(_SRC)
_BACKEND_STR = str(_BACKEND_ROOT)

# Drop any pre-existing entry that would let the legacy ``backend/app.py``
# resolve as the ``app`` module ahead of the new package.
sys.path[:] = [p for p in sys.path if p != _BACKEND_STR]
if _SRC_STR in sys.path:
    sys.path.remove(_SRC_STR)
sys.path.insert(0, _SRC_STR)

# Import settings + Base so the URL flows from one source of truth and the
# metadata picks up every model registered against ``Base``.
from app.core.config import get_settings  # noqa: E402
from app.core.db import Base  # noqa: E402

# IMPORTANT: import every feature's models module so its tables register on
# ``Base.metadata`` before ``target_metadata`` is read. Missing an import
# here is the #1 cause of "autogenerate didn't see my table" bugs.
from app.features.auth import models as _auth_models  # noqa: E402, F401
from app.features.cards import models as _cards_models  # noqa: E402, F401

# Alembic ``Config`` object, providing access to ``alembic.ini`` values.
config = context.config

# Override the URL from runtime settings so the operator can't accidentally
# point migrations at a different database than the app.
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _is_sqlite_url(url: str) -> bool:
    return url.startswith("sqlite") or "sqlite" in url.split("://", 1)[0]


def _render_as_batch() -> bool:
    """SQLite needs batch-mode for column-altering migrations."""

    return _is_sqlite_url(config.get_main_option("sqlalchemy.url") or "")


def run_migrations_offline() -> None:
    """Run migrations without a live DBAPI connection.

    Useful for ``alembic upgrade head --sql`` to emit reviewable SQL.
    """

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_render_as_batch(),
    )

    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    """Synchronous body invoked via :meth:`AsyncConnection.run_sync`."""

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_render_as_batch(),
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_async() -> None:
    """Run migrations against an async engine."""

    section = config.get_section(config.config_ini_section) or {}
    # Inject the runtime URL into the kwargs passed to the engine factory.
    section["sqlalchemy.url"] = config.get_main_option("sqlalchemy.url") or ""

    connectable: AsyncEngine = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Drive migrations against a live engine.

    Auto-detects whether the configured URL is async (uses an async engine
    and :meth:`run_sync`) or sync (falls back to the classic
    ``engine_from_config`` path).
    """

    url = config.get_main_option("sqlalchemy.url") or ""
    if "+aiosqlite" in url or "+asyncpg" in url or "async" in url.split("://", 1)[0]:
        asyncio.run(_run_migrations_async())
        return

    # Sync fallback (e.g., ``sqlite:///``). Useful when running migrations
    # from a non-async test helper.
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
