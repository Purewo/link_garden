"""Tags repository.

Aggregates the distinct, sorted union of tags across cards. Because ``cards.tags``
is stored as a JSON array column (see §3.3 of the architecture spec), the
cross-dialect strategy is to select the per-row arrays and fold them in Python:
tag cardinality is in the dozens, so the overhead is negligible and avoids
SQLite/PostgreSQL JSON-function divergence.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.cards.models import Card


async def list_distinct_tags(
    session: AsyncSession,
    *,
    include_archived: bool = False,
) -> list[str]:
    """Return distinct tags across cards, case-insensitively deduped and sorted.

    Args:
        session: Active async SQLAlchemy session.
        include_archived: When False (default), archived cards are excluded so
            tags from soft-deleted entries do not leak (fixes the legacy bug
            where ``/api/tags`` included archived rows while ``/api/cards`` did
            not).

    Returns:
        Sorted list of tag strings. Comparison for dedupe is case-insensitive
        on ``str.casefold()``; the preserved form is the first occurrence
        encountered, deterministic via the ``ORDER BY id`` clause. The output
        is then ASCII/locale-sorted via plain ``sorted()`` so the response is
        stable across requests and DB backends.
    """

    stmt = select(Card.tags).order_by(Card.created_at.asc(), Card.id.asc())
    if not include_archived:
        stmt = stmt.where(Card.archived.is_(False))

    result = await session.execute(stmt)

    seen: dict[str, str] = {}
    for (tag_list,) in result.all():
        if not tag_list:
            continue
        for raw in tag_list:
            if not isinstance(raw, str):
                continue
            tag = raw.strip()
            if not tag:
                continue
            key = tag.casefold()
            # First occurrence wins; later duplicates with different casing are
            # discarded so we get a single canonical surface form per tag.
            if key not in seen:
                seen[key] = tag

    return sorted(seen.values(), key=lambda t: t.casefold())
