"""Pydantic schemas for the cover upload feature.

Cover uploads are the one success-bodied endpoint that returns ``ok: true``
alongside the resource (per §3.9 of the architecture spec) so the frontend
can flash a toast without an extra GET. The embedded ``card`` payload uses
the cards feature's :class:`CardRead` shape; we accept ``Any`` here to keep
this module's import graph independent of the cards module (the integrator
re-types at the router layer if desired).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CoverUploadResponse(BaseModel):
    """Response body for ``POST /api/v1/covers``.

    Attributes:
        ok: Constant ``True`` so success/failure can be branched on a single
            field without inspecting status codes.
        url: Public URL of the stored cover (``COVERS_PUBLIC_PREFIX`` +
            ``/{card_id}.{ext}`` + cache-buster ``?v=<unix-ts>``).
        width: Decoded pixel width (post-Pillow verify).
        height: Decoded pixel height.
        bytes: Final on-disk size in bytes.
        card: The updated card row (``CardRead``); typed as ``Any`` here to
            avoid a hard import on the cards module.
    """

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        extra="forbid",
    )

    ok: Literal[True] = True
    url: str = Field(min_length=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    bytes: int = Field(ge=1)
    card: Any = None


__all__ = ["CoverUploadResponse"]
