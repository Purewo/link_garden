"""Tag routes.

Exposes a single public endpoint: ``GET /tags``. The response is a bare list
of strings (no envelope) per the API contract in §3.5.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.tags.repo import list_distinct_tags

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get(
    "",
    response_model=list[str],
    summary="List distinct tags",
    description=(
        "Return the distinct union of card tags, case-insensitively deduped "
        "and sorted. By default, tags from archived cards are excluded; "
        "pass ``include_archived=true`` to include them."
    ),
)
async def get_tags(
    session: Annotated[AsyncSession, Depends(get_session)],
    include_archived: Annotated[
        bool,
        Query(description="Include tags attached to archived cards."),
    ] = False,
) -> list[str]:
    """Return the distinct sorted tag list.

    The endpoint is unauthenticated — tag names are not considered sensitive.
    """

    return await list_distinct_tags(session, include_archived=include_archived)
