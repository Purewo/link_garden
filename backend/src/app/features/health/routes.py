"""Health endpoint. Never touches the database.

Mounted twice:

* ``GET /api/v1/health`` (versioned mirror via the v1 router).
* ``GET /api/health`` (registered directly in ``app.main`` so external monitors
  remain stable across the v1 → v2 jump).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.errors import OkResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=OkResponse, summary="Liveness probe")
async def health() -> OkResponse:
    """Return the liveness envelope ``{"ok": true}``."""

    return OkResponse()


__all__ = ["router"]
