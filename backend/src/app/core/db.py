"""Async SQLAlchemy engine, session factory, and FastAPI session dependency.

A single ``AsyncEngine`` is created lazily on first use so test fixtures can
override the engine before the app touches a database. The session dependency
is a FastAPI generator that rolls back on exception and closes in ``finally``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Final

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings
from app.core.pragmas import install as install_pragma_listener

# Standard naming convention: makes Alembic autogen produce stable, readable
# constraint names instead of hash-suffixed ones.
NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""

    metadata = metadata


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns with DB-side defaults."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# Engine + session factory state. Initialised lazily so import order is safe
# (e.g., tests can replace the engine before any code imports it).
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine(database_url: str) -> AsyncEngine:
    install_pragma_listener()
    return create_async_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        # ``echo`` stays off; use structlog for query observability instead.
    )


def get_engine() -> AsyncEngine:
    """Return the lazily-initialised process-wide async engine."""

    global _engine
    if _engine is None:
        _engine = _build_engine(get_settings().DATABASE_URL)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the lazily-initialised process-wide session factory."""

    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
            class_=AsyncSession,
        )
    return _session_factory


def configure_engine(engine: AsyncEngine) -> None:
    """Replace the process-wide engine (test hook).

    Tests inject an in-memory aiosqlite engine before the app touches DB.
    """

    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
        class_=AsyncSession,
    )


async def dispose_engine() -> None:
    """Tear down the engine. Called from the FastAPI lifespan on shutdown."""

    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield an :class:`AsyncSession`.

    Commits on a clean exit, rolls back on any exception escaping the
    handler. Repositories therefore stay commit-free, which makes
    multi-step service operations atomic.
    """

    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
        finally:
            await session.close()


__all__ = [
    "NAMING_CONVENTION",
    "Base",
    "TimestampMixin",
    "configure_engine",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_session_factory",
    "metadata",
]
