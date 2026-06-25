"""Integration tests for the health endpoint.

Both mounts must answer:

* ``GET /api/health``    — the version-stable monitor mount
* ``GET /api/v1/health`` — the versioned mirror under ``/api/v1``

Neither path may touch the database.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_root_mount_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_health_v1_mount_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_health_endpoint_carries_request_id_header(client: AsyncClient) -> None:
    """The request-context middleware should echo a request id back."""

    response = await client.get("/api/health")

    assert "x-request-id" in response.headers
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_health_does_not_require_auth(client: AsyncClient) -> None:
    """No Authorization header is required."""

    response = await client.get("/api/health", headers={"accept": "application/json"})

    assert response.status_code == 200
