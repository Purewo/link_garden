"""Slug derivation + collision resolution for cards.

Per §3.2: ``slugify(text)`` is CJK-safe (lowercase ASCII, whitespace folds to
``-``, only ``[a-z0-9\\-一-鿿]`` survive, fallback to ``article-<short_uuid>``)
and ``unique_slug`` walks ``-2/-3/...`` against non-archived rows so the
partial unique index is the safety net, not the only check.

The helpers stay pure-Python on the slug-string side; only ``unique_slug``
takes the session, and even then it does a single ``slug LIKE base%`` query
to bound the I/O at one round-trip regardless of collision depth.
"""

from __future__ import annotations

import re
import uuid
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.cards.models import Card

__all__ = ["slugify", "unique_slug"]


# Whitespace folds to a single hyphen. ``\s`` covers ASCII + unicode spaces.
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

# Characters that survive slugification: lowercase ASCII letters, digits,
# hyphens, and CJK Unified Ideographs (U+4E00..U+9FFF). Everything else is
# stripped — punctuation, emoji, full-width forms, accented Latin, etc.
_KEEP_RE: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9\-一-鿿]")

# Collapse runs of hyphens introduced by stripping. Keeps slugs tidy when
# the source is something like "Hello, World!" -> "hello--world" -> "hello-world".
_DEDUP_HYPHEN_RE: Final[re.Pattern[str]] = re.compile(r"-{2,}")

# Maximum slug length matches the column width (200) so the DB never has to
# truncate.
_MAX_SLUG_LENGTH: Final[int] = 200


def slugify(text: str) -> str:
    """Derive a URL-safe slug from ``text``.

    Pipeline (matches §3.2 — keep this list in sync with the doctests):

    1. Strip + lowercase.
    2. Fold runs of whitespace to a single ``-``.
    3. Drop everything that isn't ``[a-z0-9\\-一-鿿]``.
    4. Collapse double hyphens, trim leading/trailing ``-``.
    5. Truncate to 200 chars (DB column width).
    6. If nothing survives, fall back to ``article-<short-uuid>``.

    Examples::

        >>> slugify("Hello, World!")
        'hello-world'
        >>> slugify("  Multiple   Spaces  ")
        'multiple-spaces'
        >>> slugify("中文 标题")
        '中文-标题'
        >>> slugify("###")
        'article-...'  # length 16
    """

    text = (text or "").strip().lower()
    text = _WHITESPACE_RE.sub("-", text)
    text = _KEEP_RE.sub("", text)
    text = _DEDUP_HYPHEN_RE.sub("-", text).strip("-")
    if len(text) > _MAX_SLUG_LENGTH:
        text = text[:_MAX_SLUG_LENGTH].rstrip("-")
    if not text:
        return f"article-{uuid.uuid4().hex[:8]}"
    return text


async def unique_slug(
    session: AsyncSession,
    base: str,
    *,
    exclude_id: UUID | None = None,
) -> str:
    """Return ``base`` (or ``base-2``, ``base-3``, …) so it does not collide.

    Only non-archived rows are considered, mirroring the partial unique
    index ``ix_cards_slug_active``. ``exclude_id`` lets an update keep its
    own slug — a card editing itself is not a collision.

    The implementation pulls every active slug that starts with ``base`` in
    one round-trip, then walks numeric suffixes in Python. For the expected
    cardinality (single-admin blog, dozens of cards) this is faster than a
    loop of ``EXISTS`` queries and immune to N+1 surprises.
    """

    if not base:
        # ``slugify`` should have already produced a fallback, but defend
        # in depth so callers can't ship an empty slug.
        base = f"article-{uuid.uuid4().hex[:8]}"

    stmt = select(Card.slug).where(
        Card.archived.is_(False),
        Card.slug.like(f"{base}%"),
    )
    if exclude_id is not None:
        stmt = stmt.where(Card.id != exclude_id)

    result = await session.execute(stmt)
    taken = {row[0] for row in result.all()}

    if base not in taken:
        return base

    # Walk -2, -3, ... until we find a free suffix. Bounded above by the
    # cardinality of taken slugs so this terminates even under contention.
    idx = 2
    while True:
        candidate = f"{base}-{idx}"
        if candidate not in taken:
            return candidate
        idx += 1
