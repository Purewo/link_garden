"""Auth feature business logic.

Two public functions: `authenticate` (validate username + password and
return the user row) and `mint_token` (turn a `User` into a
`TokenResponse`). Neither issues SQL directly — that lives in `repo.py`.
"""

from __future__ import annotations

import secrets
import time
from collections import deque
from threading import Lock
from typing import TYPE_CHECKING, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, Unauthorized
from app.core.security import encode_jwt, hash_password, verify_password
from app.features.auth.repo import UserRepository
from app.features.auth.schemas import TokenResponse, UserRead

if TYPE_CHECKING:
    from app.features.auth.models import User


# A live bcrypt hash generated at import time. Used purely to equalize
# timing between the "user not found" and "wrong password" branches —
# the value is opaque random bytes so it can never accidentally verify a
# real password. ``hash_password`` runs at module load so the cost is paid
# once per process, not once per failed login.
_DUMMY_HASH: str = hash_password(secrets.token_urlsafe(16))


# In-process credential-stuffing brake. nginx already rate-limits this
# endpoint, but doubling up at the app layer means the throttle survives
# someone exposing port 5001 directly. ``_LOGIN_WINDOW`` is the rolling
# window in seconds; ``_LOGIN_MAX_FAILS`` is the failure budget per
# (username, ip) before a 429 lockout.
_LOGIN_MAX_FAILS: Final[int] = 5
_LOGIN_WINDOW: Final[float] = 300.0  # 5 minutes
_LOGIN_LOCK = Lock()
_login_attempts: dict[tuple[str, str], deque[float]] = {}


class TooManyAttempts(AppError):
    """Raised when a (username, ip) bucket exceeds the failure budget."""

    http_status = 429
    default_code = "too_many_attempts"


def _attempt_key(username: str, client_ip: str) -> tuple[str, str]:
    return (username.casefold(), client_ip or "")


def _check_login_budget(username: str, client_ip: str) -> None:
    """Raise :class:`TooManyAttempts` when the failure budget is spent."""

    now = time.monotonic()
    key = _attempt_key(username, client_ip)
    with _LOGIN_LOCK:
        bucket = _login_attempts.get(key)
        if bucket is None:
            return
        # Drop expired entries from the front so the deque size reflects
        # only failures inside the rolling window.
        while bucket and (now - bucket[0]) > _LOGIN_WINDOW:
            bucket.popleft()
        if len(bucket) >= _LOGIN_MAX_FAILS:
            raise TooManyAttempts(
                code="too_many_attempts",
                message="Too many failed login attempts, please retry later.",
            )


def _record_login_failure(username: str, client_ip: str) -> None:
    now = time.monotonic()
    key = _attempt_key(username, client_ip)
    with _LOGIN_LOCK:
        bucket = _login_attempts.setdefault(key, deque(maxlen=_LOGIN_MAX_FAILS + 1))
        bucket.append(now)


def _clear_login_failures(username: str, client_ip: str) -> None:
    key = _attempt_key(username, client_ip)
    with _LOGIN_LOCK:
        _login_attempts.pop(key, None)


async def authenticate(
    session: AsyncSession,
    username: str,
    password: str,
    *,
    client_ip: str = "",
) -> "User":
    """Resolve `(username, password)` to a `User` row or raise 401.

    Returns the same `invalid_credentials` error for both "user not found"
    and "wrong password" so timing/branching does not leak which usernames
    exist. We still call `verify_password` on a throwaway hash when the
    user does not exist, keeping the cost roughly constant.

    A small in-memory throttle (``_LOGIN_MAX_FAILS`` failures per
    ``_LOGIN_WINDOW`` seconds keyed on ``(username, client_ip)``) raises
    429 ``too_many_attempts`` once the budget is spent. The brake is
    process-local; production sits behind nginx's matching limit.
    """

    _check_login_budget(username, client_ip)

    repo = UserRepository(session)
    user = await repo.get_by_username(username)

    if user is None:
        # Run a dummy bcrypt verify so failure timing matches the
        # "wrong password" branch. The constant below is a valid bcrypt
        # hash of an arbitrary string; we throw away the result.
        verify_password(password, _DUMMY_HASH)
        _record_login_failure(username, client_ip)
        raise Unauthorized("invalid_credentials", "Invalid username or password.")

    if not verify_password(password, user.password_hash):
        _record_login_failure(username, client_ip)
        raise Unauthorized("invalid_credentials", "Invalid username or password.")

    _clear_login_failures(username, client_ip)
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
    token = encode_jwt(claims, ttl_seconds=ttl)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ttl,
        user=UserRead.model_validate(user),
    )
