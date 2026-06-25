"""Pydantic schemas for the cover upload feature.

Cover uploads are the one success-bodied endpoint that returns ``ok: true``
alongside the resource (per §3.9 of the architecture spec) so the frontend
can flash a toast without an extra GET. The embedded ``card`` payload uses
the cards feature's :class:`CardRead` shape so the OpenAPI schema typing
flows through ``openapi-typescript`` cleanly.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.cards.schemas import CardRead


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
        card: The updated card row, projected through :class:`CardRead`.
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
    card: CardRead


__all__ = ["CoverUploadResponse"]
