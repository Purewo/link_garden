"""Cards feature router.

Six endpoints per §3.5:

* GET    /cards                — public, query filters
* GET    /cards/{slug}         — public, by slug
* POST   /cards                — admin, publish
* PUT    /cards/{id}           — admin, update by UUID
* PATCH  /cards/{id}/archive   — admin, archive setter
* DELETE /cards/{id}           — admin, hard delete

Routes stay thin — no SQL, no business logic — and the admin-gated
endpoints depend on :data:`AdminUser` from the auth feature.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.auth.deps import AdminUser
from app.features.cards.schemas import (
    CardArchive,
    CardCreate,
    CardDetail,
    CardListItem,
    CardListQuery,
    CardRead,
    CardUpdate,
)
from app.features.cards.service import CardService

if TYPE_CHECKING:
    from app.features.cards.models import Card


__all__ = ["router"]


router = APIRouter(prefix="/cards", tags=["cards"])


def _to_list_item(card: Card) -> CardListItem:
    return CardListItem.model_validate(card)


def _to_detail(card: Card) -> CardDetail:
    """Project a card into ``CardDetail``.

    For external cards we explicitly null out ``body``/``body_html`` so the
    wire shape stays small even if the columns are populated by accident.
    """

    detail = CardDetail.model_validate(card)
    if card.category != "local":
        detail.body = None
        detail.body_html = None
    return detail


def _to_read(card: Card) -> CardRead:
    return CardRead.model_validate(card)


@router.get(
    "",
    response_model=list[CardListItem],
    summary="List cards",
    description=(
        "Return cards matching the query filters. Default sort is "
        "``created_at DESC, id DESC``. Archived cards are excluded unless "
        "``include_archived=true`` is passed."
    ),
)
async def list_cards(
    session: Annotated[AsyncSession, Depends(get_session)],
    category: Annotated[str | None, Query(max_length=16)] = None,
    group: Annotated[str | None, Query(max_length=32)] = None,
    tag: Annotated[str | None, Query(max_length=32)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> list[CardListItem]:
    query = CardListQuery(
        category=category,  # type: ignore[arg-type]
        group=group,  # type: ignore[arg-type]
        tag=tag,
        q=q,
        include_archived=include_archived,
    )
    cards = await CardService(session).list_cards(query)
    return [_to_list_item(card) for card in cards]


@router.get(
    "/{slug}",
    response_model=CardDetail,
    summary="Get card by slug",
)
async def get_card(
    slug: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CardDetail:
    card = await CardService(session).get_card_detail(slug)
    return _to_detail(card)


@router.post(
    "",
    response_model=CardDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Publish a new card",
)
async def publish_card(
    payload: CardCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: AdminUser,
) -> CardDetail:
    card = await CardService(session).publish(payload)
    return _to_detail(card)


@router.put(
    "/{card_id}",
    response_model=CardDetail,
    summary="Update a card by id",
)
async def update_card(
    card_id: UUID,
    payload: CardUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: AdminUser,
) -> CardDetail:
    card = await CardService(session).update(card_id, payload)
    return _to_detail(card)


@router.patch(
    "/{card_id}/archive",
    response_model=CardRead,
    summary="Archive or unarchive a card",
)
async def archive_card(
    card_id: UUID,
    payload: CardArchive,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: AdminUser,
) -> CardRead:
    card = await CardService(session).set_archive(card_id, payload)
    return _to_read(card)


@router.delete(
    "/{card_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a card",
)
async def delete_card(
    card_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: AdminUser,
) -> Response:
    await CardService(session).delete(card_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
