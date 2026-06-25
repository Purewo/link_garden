"""Application settings loaded once at import via pydantic-settings.

The :func:`get_settings` accessor returns a process-wide singleton. Importing
this module reads ``.env`` (when present) and the process environment; any
fatal misconfiguration (missing or too-short ``JWT_SECRET``) raises immediately
so the worker exits before serving traffic.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor relative paths to the backend root (the directory that owns
# ``pyproject.toml``), not the cwd of whoever launched the process.
_BACKEND_ROOT: Final[Path] = Path(__file__).resolve().parents[3]


# Single-token placeholder forms we reject up-front. The validator below
# also screens for ``REPLACE_ME``/``CHANGE_ME``-style ALL-CAPS sentinels and
# low-entropy strings even when the literal isn't in this set.
_PLACEHOLDER_LITERALS: Final[frozenset[str]] = frozenset(
    {"change-me", "changeme", "secret", "__unset__", "placeholder"}
)
# All-caps with underscores/digits only — exactly the shape of every
# REPLACE_ME_WITH_… sentinel that has shipped in example envs.
_ALLCAPS_SENTINEL: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9_]+$")


def _is_placeholder_secret(value: str) -> bool:
    """Return True when ``value`` is structurally a sentinel, not a secret."""

    folded = value.casefold()
    if folded in _PLACEHOLDER_LITERALS:
        return True
    if _ALLCAPS_SENTINEL.fullmatch(value):
        return True
    if "replace_me" in folded or "replaceme" in folded:
        return True
    if len(set(value)) < 16:
        return True
    return False


class Settings(BaseSettings):
    """Process-wide configuration.

    Read once at import; mutate at your own risk. All values are validated by
    pydantic at construction so misconfiguration surfaces before the first
    request.
    """

    model_config = SettingsConfigDict(
        env_file=(_BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database ---
    DATABASE_URL: str = Field(default="sqlite+aiosqlite:///./linkgarden.db")

    # --- JWT ---
    JWT_SECRET: str = Field(min_length=32)
    # ``JWT_ALG`` is a constant; surfaced as a field so it shows in /openapi
    # debug dumps but never read from env.
    JWT_ALG: Literal["HS256"] = "HS256"
    JWT_TTL_SECONDS: int = Field(default=43_200, ge=60)

    # --- Admin bootstrap (used by alembic 0002 + scripts/seed_admin.py) ---
    LG_ADMIN_USERNAME: str = Field(default="admin", min_length=1, max_length=64)
    LG_ADMIN_PASSWORD: str = Field(default="", max_length=256)

    # --- Static / cover storage ---
    STATIC_DIR: Path = Field(default=_BACKEND_ROOT / "src" / "app" / "static")
    COVERS_PUBLIC_PREFIX: str = Field(default="/covers")
    MAX_COVER_BYTES: int = Field(default=5_242_880, ge=1)
    MAX_COVER_DIM: int = Field(default=4096, ge=1)

    # --- CORS / environment ---
    ALLOWED_ORIGINS: str = Field(default="http://localhost:5173")
    APP_ENV: Literal["dev", "test", "prod"] = "dev"

    @field_validator("STATIC_DIR", mode="before")
    @classmethod
    def _resolve_static_dir(cls, value: object) -> object:
        """Resolve relative ``STATIC_DIR`` against the backend root."""

        if isinstance(value, str) and value:
            path = Path(value)
            if not path.is_absolute():
                path = (_BACKEND_ROOT / path).resolve()
            return path
        return value

    @field_validator("COVERS_PUBLIC_PREFIX")
    @classmethod
    def _normalise_covers_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            value = "/" + value
        return value.rstrip("/") or "/covers"

    @field_validator("JWT_SECRET")
    @classmethod
    def _refuse_placeholder_secret(cls, value: str, info: ValidationInfo) -> str:
        # ``min_length=32`` already covers most cases; this guards against the
        # obvious ".env.example" leakage where someone forgets to rotate.
        if _is_placeholder_secret(value):
            raise ValueError(
                "JWT_SECRET must not be a placeholder value (rotate via "
                "`openssl rand -hex 32`)"
            )
        return value

    @field_validator("LG_ADMIN_PASSWORD")
    @classmethod
    def _refuse_placeholder_admin_password(
        cls, value: str, info: ValidationInfo
    ) -> str:
        # Empty string means "do not seed", which is legal. Anything else
        # has to pass the same sentinel screen as JWT_SECRET so a forgotten
        # REPLACE_ME never reaches bcrypt.
        if value and _is_placeholder_secret(value):
            raise ValueError(
                "LG_ADMIN_PASSWORD must not be a placeholder value"
            )
        return value

    @property
    def allowed_origins(self) -> list[str]:
        """Return ``ALLOWED_ORIGINS`` as a list (split on commas, trimmed)."""

        return [item.strip() for item in self.ALLOWED_ORIGINS.split(",") if item.strip()]

    @property
    def covers_dir(self) -> Path:
        """Filesystem location for cover uploads (``STATIC_DIR/covers``)."""

        return self.STATIC_DIR / "covers"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton."""

    return Settings()  # type: ignore[call-arg]


__all__ = ["Settings", "get_settings"]
