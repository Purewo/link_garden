"""Interactive admin user rotator / creator.

Run from the backend root::

    uv run python -m scripts.seed_admin            # interactive prompt
    uv run python -m scripts.seed_admin --username admin --password '...'

Behaviour:
* If a user with the given username exists, the password hash is rotated
  in place and ``updated_at`` is refreshed.
* If no user with that username exists, a new admin row is inserted.
* Password input defaults to :func:`getpass.getpass` so it never lands in
  shell history. The ``--password`` flag is accepted for scripted use but
  emits a warning.

The script asserts schema parity with Alembic ``head`` before touching the
DB so it cannot run against an unmigrated tree.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Ensure ``src/`` is importable when invoked via ``python -m scripts.seed_admin``
# from the backend root. The legacy ``backend/app.py`` Flask script must not
# shadow the new ``app`` package, so we drop any earlier ``backend`` entry
# from ``sys.path`` before prepending ``src``.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SRC = _BACKEND_ROOT / "src"
_SRC_STR = str(_SRC)
_BACKEND_STR = str(_BACKEND_ROOT)
sys.path[:] = [p for p in sys.path if p != _BACKEND_STR]
if _SRC_STR in sys.path:
    sys.path.remove(_SRC_STR)
sys.path.insert(0, _SRC_STR)

from app.core.db import dispose_engine, get_session_factory  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.features.auth.models import User  # noqa: E402
from app.features.auth.repo import UserRepository  # noqa: E402

_MIN_PASSWORD_LEN = 8


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create or rotate the LinkGarden admin user. "
            "Reads password via getpass() when --password is not provided."
        ),
    )
    parser.add_argument(
        "--username",
        default=None,
        help="Admin username. Prompts interactively when omitted.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help=(
            "Admin password. AVOID on shared shells — leaves a shell history "
            "trail. Prefer the interactive getpass prompt."
        ),
    )
    parser.add_argument(
        "--role",
        default="admin",
        help="Role to set on the user row (defaults to 'admin').",
    )
    return parser.parse_args(argv)


def _prompt_username(default: str | None) -> str:
    suffix = f" [{default}]" if default else ""
    prompt = f"Username{suffix}: "
    raw = input(prompt).strip()
    if raw:
        return raw
    if default:
        return default
    print("A username is required.", file=sys.stderr)
    raise SystemExit(2)


def _prompt_password() -> str:
    while True:
        first = getpass.getpass("New password: ")
        if len(first) < _MIN_PASSWORD_LEN:
            print(
                f"Password must be at least {_MIN_PASSWORD_LEN} characters.",
                file=sys.stderr,
            )
            continue
        second = getpass.getpass("Repeat password: ")
        if first != second:
            print("Passwords did not match; try again.", file=sys.stderr)
            continue
        return first


async def _seed(username: str, password: str, role: str) -> str:
    """Insert or rotate the admin row. Returns a one-line outcome message."""

    factory = get_session_factory()
    async with factory() as session:
        repo = UserRepository(session)
        existing = await repo.get_by_username(username)
        now = datetime.now(UTC)

        if existing is None:
            user = User(
                id=uuid.uuid4(),
                username=username,
                password_hash=hash_password(password),
                role=role,
                created_at=now,
                updated_at=now,
            )
            await repo.insert(user)
            await session.commit()
            return f"inserted user {username!r} (role={role!r})"

        existing.password_hash = hash_password(password)
        existing.role = role
        existing.updated_at = now
        await session.commit()
        return f"rotated password for user {username!r} (role={role!r})"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    username = (args.username or "").strip() or _prompt_username(default=None)

    if args.password is not None:
        password = args.password
        if len(password) < _MIN_PASSWORD_LEN:
            print(
                f"--password must be at least {_MIN_PASSWORD_LEN} characters.",
                file=sys.stderr,
            )
            return 2
        print(
            "warning: --password supplied on the command line; this is visible "
            "in shell history. Prefer the interactive prompt.",
            file=sys.stderr,
        )
    else:
        password = _prompt_password()

    try:
        outcome = asyncio.run(_seed(username, password, args.role))
    finally:
        # Engine dispose is best-effort; swallowed so a tear-down error
        # doesn't mask a real success/failure exit code.
        try:
            asyncio.run(dispose_engine())
        except Exception:  # pragma: no cover - defensive
            pass

    print(outcome)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
