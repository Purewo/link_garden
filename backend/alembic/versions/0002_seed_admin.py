"""Seed the bootstrap admin user.

Revision ID: 0002_seed_admin
Revises: 0001_initial
Create Date: 2026-06-25 00:00:01.000000

Idempotently inserts a single admin row built from ``LG_ADMIN_USERNAME`` and
``LG_ADMIN_PASSWORD`` when the ``users`` table is empty. If any user already
exists this migration is a no-op so re-running ``alembic upgrade head`` on a
populated database is safe. ``LG_ADMIN_PASSWORD`` is required to be at least
8 characters; the migration aborts loudly otherwise so a deployment never
ships with a weak default.

Imports of ``app.core.*`` happen inside :func:`upgrade` rather than at
module scope so test runs that target an isolated metadata (without the app's
real settings on the path) can still import the migrations module.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_seed_admin"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Minimum admin password length, enforced at seed time so the
# bootstrap row can never carry a trivially-guessable secret.
_MIN_ADMIN_PASSWORD_LEN = 8


def _users_table() -> sa.Table:
    """Light reflection of ``users`` for ``op.bulk_insert``.

    Defined locally so this migration does not depend on the live ORM
    metadata: future model edits will not silently change the seeder's
    column shape.
    """

    return sa.table(
        "users",
        sa.column("id", sa.String),
        sa.column("username", sa.String),
        sa.column("password_hash", sa.String),
        sa.column("role", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def upgrade() -> None:
    """Insert the admin row only when no users exist yet."""

    # Late imports keep migrations importable in isolation (e.g., when
    # generating a new revision in an environment that has not configured
    # ``JWT_SECRET``).
    from app.core.config import get_settings
    from app.core.security import hash_password

    bind = op.get_bind()
    existing = bind.execute(sa.text("SELECT COUNT(*) FROM users")).scalar_one()
    if int(existing) > 0:
        return

    settings = get_settings()
    username = (settings.LG_ADMIN_USERNAME or "").strip()
    password = settings.LG_ADMIN_PASSWORD or ""

    if not username:
        raise RuntimeError(
            "LG_ADMIN_USERNAME must be set before running the 0002_seed_admin "
            "migration on an empty database."
        )
    if len(password) < _MIN_ADMIN_PASSWORD_LEN:
        raise RuntimeError(
            "LG_ADMIN_PASSWORD must be at least "
            f"{_MIN_ADMIN_PASSWORD_LEN} characters before running the "
            "0002_seed_admin migration on an empty database."
        )

    now = datetime.now(UTC)
    op.bulk_insert(
        _users_table(),
        [
            {
                "id": str(uuid.uuid4()),
                "username": username,
                "password_hash": hash_password(password),
                "role": "admin",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    """Remove the seeded admin row, if it still matches the env-configured username.

    Keeps the operation reversible without nuking arbitrary downstream users.
    """

    from app.core.config import get_settings

    settings = get_settings()
    username = (settings.LG_ADMIN_USERNAME or "").strip()
    if not username:
        return

    op.execute(
        sa.text("DELETE FROM users WHERE username = :u").bindparams(u=username)
    )
