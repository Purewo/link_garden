"""User repository — the only place that touches the `users` table.

Per the spec (§3.2), all SQL for the auth feature lives here; the service
layer is forbidden from issuing queries directly. Insert is exposed for the
seeder script (`alembic 0002`, `scripts/seed_admin.py`) — there is no
self-registration in v1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    # B2 owns `features/auth/models.py`. Import only for typing so this unit
    # compiles in isolation before B2 lands; runtime resolution happens via
    # the local import inside each method.
    from app.features.auth.models import User


class UserRepository:
    """Read/write helpers for the `users` table.

    The repo is a thin wrapper around an `AsyncSession`. Callers are
    expected to manage transaction boundaries (commit / rollback) at the
    service layer; this class never commits on its own.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> "User | None":
        """Return the user row matching `username` exactly, or `None`."""

        from app.features.auth.models import User

        stmt = select(User).where(User.username == username)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> "User | None":
        """Return the user row with PK `user_id`, or `None`.

        Accepts a `UUID` (the canonical shape from JWT claims after we
        parse `sub`).  Use this in the auth dependency to resolve a token
        back to a row.
        """

        from app.features.auth.models import User

        return await self._session.get(User, user_id)

    async def insert(self, user: "User") -> "User":
        """Persist a new user row.

        Used by the seeder paths only — `alembic 0002` and
        `scripts/seed_admin.py`. The caller owns the commit.
        """

        self._session.add(user)
        await self._session.flush()
        return user

    async def count(self) -> int:
        """Return total user count.

        The seeder relies on this to stay idempotent: it inserts the admin
        row only when no users exist yet.
        """

        from app.features.auth.models import User

        stmt = select(func.count()).select_from(User)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())
