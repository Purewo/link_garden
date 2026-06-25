"""Pydantic schemas for the auth feature.

LoginRequest, TokenResponse, UserRead are the only public shapes.
Per the phase-2 spec (§3.4), users are not self-registerable in v1, so there
is no `UserCreate` exposed here — the seeder script handles that internally.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserRead(BaseModel):
    """Public read view of a user row."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        extra="forbid",
    )

    id: UUID
    username: str
    role: str
    created_at: datetime


class LoginRequest(BaseModel):
    """Body of `POST /api/v1/auth/login`.

    Bounds match the user table widths in §3.3 so over-long inputs are
    rejected with a 422 before they reach bcrypt (which itself truncates at
    72 bytes).
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    """Success body of `POST /api/v1/auth/login`.

    `expires_in` is seconds, mirroring the conventional OAuth2 token
    response shape so the frontend can store an absolute deadline if it
    wants to.
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
    )

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserRead
