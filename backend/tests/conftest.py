"""Shared pytest fixtures.

* Sets safe env vars before the app imports settings.
* Builds a per-session in-memory aiosqlite engine and wires the app's session
  dependency to it.
* Exposes an ``httpx.AsyncClient`` over an ASGITransport for integration tests.

The DB schema is brought up via ``Base.metadata.create_all`` (synchronous run
through ``connection.run_sync``) — Alembic-driven migrations are validated by
B2's test suite separately. The engine is per-session because each test is
isolated by truncating tables in the ``db_session`` fixture.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

# --- Environment defaults: applied BEFORE the app or its settings get imported.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "JWT_SECRET",
    # Long-enough placeholder that satisfies the Settings min_length=32 check.
    "test-jwt-secret-please-do-not-use-in-prod-12345",
)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ALLOWED_ORIGINS", "http://testserver")
os.environ.setdefault("LG_ADMIN_PASSWORD", "test-admin-pass")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core import db as core_db
from app.core.config import get_settings
from app.core.db import Base, configure_engine, dispose_engine
from app.main import create_app


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Pin the async backend so anyio-based tools pick a consistent loop."""

    return "asyncio"


@pytest_asyncio.fixture()
async def engine() -> AsyncIterator[AsyncEngine]:
    """In-memory aiosqlite engine bound to the app's session factory.

    Each test gets its own engine + schema so cross-test leakage is impossible
    even when tests run in parallel.
    """

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        # ``StaticPool`` would be ideal for shared in-memory state, but each
        # test uses its own engine so the default pool behaviour is fine.
    )
    configure_engine(test_engine)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield test_engine
    finally:
        await dispose_engine()


@pytest_asyncio.fixture()
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Async session bound to the test engine."""

    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )
    async with factory() as session:
        yield session


@pytest_asyncio.fixture()
async def app(engine: AsyncEngine):
    """Build a fresh FastAPI app for each test."""

    return create_app()


@pytest_asyncio.fixture()
async def client(app) -> AsyncIterator[AsyncClient]:
    """ASGI httpx client targeting the test app."""

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture()
def settings():
    """Return the cached settings object (kept available for parametrised tests)."""

    return get_settings()


# Re-export the db module for tests that want to monkeypatch globals.
__all__ = ["core_db"]
