"""Shared pytest fixtures.

* Sets safe env vars before the app imports settings.
* Builds a per-session in-memory aiosqlite engine and wires the app's session
  dependency to it.
* Exposes an ``httpx.AsyncClient`` over an ASGITransport for integration tests.

The DB schema is brought up via ``Base.metadata.create_all`` (synchronous run
through ``connection.run_sync``) — Alembic-driven migrations are validated by
B2's test suite separately. The engine is per-session because each test is
isolated by truncating tables in the ``session`` fixture.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

# --- Environment defaults: applied BEFORE the app or its settings get imported.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "JWT_SECRET",
    # Long-enough placeholder that satisfies the Settings min_length=32 check.
    # Avoid the literal example sentinels rejected by the placeholder validator.
    "Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_secret_for_tests_only",
)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ALLOWED_ORIGINS", "http://testserver")
os.environ.setdefault("LG_ADMIN_PASSWORD", "ZkP9qT3hLm2vW7xR_test_admin")

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
from app.core.security import hash_password
from app.features.auth.models import User
from app.features.auth.repo import UserRepository
from app.features.auth.service import mint_token
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
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Async session bound to the test engine.

    Renamed from ``db_session`` so the auth + cards suites can both depend on
    a single canonical fixture name.
    """

    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )
    async with factory() as sess:
        yield sess


# Back-compat alias so any straggling caller of ``db_session`` keeps working.
@pytest_asyncio.fixture()
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Alias for ``session`` so legacy tests still resolve their fixture name."""

    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )
    async with factory() as sess:
        yield sess


@pytest_asyncio.fixture()
async def admin_user(session: AsyncSession) -> User:
    """Insert a seeded admin user and return the persisted row."""

    user = User(
        id=uuid4(),
        username="admin",
        password_hash=hash_password("admin-test-password"),
        role="admin",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await UserRepository(session).insert(user)
    await session.commit()
    return user


@pytest_asyncio.fixture()
async def admin_token(admin_user: User) -> str:
    """Return a ready-to-use ``Authorization`` header value for the admin."""

    return f"Bearer {mint_token(admin_user).access_token}"


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
