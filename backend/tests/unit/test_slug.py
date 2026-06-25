"""Unit tests for :mod:`app.features.cards.slug`.

Pure tests for :func:`slugify` plus async tests for :func:`unique_slug`
against the in-memory aiosqlite engine wired up by ``tests/conftest.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.features.cards.models import Card
from app.features.cards.slug import slugify, unique_slug

# --------------------------------------------------------------------------- #
# slugify                                                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Hello, World!", "hello-world"),
        ("  Multiple   Spaces  ", "multiple-spaces"),
        ("Mixed CASE Title", "mixed-case-title"),
        ("中文 标题", "中文-标题"),
        ("Hello-中文_World", "hello-中文world"),
        ("trailing---hyphens---", "trailing-hyphens"),
        ("with.punct?and!stuff", "withpunctandstuff"),
        ("123 numeric 456", "123-numeric-456"),
    ],
)
def test_slugify_happy_path(source: str, expected: str) -> None:
    assert slugify(source) == expected


def test_slugify_empty_returns_uuid_fallback() -> None:
    result = slugify("")
    assert result.startswith("article-")
    assert len(result) == len("article-") + 8


def test_slugify_pure_punctuation_returns_uuid_fallback() -> None:
    result = slugify("###!!!???")
    assert result.startswith("article-")


def test_slugify_truncates_to_column_width() -> None:
    long = "a" * 300
    result = slugify(long)
    assert len(result) <= 200
    assert set(result) == {"a"}


def test_slugify_is_idempotent_on_valid_slugs() -> None:
    once = slugify("Some Title")
    twice = slugify(once)
    assert once == twice == "some-title"


def test_slugify_handles_none_like_input() -> None:
    # ``slugify`` defends against ``None`` by treating it as empty.
    assert slugify(None).startswith("article-")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# unique_slug                                                                 #
# --------------------------------------------------------------------------- #


def _make_card(slug: str, *, archived: bool = False) -> Card:
    now = datetime.now(UTC)
    return Card(
        id=uuid4(),
        slug=slug,
        title=slug,
        category="external",
        url="https://example.com",
        summary="",
        tags=[],
        archived=archived,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_unique_slug_returns_base_when_no_collision(db_session) -> None:
    assert await unique_slug(db_session, "hello-world") == "hello-world"


@pytest.mark.asyncio
async def test_unique_slug_walks_numeric_suffixes(db_session) -> None:
    db_session.add(_make_card("hello"))
    db_session.add(_make_card("hello-2"))
    await db_session.commit()

    assert await unique_slug(db_session, "hello") == "hello-3"


@pytest.mark.asyncio
async def test_unique_slug_ignores_archived_rows(db_session) -> None:
    """Archived cards do not occupy the partial unique index."""

    db_session.add(_make_card("draft", archived=True))
    await db_session.commit()

    assert await unique_slug(db_session, "draft") == "draft"


@pytest.mark.asyncio
async def test_unique_slug_excludes_self_for_updates(db_session) -> None:
    """An update keeping its own slug should not be treated as a collision."""

    card = _make_card("same")
    db_session.add(card)
    await db_session.commit()

    result = await unique_slug(db_session, "same", exclude_id=card.id)
    assert result == "same"


@pytest.mark.asyncio
async def test_unique_slug_empty_base_falls_back(db_session) -> None:
    result = await unique_slug(db_session, "")
    assert result.startswith("article-")
