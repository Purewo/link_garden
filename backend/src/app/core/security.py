"""Password hashing and JWT helpers.

bcrypt is wrapped directly (no passlib) and JWT decoding is pinned to HS256
exactly so the algorithm-confusion ``alg=none`` attack is impossible.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.errors import Unauthorized

# bcrypt's hard 72-byte cap. Truncating client-side is consistent with the
# documented behaviour and matches what verify_password does on the wire.
_BCRYPT_MAX_BYTES: Final[int] = 72


def _truncate_for_bcrypt(password: str) -> bytes:
    """Encode ``password`` and truncate to bcrypt's 72-byte limit."""

    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Return a bcrypt hash for ``password`` (12 rounds by default)."""

    hashed = bcrypt.hashpw(_truncate_for_bcrypt(password), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time bcrypt verification. Returns False on any failure."""

    try:
        return bcrypt.checkpw(_truncate_for_bcrypt(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed hash bytes — treat as mismatch, never raise.
        return False


def encode_jwt(claims: dict[str, Any], ttl_seconds: int | None = None) -> str:
    """Sign ``claims`` with HS256 and the configured secret.

    Adds ``iat`` and ``exp`` claims when not already present. ``ttl_seconds``
    defaults to ``Settings.JWT_TTL_SECONDS``.
    """

    settings = get_settings()
    now = datetime.now(UTC)
    ttl = ttl_seconds if ttl_seconds is not None else settings.JWT_TTL_SECONDS

    payload = dict(claims)
    payload.setdefault("iat", int(now.timestamp()))
    payload.setdefault("exp", int((now + timedelta(seconds=ttl)).timestamp()))

    return jwt.encode(  # pyright: ignore[reportUnknownMemberType]
        payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG
    )


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode + verify ``token``. Raises :class:`Unauthorized` on any failure.

    Pinned to ``algorithms=["HS256"]``; the ``none`` algorithm and any other
    family is rejected unconditionally.
    """

    settings = get_settings()
    try:
        return jwt.decode(  # pyright: ignore[reportUnknownMemberType]
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALG],
            options={"require": ["exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("unauthenticated", "token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("unauthenticated", "invalid token") from exc


__all__ = [
    "decode_jwt",
    "encode_jwt",
    "hash_password",
    "verify_password",
]
