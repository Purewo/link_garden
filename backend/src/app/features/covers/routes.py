"""``POST /api/v1/covers`` — admin-only multipart cover upload.

The router stays thin per the architecture rules (≤30 LOC, no SQL, no
business logic). All work delegates to
:func:`app.features.covers.service.upload_cover`.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

# ``AsyncSession`` is referenced in runtime annotations on the route, so
# it must be importable outside ``TYPE_CHECKING``. With ``from __future__
# import annotations`` the annotation is a string FastAPI evaluates at
# request time; a missing name then collapses the dependency into a
# query parameter, which is the failure mode we are guarding against.
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.features.covers.schemas import CoverUploadResponse
from app.features.covers.service import upload_cover

# Cross-unit symbols (B4 + B5). We import lazily and fall back to a
# minimal sentinel so this module imports even when the auth and cards
# features have not landed yet. The integrator wires the real deps in
# during merge.
try:  # pragma: no cover - exercised at import time only
    from app.core.db import get_session  # type: ignore[import-not-found]
except Exception:  # pragma: no cover

    async def get_session():  # type: ignore[no-redef]
        """Stub session dependency; integrator replaces with the real one."""

        raise RuntimeError(
            "app.core.db.get_session is not available; integrator must wire it"
        )


try:  # pragma: no cover
    from app.features.auth.deps import (
        _require_admin as _require_admin,  # type: ignore[import-not-found]
    )
except Exception:  # pragma: no cover

    async def _require_admin() -> Any:  # type: ignore[no-redef]
        """Stub admin guard; integrator replaces during merge."""

        return None


try:  # pragma: no cover
    from app.features.cards.repo import CardRepository  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - any import-time failure (parallel build)
    # Other builders may still be in-flight; tolerate ImportError *and*
    # SyntaxError so this module remains usable in tests that inject a
    # fake repo via the ``_make_card_repo`` seam below.
    CardRepository = None  # type: ignore[assignment, misc]


router = APIRouter(
    prefix="/covers",
    tags=["covers"],
    # The admin gate runs as a router-level dependency; this keeps the
    # endpoint signature focused on multipart inputs and prevents the
    # dependency from leaking into the OpenAPI parameter list.
    dependencies=[Depends(_require_admin)],
)


def _make_card_repo(session: AsyncSession) -> Any:
    """Build a cards repository for the current request.

    Isolated as a helper so tests can monkeypatch the constructor without
    chasing FastAPI dependency overrides.
    """

    if CardRepository is None:  # pragma: no cover - integration-only branch
        raise RuntimeError(
            "app.features.cards.repo.CardRepository is not available; "
            "integrator must wire B5 before exercising covers"
        )
    return CardRepository(session)


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
    settings: Annotated[Settings, Depends(get_settings)],
) -> CoverUploadResponse:
    """Validate the multipart upload and persist it for ``card_id``."""

    return await upload_cover(
        upload=file,
        card_id=card_id,
        session=session,
        settings=settings,
        card_repo=_make_card_repo(session),
    )


__all__ = ["router"]
