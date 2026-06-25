"""``POST /api/v1/covers`` — admin-only multipart cover upload.

The router stays thin per the architecture rules (≤30 LOC, no SQL, no
business logic). All work delegates to
:func:`app.features.covers.service.upload_cover`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.auth.deps import AdminUser
from app.features.cards.service import CardService
from app.features.covers.schemas import CoverUploadResponse
from app.features.covers.service import upload_cover

router = APIRouter(prefix="/covers", tags=["covers"])


@router.post(
    "",
    response_model=CoverUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a cover image for a card",
)
async def post_cover(
    file: Annotated[UploadFile, File(...)],
    card_id: Annotated[UUID, Form(...)],
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: AdminUser,
) -> CoverUploadResponse:
    """Validate the multipart upload and persist it for ``card_id``."""

    return await upload_cover(
        upload=file,
        card_id=card_id,
        session=session,
        card_service=CardService(session),
    )


__all__ = ["router"]
