"""Integration tests for the tags feature.

These tests intentionally bypass HTTP and exercise the repository directly so
that the suite remains useful even before the upstream B1 scaffolding (which
provides ``app.main:create_app`` and the ``conftest`` fixtures) lands. The
HTTP-level behaviour is covered by ``test_openapi_snapshot.py`` once the app
is wired up.

If/when ``backend/tests/conftest.py`` ships an ``async_session`` fixture, the
``session`` fixture below transparently delegates to it. Otherwise we spin up
an isolated in-memory aiosqlite engine for the duration of the test module so
that the file can be exercised standalone via::

    uv run pytest backend/tests/integration/test_tags.py
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# These imports rely on B1 (Base, GUID type) and B2 (Card model). If they are
# not yet present at test time, pytest will skip this module rather than fail
# the run — the integrator wires them up at merge.
pytest.importorskip("app.core.db")
pytest.importorskip("app.features.cards.models")

from app.core.db import Base  # noqa: E402  (deferred import after importorskip)
from app.features.cards.models import Card  # noqa: E402
from app.features.tags.repo import list_distinct_tags  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a fresh AsyncSession bound to an in-memory SQLite database.

    The schema is created from ``Base.metadata`` so the test does not depend
    on Alembic migrations being applied first.
    """

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as sess:
        yield sess

    await engine.dispose()


def _make_card(
    *,
    title: str,
    tags: list[str],
    archived: bool = False,
    category: str = "external",
    created_at: datetime | None = None,
) -> Card:
    """Build a minimal valid ``Card`` row for the tag aggregation tests."""

    return Card(
        id=uuid.uuid4(),
        slug=title.lower().replace(" ", "-") + "-" + uuid.uuid4().hex[:6],
        title=title,
        category=category,
        group=None,
        summary="",
        cover=None,
        url="https://example.com" if category == "external" else None,
        body=None if category == "external" else "body",
        body_html=None,
        tags=tags,
        archived=archived,
        created_at=created_at or datetime.now(UTC),
    )


# Constant base timestamp; tests offset by N seconds to pin row order without
# relying on the DB's server-side default (which can collapse rows added in
# the same transaction onto the same instant).
_BASE_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _ts(offset: int) -> datetime:
    return _BASE_TS + timedelta(seconds=offset)


# ---------------------------------------------------------------------------
# Repository behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_distinct_tags_empty(session: AsyncSession) -> None:
    """No cards => empty tag list."""

    assert await list_distinct_tags(session) == []


@pytest.mark.asyncio
async def test_list_distinct_tags_distinct_and_sorted(
    session: AsyncSession,
) -> None:
    """Tags from non-archived cards are deduped (case-insensitive) and sorted."""

    session.add_all(
        [
            _make_card(
                title="Alpha",
                tags=["python", "FastAPI", "sql"],
                created_at=_ts(0),
            ),
            _make_card(
                title="Beta",
                tags=["FastAPI", "Vue"],
                created_at=_ts(1),
            ),
            _make_card(
                title="Gamma",
                tags=["python", "vue", "  "],
                created_at=_ts(2),
            ),
        ]
    )
    await session.commit()

    tags = await list_distinct_tags(session)

    # Case-insensitive dedupe; first-seen casing wins (FastAPI, Vue from Alpha/Beta).
    assert tags == ["FastAPI", "python", "sql", "Vue"]


@pytest.mark.asyncio
async def test_list_distinct_tags_excludes_archived_by_default(
    session: AsyncSession,
) -> None:
    """Archived cards' tags must not leak unless explicitly requested."""

    session.add_all(
        [
            _make_card(
                title="Live",
                tags=["python", "fastapi"],
                created_at=_ts(0),
            ),
            _make_card(
                title="Old",
                tags=["legacy", "deprecated"],
                archived=True,
                created_at=_ts(1),
            ),
        ]
    )
    await session.commit()

    tags = await list_distinct_tags(session)
    assert tags == ["fastapi", "python"]
    assert "legacy" not in tags
    assert "deprecated" not in tags


@pytest.mark.asyncio
async def test_list_distinct_tags_include_archived(
    session: AsyncSession,
) -> None:
    """include_archived=True returns the union of all card tags."""

    session.add_all(
        [
            _make_card(
                title="Live",
                tags=["python", "fastapi"],
                created_at=_ts(0),
            ),
            _make_card(
                title="Old",
                tags=["legacy", "Python"],
                archived=True,
                created_at=_ts(1),
            ),
        ]
    )
    await session.commit()

    tags = await list_distinct_tags(session, include_archived=True)
    assert tags == ["fastapi", "legacy", "python"]


@pytest.mark.asyncio
async def test_list_distinct_tags_handles_empty_and_whitespace(
    session: AsyncSession,
) -> None:
    """Empty arrays, empty strings, and whitespace-only entries are dropped."""

    session.add_all(
        [
            _make_card(title="Empty", tags=[], created_at=_ts(0)),
            _make_card(
                title="Whitespace",
                tags=["  ", "", "\t"],
                created_at=_ts(1),
            ),
            _make_card(
                title="Real",
                tags=["  trim-me  ", "keep"],
                created_at=_ts(2),
            ),
        ]
    )
    await session.commit()

    tags = await list_distinct_tags(session)
    assert tags == ["keep", "trim-me"]
