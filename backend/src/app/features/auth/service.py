"""Auth feature business logic.

Two public functions: `authenticate` (validate username + password and
return the user row) and `mint_token` (turn a `User` into a
`TokenResponse`). Neither issues SQL directly — that lives in `repo.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.core.security import encode_jwt, verify_password
from app.features.auth.repo import UserRepository
from app.features.auth.schemas import TokenResponse, UserRead

if TYPE_CHECKING:
    from app.features.auth.models import User


async def authenticate(
    session: AsyncSession,
    username: str,
    password: str,
) -> "User":
    """Resolve `(username, password)` to a `User` row or raise 401.

    Returns the same `invalid_credentials` error for both "user not found"
    and "wrong password" so timing/branching does not leak which usernames
    exist. We still call `verify_password` on a throwaway hash when the
    user does not exist, keeping the cost roughly constant.
    """

    repo = UserRepository(session)
    user = await repo.get_by_username(username)

    if user is None:
        # Run a dummy bcrypt verify so failure timing matches the
        # "wrong password" branch. The constant below is a valid bcrypt
        # hash of an arbitrary string; we throw away the result.
        verify_password(password, _DUMMY_HASH)
        raise Unauthorized("invalid_credentials", "Invalid username or password.")

    if not verify_password(password, user.password_hash):
        raise Unauthorized("invalid_credentials", "Invalid username or password.")

    return user


def mint_token(user: "User") -> TokenResponse:
    """Build a JWT for `user` and wrap it in a `TokenResponse`.

    Claims follow §3.6: `sub` is the UUID stringified, plus `username` and
    `role` to save the dep one DB hit on hot paths if it ever wants to
    short-circuit. The encode helper attaches `iat` + `exp` itself.
    """

    settings = get_settings()
    ttl = settings.JWT_TTL_SECONDS
    claims = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
    }
    token = encode_jwt(claims, ttl=ttl)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ttl,
        user=UserRead.model_validate(user),
    )


# A pre-computed bcrypt hash used purely to equalize timing on the
# "user not found" path. Decoded value is intentionally not a real
# password; the hash was generated with bcrypt rounds=12.
_DUMMY_HASH = "$2b$12$abcdefghijklmnopqrstuuOZ0X1l5N4w2C8b6r3v0z1Y7s9eK6QHy"
