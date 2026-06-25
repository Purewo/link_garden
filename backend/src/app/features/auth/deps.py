"""FastAPI dependency types for authentication and admin authorization.

Two type aliases are exported and consumed directly in router signatures:

    CurrentUser = Annotated[User, Depends(_get_current_user)]
    AdminUser   = Annotated[User, Depends(_require_admin)]

Per §3.6, both raise 401 `unauthenticated` on any failure (missing header,
bad prefix, signature mismatch, expired token, missing user) and 403
`forbidden` when an authenticated non-admin hits an admin route.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_jwt
from app.features.auth.repo import UserRepository

if TYPE_CHECKING:
    from app.features.auth.models import User


_BEARER_PREFIX = "bearer "


async def _get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_session),
) -> "User":
    """Resolve the `Authorization: Bearer <jwt>` header to a `User` row.

    Any failure path collapses to `Unauthorized('unauthenticated', 401)`
    so callers cannot distinguish "no token" from "expired token" from
    "user since deleted". This matches the spec.
    """

    if not authorization:
        raise Unauthorized("unauthenticated", "Authentication required.")

    # Case-insensitive prefix match; the rest of the header value is the
    # token and is left untouched (no .strip on the token itself, since
    # base64url has no whitespace and a trailing space would be a bug).
    if not authorization.lower().startswith(_BEARER_PREFIX):
        raise Unauthorized("unauthenticated", "Authentication required.")

    token = authorization[len(_BEARER_PREFIX):].strip()
    if not token:
        raise Unauthorized("unauthenticated", "Authentication required.")

    # `decode_jwt` already raises Unauthorized on signature/expiry failure
    # per its contract in core.security. We re-wrap any other exception
    # raised *by the decoder itself* so JWT internals never leak. DB
    # errors propagate untouched so the global handler renders a 500.
    try:
        claims = decode_jwt(token)
    except Unauthorized:
        raise
    except Exception as exc:  # noqa: BLE001 — defense in depth around decode_jwt
        raise Unauthorized("unauthenticated", "Authentication required.") from exc

    sub = claims.get("sub")
    if not isinstance(sub, str):
        raise Unauthorized("unauthenticated", "Authentication required.")

    try:
        user_id = UUID(sub)
    except (ValueError, TypeError) as exc:
        raise Unauthorized("unauthenticated", "Authentication required.") from exc

    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise Unauthorized("unauthenticated", "Authentication required.")

    return user


async def _require_admin(
    user: "User" = Depends(_get_current_user),
) -> "User":
    """Compose `_get_current_user` and assert `user.role == 'admin'`.

    Returns the same `User` so admin-only routes get a free typed handle
    on the caller without re-running the dep.
    """

    if user.role != "admin":
        raise Forbidden("forbidden", "Admin role required.")
    return user


# Public re-export so cross-feature routers don't import the underscored name.
require_admin = _require_admin


# These are the two symbols the router signatures consume. Keeping them as
# `Annotated` aliases (rather than passing `Depends(...)` inline at every
# call site) means the router signatures stay short and the typing tools
# can resolve `User` directly from the parameter.
if TYPE_CHECKING:
    from app.features.auth.models import User as _UserModel

    CurrentUser = Annotated[_UserModel, Depends(_get_current_user)]
    AdminUser = Annotated[_UserModel, Depends(_require_admin)]
else:
    # At runtime the forward reference is resolved lazily through Depends;
    # we still keep the Annotated alias so router signatures read well.
    from typing import Any

    CurrentUser = Annotated[Any, Depends(_get_current_user)]
    AdminUser = Annotated[Any, Depends(_require_admin)]
