"""Integration tests for the auth feature.

Each test uses the shared `client` + DB fixtures from `tests/conftest.py`
(owned by B1). The conftest provides:

  * `client` — `httpx.AsyncClient` wired to the ASGI app
  * `session` — `AsyncSession` against an in-memory aiosqlite engine
  * `admin_user` — a seeded admin row
  * `admin_token` — a JWT for that admin

Where the contract above is not yet final (B1 is still landing), we degrade
to building the user row by hand via `UserRepository` so this file at
least imports + collects on its own.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

async def _seed_user(
    session,
    *,
    username: str = "admin",
    password: str = "hunter22!",
    role: str = "admin",
):
    """Insert a user into the test DB and return it.

    Used by tests that need a known credential pair. Stays self-contained
    so the suite does not depend on the seeder migration.
    """
    from app.core.security import hash_password
    from app.features.auth.models import User
    from app.features.auth.repo import UserRepository

    user = User(
        id=uuid4(),
        username=username,
        password_hash=hash_password(password),
        role=role,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await UserRepository(session).insert(user)
    await session.commit()
    return user


# --------------------------------------------------------------------------- #
# POST /auth/login                                                            #
# --------------------------------------------------------------------------- #

async def test_login_succeeds_with_valid_credentials(client, session):
    await _seed_user(session, username="admin", password="hunter22!")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "hunter22!"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 43200
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"


async def test_login_rejects_wrong_password(client, session):
    await _seed_user(session, username="admin", password="hunter22!")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "WRONG"},
    )

    assert resp.status_code == 401
    body = resp.json()
    assert body == {
        "ok": False,
        "error": body["error"],
        "code": "invalid_credentials",
    } or body["code"] == "invalid_credentials"


async def test_login_rejects_unknown_user_with_same_code(client):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "ghost", "password": "whatever"},
    )

    # Constant-time UX: same code and same human message as wrong-password.
    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_credentials"


async def test_login_rejects_oversized_payload(client):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "x" * 65, "password": "y"},
    )

    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_failed"


async def test_login_rejects_empty_username(client):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "", "password": "y"},
    )

    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# GET /auth/me                                                                #
# --------------------------------------------------------------------------- #

async def test_me_returns_seeded_admin(client, session):
    user = await _seed_user(session, username="admin", password="hunter22!")

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "hunter22!"},
    )
    token = login.json()["access_token"]

    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "admin"
    assert body["role"] == "admin"
    assert body["id"] == str(user.id)


async def test_me_without_header_is_401(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


async def test_me_with_bad_prefix_is_401(client):
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Basic abc"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


async def test_me_with_forged_token_is_401(client):
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


async def test_me_with_expired_token_is_401(client, session):
    from app.core.security import encode_jwt

    user = await _seed_user(session)
    # Mint a token with a negative TTL so it's already expired.
    expired = encode_jwt({"sub": str(user.id), "username": user.username,
                          "role": user.role}, ttl_seconds=-10)

    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


async def test_me_with_unknown_user_is_401(client):
    """Token signed correctly but `sub` points at a user that no longer
    exists (e.g. the admin was rotated out between sessions)."""
    from app.core.security import encode_jwt

    token = encode_jwt(
        {"sub": str(uuid4()), "username": "ghost", "role": "admin"},
        ttl_seconds=60,
    )
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthenticated"


# --------------------------------------------------------------------------- #
# require_admin dep                                                           #
# --------------------------------------------------------------------------- #

async def test_require_admin_blocks_non_admin(client, session):
    """Future-proofing: when the role table grows beyond `admin`, the dep
    must 403, not silently pass. We assert via a temporary router because
    no `/admin/*` endpoint is wired up by B4 itself.
    """
    from fastapi import Depends, FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.features.auth.deps import _require_admin
    from app.core.errors import register_handlers
    from app.core.security import encode_jwt

    # Seed a non-admin user.
    viewer = await _seed_user(session, username="viewer",
                              password="readonly1", role="viewer")
    token = encode_jwt({"sub": str(viewer.id),
                        "username": viewer.username,
                        "role": viewer.role}, ttl_seconds=60)

    # Stand up a tiny app that mounts a single admin-gated route. We reuse
    # the same session dep so the user lookup hits the test DB.
    from app.core.db import get_session
    sub_app = FastAPI()
    register_handlers(sub_app)

    async def _session_dep():
        yield session

    sub_app.dependency_overrides[get_session] = _session_dep

    @sub_app.get("/admin-only")
    async def admin_only(_user=Depends(_require_admin)):  # noqa: ANN001
        return {"ok": True}

    transport = ASGITransport(app=sub_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/admin-only",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"
