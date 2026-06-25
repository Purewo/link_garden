"""Cards service: business logic for card CRUD.

Per §3.2 the service holds the orchestration glue between the schemas,
the repository, the markdown renderer, and the filesystem (for cover
cleanup). It contains no SQL — only ``CardRepository`` does.

Responsibilities pinned by §3.2:

* Mint UUIDs for new cards.
* Derive slugs via :func:`slugify` and de-collide via :func:`unique_slug`.
* Enforce ``category ⇒ url|body`` coupling against the **merged** state
  (the request payload alone cannot see the current row, so the
  schema-level validator only fires for create — update is verified here).
* Render and persist ``body_html`` on every mutation that touches
  ``body`` or ``category``.
* Wipe the stale-category field (``url`` ↔ ``body``) on a category switch.
* Unlink the cover file on delete when its URL points at our static dir.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.config import Settings, get_settings
from app.core.errors import BadRequest, Conflict, NotFound
from app.features.cards.models import Card
from app.features.cards.repo import CardRepository
from app.features.cards.schemas import (
    CardArchive,
    CardCreate,
    CardListQuery,
    CardUpdate,
)
from app.features.cards.slug import slugify, unique_slug
from app.services.markdown import render_markdown

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["CardService"]


_log = logging.getLogger(__name__)


class CardService:
    """Orchestrates card CRUD on top of :class:`CardRepository`."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.repo = CardRepository(session)
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ #
    # Reads                                                              #
    # ------------------------------------------------------------------ #

    async def list_cards(self, query: CardListQuery) -> list[Card]:
        """Return cards matching ``query`` (newest first)."""

        return await self.repo.list(query)

    async def get_card_detail(
        self, slug: str, *, include_archived: bool = False
    ) -> Card:
        """Fetch a card by slug. 404s when missing (or archived for anon)."""

        card = await self.repo.get_by_slug(slug, include_archived=include_archived)
        if card is None:
            raise NotFound("card_not_found", "Card not found")
        return card

    # ------------------------------------------------------------------ #
    # Writes                                                             #
    # ------------------------------------------------------------------ #

    async def publish(self, payload: CardCreate) -> Card:
        """Insert a new card from an admin publish payload."""

        # Slug derivation: prefer the explicit slug, else the title.
        base = slugify(payload.slug) if payload.slug else slugify(payload.title)
        slug = await unique_slug(self.session, base)

        body = payload.body if payload.category == "local" else None
        body_html = render_markdown(body) if body else None

        now = datetime.now(UTC)
        card = Card(
            id=uuid.uuid4(),
            slug=slug,
            title=payload.title,
            category=payload.category,
            group=payload.group,
            summary=payload.summary or "",
            cover=payload.cover,
            url=payload.url if payload.category == "external" else None,
            body=body,
            body_html=body_html,
            tags=list(payload.tags),
            archived=False,
            created_at=now,
            updated_at=now,
        )
        try:
            return await self.repo.insert(card)
        except Exception as exc:  # pragma: no cover - DB-side defense in depth
            # ``get_session`` will rollback on the raised exception; we
            # only translate slug-collision races into a structured 409.
            if "slug" in str(exc).lower():
                raise Conflict(
                    "slug_conflict",
                    "Slug already exists",
                ) from exc
            raise

    async def update(self, card_id: UUID, payload: CardUpdate) -> Card:
        """Apply a partial update to ``card_id``."""

        card = await self.repo.get_by_id(card_id)
        if card is None:
            raise NotFound("card_not_found", "Card not found")

        data = payload.model_dump(exclude_unset=True)

        # Merge with current state to know what coupling rule applies.
        merged_category: str = data.get("category", card.category)
        if merged_category not in {"external", "local"}:
            raise BadRequest(
                "invalid_category",
                "category must be external or local",
            )

        # Apply top-level fields that don't need cross-coupling logic.
        if "title" in data:
            card.title = data["title"]
        if "group" in data:
            card.group = data["group"]
        if "summary" in data:
            card.summary = data["summary"] or ""
        if "tags" in data:
            card.tags = list(data["tags"])
        if "cover" in data:
            card.cover = data["cover"]

        # Slug regeneration: if the payload supplies a slug, slugify + de-collide
        # (excluding self). Otherwise the existing slug is preserved.
        if "slug" in data and data["slug"] is not None:
            new_slug = slugify(data["slug"])
            new_slug = await unique_slug(
                self.session, new_slug, exclude_id=card.id
            )
            card.slug = new_slug

        category_changed = "category" in data and data["category"] != card.category

        # Determine the resulting url/body once so coupling is checked against
        # the post-merge state — never on the bare payload.
        if merged_category == "external":
            merged_url = data.get("url", card.url)
            if not merged_url:
                raise BadRequest(
                    "missing_url",
                    "url is required for external cards",
                )
            card.category = "external"
            card.url = merged_url
            # Wipe stale local-only fields if we are switching categories.
            if category_changed or card.body is not None:
                card.body = None
                card.body_html = None
        else:
            merged_body = data.get("body", card.body)
            if not merged_body or not merged_body.strip():
                raise BadRequest(
                    "missing_body",
                    "body is required for local cards",
                )
            card.category = "local"
            card.body = merged_body
            # Wipe stale external-only fields.
            if category_changed or card.url is not None:
                card.url = None
            # Re-render unconditionally on any path that touched body OR
            # category, per §3.2.
            if (
                "body" in data
                or category_changed
                or card.body_html is None
            ):
                card.body_html = render_markdown(merged_body)

        try:
            return await self.repo.update(card)
        except Exception as exc:
            # ``get_session`` rolls back automatically; only translate
            # slug-collision races into a structured 409.
            if "slug" in str(exc).lower():
                raise Conflict(
                    "slug_conflict",
                    "Slug already exists",
                ) from exc
            raise

    async def set_archive(self, card_id: UUID, payload: CardArchive) -> Card:
        """Toggle the archive flag.

        The partial unique index on ``slug`` is the safety net: archiving a
        card releases its slug so a replacement can be published, and
        un-archiving re-enters the constraint pool. We raise 409 if
        un-archiving would collide with an active twin.
        """

        card = await self.repo.get_by_id(card_id)
        if card is None:
            raise NotFound("card_not_found", "Card not found")

        # Un-archiving: check whether the slug now collides with an
        # active row (someone may have re-published under the same slug).
        if (
            not payload.archived
            and card.archived
            and await self.repo.slug_exists(card.slug, exclude_id=card.id)
        ):
            raise Conflict(
                "slug_conflict",
                "Slug already exists for an active card",
            )

        card.archived = bool(payload.archived)
        return await self.repo.update(card)

    async def delete(self, card_id: UUID) -> None:
        """Hard-delete a card and (best-effort) unlink its cover file."""

        card = await self.repo.get_by_id(card_id)
        if card is None:
            raise NotFound("card_not_found", "Card not found")

        cover_url = card.cover
        await self.repo.delete(card)

        if cover_url and cover_url.startswith(self.settings.COVERS_PUBLIC_PREFIX):
            self._unlink_cover_file(cover_url)

    async def attach_cover(self, card_id: UUID, cover_url: str) -> Card:
        """Set ``card.cover`` to ``cover_url`` and return the refreshed row.

        Exposed as the seam the covers feature consumes so that feature stays
        unaware of the cards repository. Raises 404 ``card_not_found`` when
        the card has disappeared between the upload validation and the
        commit.
        """

        card = await self.repo.set_cover(card_id, cover_url)
        if card is None:
            raise NotFound("card_not_found", "Card not found")
        return card

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _unlink_cover_file(self, cover_url: str) -> None:
        """Best-effort delete of the on-disk cover file backing ``cover_url``.

        Errors are swallowed (the row is already gone — we don't want to fail
        the request because of a stale file). Defensive ``resolve()`` keeps
        traversal out of reach.
        """

        # Strip the cache-buster query string and the public prefix to land at
        # the filename relative to ``covers_dir``.
        path_part = cover_url.split("?", 1)[0]
        prefix = self.settings.COVERS_PUBLIC_PREFIX
        if not path_part.startswith(prefix):
            return
        relative = path_part[len(prefix):].lstrip("/")
        if not relative:
            return

        covers_dir = self.settings.covers_dir
        try:
            candidate = (covers_dir / relative).resolve()
            covers_resolved = covers_dir.resolve()
        except OSError:
            return

        # Refuse to unlink anything outside the covers dir.
        if (
            covers_resolved not in candidate.parents
            and candidate != covers_resolved
        ):
            return

        try:
            Path(candidate).unlink(missing_ok=True)
        except OSError:
            _log.warning("failed_to_unlink_cover", extra={"path": str(candidate)})
