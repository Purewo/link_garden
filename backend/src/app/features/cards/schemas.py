"""Pydantic schemas for the cards feature.

Per §3.4 of the architecture spec: every schema uses
``ConfigDict(from_attributes=True, str_strip_whitespace=True, extra='forbid')``.
Tag validation is centralised in :func:`_normalise_tags`: trim each entry,
drop empties, case-insensitively dedupe, max 16, each entry capped at 32
chars.

Shapes:

* :class:`CardListItem` — list-row projection (no body, no body_html, no url).
* :class:`CardRead` — full read shape minus the heavy ``body``/``body_html``.
* :class:`CardDetail` — read shape including ``body``/``body_html`` (only
  populated when ``category == 'local'``).
* :class:`CardCreate` — admin publish payload.
* :class:`CardUpdate` — admin partial update payload; omitted fields are
  preserved (fixes the legacy PUT-wipes-summary bug).
* :class:`CardArchive` — archive setter (``archived: bool`` required).
* :class:`CardListQuery` — query-string filters for ``GET /cards``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

__all__ = [
    "CardArchive",
    "CardCategory",
    "CardCreate",
    "CardDetail",
    "CardGroup",
    "CardListItem",
    "CardListQuery",
    "CardRead",
    "CardUpdate",
]


CardCategory = Literal["external", "local"]
"""Storage type: ``external`` (jumps out via ``url``) or ``local`` (in-site
markdown stored in ``body``)."""

CardGroup = Literal["技术类", "随笔类", "生活类"]
"""Content-group taxonomy (separate from storage type)."""


_MAX_TAGS: Final[int] = 16
_MAX_TAG_LENGTH: Final[int] = 32
# Markdown body cap: 256 KiB is well above any human-authored article and
# keeps Pydantic + markdown-it + nh3 from being weaponised for OOM.
_MAX_BODY_LENGTH: Final[int] = 256 * 1024


def _normalise_tags(value: object) -> list[str]:
    """Trim, drop empties, dedupe case-insensitively, cap at 16 entries.

    Raises ``ValueError`` when an individual tag exceeds 32 chars or when the
    list exceeds 16 entries. Non-list inputs raise as well — the spec pins
    tags as a JSON array.
    """

    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("tags must be a list")

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, str):
            raise ValueError("each tag must be a string")
        tag = raw.strip()
        if not tag:
            continue
        if len(tag) > _MAX_TAG_LENGTH:
            raise ValueError(
                f"tag exceeds {_MAX_TAG_LENGTH} characters: {tag[:8]}…"
            )
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag)
    if len(cleaned) > _MAX_TAGS:
        raise ValueError(f"tags must not exceed {_MAX_TAGS} entries")
    return cleaned


class _BaseSchema(BaseModel):
    """Shared model_config for every schema in this module."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        extra="forbid",
    )


# --------------------------------------------------------------------------- #
# Read shapes                                                                 #
# --------------------------------------------------------------------------- #


class CardListItem(_BaseSchema):
    """List-row projection of a card. Used by ``GET /cards``."""

    id: UUID
    slug: str
    title: str
    category: CardCategory
    group: CardGroup | None = None
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    cover: str | None = None
    archived: bool = False
    created_at: datetime


class CardRead(CardListItem):
    """Full read shape minus body/body_html. Returned by archive endpoint."""

    url: str | None = None
    updated_at: datetime


class CardDetail(CardRead):
    """Detail read shape including raw body and rendered HTML.

    ``body`` and ``body_html`` are only populated when ``category == 'local'``
    so external cards stay light over the wire.
    """

    body: str | None = None
    body_html: str | None = None


# --------------------------------------------------------------------------- #
# Write shapes                                                                #
# --------------------------------------------------------------------------- #


def _validate_url(value: str | None) -> str | None:
    """Validate a candidate URL string. ``None``/empty -> ``None``."""

    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    # AnyHttpUrl accepts http/https only. We coerce to str so storage stays
    # a plain column without Pydantic types leaking into the ORM.
    AnyHttpUrl(value)  # type: ignore[arg-type]
    return value


class CardCreate(_BaseSchema):
    """Admin publish payload.

    Validates ``external ⇒ url`` and ``local ⇒ body`` after the field-level
    coercions run, so a payload with both/neither is rejected before the
    service is invoked.
    """

    title: str = Field(min_length=1, max_length=255)
    category: CardCategory
    group: CardGroup | None = None
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    cover: str | None = Field(default=None, max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    body: str | None = Field(default=None, max_length=_MAX_BODY_LENGTH)
    slug: str | None = Field(default=None, max_length=200)

    @field_validator("summary", mode="before")
    @classmethod
    def _coerce_summary(cls, value: object) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError("summary must be a string")
        return value

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> list[str]:
        return _normalise_tags(value)

    @field_validator("url", mode="before")
    @classmethod
    def _coerce_url(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("url must be a string")
        return _validate_url(value)

    @field_validator("cover", mode="before")
    @classmethod
    def _coerce_cover(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("cover must be a string")
        value = value.strip()
        if not value:
            return None
        # Cover may be a relative path (``/covers/<id>.png``) or an absolute
        # http(s) URL. Reject anything else early.
        if value.startswith("/"):
            return value
        AnyHttpUrl(value)  # type: ignore[arg-type]
        return value

    @field_validator("slug", mode="before")
    @classmethod
    def _coerce_slug(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("slug must be a string")
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def _enforce_category_coupling(self) -> CardCreate:
        if self.category == "external":
            if not self.url:
                raise ValueError("url is required for external cards")
        else:
            if not self.body or not self.body.strip():
                raise ValueError("body is required for local cards")
        return self


class CardUpdate(_BaseSchema):
    """Admin partial update payload.

    Every field is optional. Omitted fields are preserved by the service so a
    PUT with only ``{title: '…'}`` no longer wipes ``summary``/``cover`` — a
    fix for a documented P1 bug from phase 1.

    The category/url/body coupling is re-checked against the merged result in
    the service layer, since this schema cannot see the current row.
    """

    title: str | None = Field(default=None, min_length=1, max_length=255)
    category: CardCategory | None = None
    group: CardGroup | None = None
    summary: str | None = None
    tags: list[str] | None = None
    cover: str | None = Field(default=None, max_length=512)
    url: str | None = Field(default=None, max_length=2048)
    body: str | None = Field(default=None, max_length=_MAX_BODY_LENGTH)
    slug: str | None = Field(default=None, max_length=200)

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, value: object) -> list[str] | None:
        if value is None:
            return None
        return _normalise_tags(value)

    @field_validator("url", mode="before")
    @classmethod
    def _coerce_url(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("url must be a string")
        value = value.strip()
        if not value:
            return None
        AnyHttpUrl(value)  # type: ignore[arg-type]
        return value

    @field_validator("cover", mode="before")
    @classmethod
    def _coerce_cover(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("cover must be a string")
        value = value.strip()
        if not value:
            return None
        if value.startswith("/"):
            return value
        AnyHttpUrl(value)  # type: ignore[arg-type]
        return value

    @field_validator("slug", mode="before")
    @classmethod
    def _coerce_slug(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("slug must be a string")
        value = value.strip()
        return value or None


class CardArchive(_BaseSchema):
    """Setter for the archive endpoint. ``archived`` is required (no default).

    Removing the legacy "empty body archives" surprise from phase 1 is the
    whole point of the explicit required field.
    """

    archived: bool


# --------------------------------------------------------------------------- #
# Query                                                                       #
# --------------------------------------------------------------------------- #


class CardListQuery(_BaseSchema):
    """Query-string filters for ``GET /cards``."""

    category: CardCategory | None = None
    group: CardGroup | None = None
    tag: str | None = Field(default=None, max_length=_MAX_TAG_LENGTH)
    q: str | None = Field(default=None, max_length=200)
    include_archived: bool = False

    @field_validator("tag", mode="before")
    @classmethod
    def _coerce_tag(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("tag must be a string")
        value = value.strip()
        return value or None

    @field_validator("q", mode="before")
    @classmethod
    def _coerce_q(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("q must be a string")
        value = value.strip()
        return value or None
