"""Integration tests for the legacy ``/api/*`` 308 redirect shim.

The new backend serves everything under ``/api/v1``. For exactly one release
after cutover, any legacy ``/api/<path>`` request (excluding ``health`` and
anything under ``v1/``) is answered with a ``308 Permanent Redirect`` to the
v1 equivalent, preserving method and body per RFC 7538.

Note: in pure aiosqlite/in-memory tests we only assert the redirect itself.
End-to-end body preservation across the redirect is exercised in later
integration suites that own real endpoints (cards/auth).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_legacy_get_redirects_to_v1(client: AsyncClient) -> None:
    response = await client.get("/api/cards", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/api/v1/cards"


@pytest.mark.asyncio
async def test_legacy_post_redirects_with_method_preserved(client: AsyncClient) -> None:
    """``308`` is the method-preserving redirect (vs 301/302)."""

    response = await client.post(
        "/api/publish",
        json={"title": "x"},
        follow_redirects=False,
    )

    assert response.status_code == 308
    assert response.headers["location"] == "/api/v1/publish"


@pytest.mark.asyncio
async def test_legacy_redirect_preserves_query_string(client: AsyncClient) -> None:
    response = await client.get(
        "/api/cards?include_archived=true&q=hello",
        follow_redirects=False,
    )

    assert response.status_code == 308
    assert response.headers["location"] == "/api/v1/cards?include_archived=true&q=hello"


@pytest.mark.asyncio
async def test_legacy_redirect_skips_health(client: AsyncClient) -> None:
    """``/api/health`` is a stable mount; the shim must not intercept it."""

    response = await client.get("/api/health", follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_legacy_redirect_skips_v1_paths(client: AsyncClient) -> None:
    """Real v1 paths must not be shadowed by the catch-all."""

    response = await client.get("/api/v1/health", follow_redirects=False)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_legacy_redirect_chains_into_v1(client: AsyncClient) -> None:
    """Following the redirect should land on a real v1 response.

    We can verify this end-to-end against the health route by hitting
    ``/api/health`` … but to confirm the chain works for any path we walk
    the redirect for the always-valid v1 health mirror, addressed via a
    legacy path that doesn't exist in the new API.

    The target route returns 404 with the standard error envelope. That's
    enough proof the redirect chain reached the v1 mount.
    """

    response = await client.get("/api/some-missing-route", follow_redirects=True)

    # We don't pin the status code here — what matters is that the redirect
    # was followed into ``/api/v1/...``. ``url.path`` reflects the final hop.
    assert str(response.url).endswith("/api/v1/some-missing-route")


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_legacy_redirect_covers_all_methods(client: AsyncClient, method: str) -> None:
    response = await client.request(method, "/api/cards/abc", follow_redirects=False)

    assert response.status_code == 308
    assert response.headers["location"] == "/api/v1/cards/abc"
