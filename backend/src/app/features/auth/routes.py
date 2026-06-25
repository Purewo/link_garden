"""Auth feature router.

Two endpoints per §3.5: `POST /auth/login` (public) and `GET /auth/me`
(bearer). The router itself is intentionally thin — no SQL, no business
logic — so it stays well under the 30 LOC guidance from §3.2.

The router is exported as `router` so `main.py` can mount it under
`/api/v1/auth` via `api_v1_router.include_router(router, prefix="/auth")`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.features.auth.deps import CurrentUser
from app.features.auth.schemas import LoginRequest, TokenResponse, UserRead
from app.features.auth.service import authenticate, mint_token

if TYPE_CHECKING:
    from app.features.auth.models import User


router = APIRouter(tags=["auth"])


@router.post("/login", response_model=TokenResponse, status_code=200)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Validate credentials and return a JWT.

    Wrong credentials raise 401 `invalid_credentials`; oversized payloads
    are rejected with 422 by Pydantic before this handler runs.
    """

    user = await authenticate(session, payload.username, payload.password)
    return mint_token(user)


@router.get("/me", response_model=UserRead, status_code=200)
async def me(current_user: CurrentUser) -> UserRead:
    """Return the authenticated user.

    Used by the SPA on boot to validate a persisted token. The dep takes
    care of 401 paths — by the time we reach the body, `current_user` is
    guaranteed to be a real row.
    """

    return UserRead.model_validate(current_user)
