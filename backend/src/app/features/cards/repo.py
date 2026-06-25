"""Cards repository: all SQL for the cards feature lives here.

Per §3.2 the repository is the only layer that talks SQL. The service layer
calls into these methods; the router never imports it. Tests can substitute a
fake by depending on the ``CardRepository`` constructor signature (a single
``AsyncSession``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import String, func, or_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.cards.models import Card

if TYPE_CHECKING:
    from app.features.cards.schemas import CardListQuery


__all__ = ["CardRepository"]


class CardRepository:
    """Async SQL access for the ``cards`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ #
    # Reads                                                              #
    # ------------------------------------------------------------------ #

    async def list(self, query: CardListQuery) -> list[Card]:
        """Return cards matching ``query``, newest first.

        Filters:
        * ``include_archived`` — when False (default), archived rows hidden.
        * ``category`` — exact match on storage type.
        * ``group`` — exact match on the content-group enum.
        * ``tag`` — case-insensitive match against any element of ``tags``.
          Implemented in two stages: a coarse LIKE narrows candidates in
          SQL, then a Python pass confirms the JSON array actually contains
          the tag. This keeps the query portable across SQLite + Postgres
          without per-dialect JSON path operators.
        * ``q`` — case-insensitive substring across ``title``, ``summary``,
          and (coarsely) the tags JSON column.

        Sort: ``created_at DESC, id DESC`` (deterministic tie-breaker).
        """

        # ``cast(tags, String)`` produces the dialect-appropriate text rep
        # (TEXT on SQLite, JSON-cast on PostgreSQL); both let LIKE narrow.
        tags_text = func.lower(func.cast(Card.tags, String))

        stmt = select(Card)
        if not query.include_archived:
            stmt = stmt.where(Card.archived.is_(False))
        if query.category is not None:
            stmt = stmt.where(Card.category == query.category)
        if query.group is not None:
            stmt = stmt.where(Card.group == query.group)
        if query.tag is not None:
            needle = query.tag.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            stmt = stmt.where(tags_text.like(f"%{needle.lower()}%", escape="\\"))
        if query.q is not None:
            needle = f"%{query.q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Card.title).like(needle),
                    func.lower(Card.summary).like(needle),
                    tags_text.like(needle),
                )
            )
        stmt = stmt.order_by(Card.created_at.desc(), Card.id.desc())

        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())

        if query.tag is not None:
            needle_cf = query.tag.casefold()
            rows = [
                row
                for row in rows
                if any(
                    isinstance(t, str) and t.casefold() == needle_cf
                    for t in (row.tags or [])
                )
            ]
        return rows

    async def get_by_slug(
        self, slug: str, *, include_archived: bool = False
    ) -> Card | None:
        """Lookup by URL-facing slug. ``include_archived`` lets admin views
        retrieve archived rows."""

        stmt = select(Card).where(Card.slug == slug)
        if not include_archived:
            stmt = stmt.where(Card.archived.is_(False))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, card_id: UUID) -> Card | None:
        """Lookup by canonical UUID. Admin-facing; archived rows visible."""

        stmt = select(Card).where(Card.id == card_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def slug_exists(
        self, slug: str, *, exclude_id: UUID | None = None
    ) -> bool:
        """Return True when ``slug`` collides with a non-archived row.

        Mirrors the partial unique index. ``exclude_id`` allows a card to
        keep its own slug across an update.
        """

        stmt = select(Card.id).where(
            Card.archived.is_(False),
            Card.slug == slug,
        )
        if exclude_id is not None:
            stmt = stmt.where(Card.id != exclude_id)
        result = await self.session.execute(stmt.limit(1))
        return result.first() is not None

    # ------------------------------------------------------------------ #
    # Writes                                                             #
    # ------------------------------------------------------------------ #

    async def insert(self, card: Card) -> Card:
        """Persist a new card and return the managed instance.

        Caller is responsible for filling every required field, including
        ``slug`` (already de-collided via :func:`unique_slug`).
        """

        self.session.add(card)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(card)
        return card

    async def update(self, card: Card) -> Card:
        """Persist a mutated managed card.

        The card must already be attached to ``self.session`` (e.g. came
        from ``get_by_id``); we just flush + commit + refresh so the caller
        sees server-side ``updated_at``.
        """

        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(card)
        return card

    async def set_cover(self, card_id: UUID, cover: str) -> Card | None:
        """Update only the ``cover`` column.

        Exposed for the covers feature so it does not have to dance with
        the full ORM row. Returns the refreshed card (or ``None`` when the
        id no longer resolves, although the caller has typically just
        looked it up).
        """

        card = await self.get_by_id(card_id)
        if card is None:
            return None
        card.cover = cover
        return await self.update(card)

    async def delete(self, card: Card) -> None:
        """Hard-delete a card by primary key.

        Cover-file cleanup is the service layer's concern — the repository
        only owns SQL.
        """

        await self.session.execute(sa_delete(Card).where(Card.id == card.id))
        await self.session.commit()
