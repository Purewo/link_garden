"""Integration tests for the cover upload pipeline.

These tests exercise :func:`app.features.covers.service.upload_cover` end
to end against a real filesystem (a per-test ``tmp_path`` directory)
with a fake ``CardService``. They cover the full validation surface
the spec calls out:

* MIME / Content-Type rejection (415 ``cover_bad_type``).
* Magic-byte spoof detection (400 ``invalid_image``).
* Oversized payload abort (413 ``cover_too_large``).
* Dimension floor + cap (400 ``cover_dim_invalid``).
* Pillow ``verify()`` rejection of corrupt images (400 ``invalid_image``).
* Atomic write — the ``.tmp`` artifact never lingers on success.
* Sibling cleanup — switching ``.png`` to ``.jpg`` removes the old file.
* DB update — ``cards.cover`` is overwritten in the same call with the
  cache-busted public URL.

The router layer (``POST /api/v1/covers``) is exercised against a
freshly-built FastAPI app that mounts only the covers router, stubs
the session, and overrides the admin dep imported from
``app.features.auth.deps``.
"""

from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import (
    BadRequest,
    NotFound,
    PayloadTooLarge,
    UnsupportedMediaType,
    register_handlers,
)
from app.features.auth.deps import _require_admin
from app.features.covers import routes as covers_routes
from app.features.covers.service import upload_cover

# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #


def _png_bytes(width: int = 320, height: int = 240, color: str = "red") -> bytes:
    """Return a real PNG with the given dimensions."""

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(width: int = 320, height: int = 240, color: str = "blue") -> bytes:
    """Return a real JPEG with the given dimensions."""

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _webp_bytes(width: int = 320, height: int = 240, color: str = "green") -> bytes:
    """Return a real WebP with the given dimensions."""

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="WEBP")
    return buf.getvalue()


@dataclass
class FakeCard:
    """Tiny stand-in for the cards ORM row exposed via ``CardRead``.

    Populated with every field ``CardRead`` requires so the response
    schema validates cleanly when the service builds the envelope.
    """

    id: UUID
    title: str = "Sample card"
    slug: str = "sample-card"
    category: str = "external"
    group: str | None = None
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    cover: str | None = None
    archived: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    url: str | None = "https://example.com"


@dataclass
class FakeCardService:
    """In-memory cards service used in place of the real one for these tests."""

    cards: dict[UUID, FakeCard] = field(default_factory=dict)
    attach_cover_calls: list[tuple[UUID, str]] = field(default_factory=list)

    async def get_by_id(self, card_id: UUID) -> FakeCard | None:
        return self.cards.get(card_id)

    async def attach_cover(self, card_id: UUID, url: str) -> FakeCard:
        self.attach_cover_calls.append((card_id, url))
        card = self.cards[card_id]
        card.cover = url
        return card


class FakeUploadFile:
    """Minimal duck-typed substitute for :class:`fastapi.UploadFile`.

    The service only touches ``.content_type`` and ``.file.read``, so we
    avoid the full Starlette/UploadFile dance — which simplifies the
    test surface considerably.
    """

    def __init__(self, data: bytes, content_type: str | None) -> None:
        self.file = io.BytesIO(data)
        self.content_type = content_type
        self.filename = "upload.bin"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Build a :class:`Settings` instance pointed at a temp static dir."""

    monkeypatch.setenv("JWT_SECRET", "Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_x")
    monkeypatch.setenv("APP_ENV", "test")
    s = Settings(  # type: ignore[call-arg]
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
        STATIC_DIR=tmp_path,
        COVERS_PUBLIC_PREFIX="/covers",
        MAX_COVER_BYTES=1_000_000,
        MAX_COVER_DIM=2048,
        ALLOWED_ORIGINS="http://localhost:5173",
        APP_ENV="test",
        JWT_SECRET="Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_x",
    )
    s.covers_dir.mkdir(parents=True, exist_ok=True)
    return s


@pytest.fixture
def card_id() -> UUID:
    return uuid4()


@pytest.fixture
def repo(card_id: UUID) -> FakeCardService:
    return FakeCardService(cards={card_id: FakeCard(id=card_id)})


# --------------------------------------------------------------------------- #
# Service-layer tests
# --------------------------------------------------------------------------- #


class TestUploadCoverService:
    """Exercises :func:`upload_cover` against a real filesystem."""

    async def test_accepts_png(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(_png_bytes(400, 300), "image/png")
        result = await upload_cover(
            upload=upload,
            card_id=card_id,
            session=None,  # type: ignore[arg-type]
            settings=settings,
            card_service=repo,
        )
        assert result.ok is True
        assert result.width == 400
        assert result.height == 300
        assert result.url.startswith(f"/covers/{card_id}.png?v=")
        target = settings.covers_dir / f"{card_id}.png"
        assert target.exists()
        # No leftover .tmp.
        assert not (settings.covers_dir / f"{card_id}.png.tmp").exists()
        # Service received the cover update.
        assert repo.attach_cover_calls == [(card_id, result.url)]

    async def test_accepts_jpeg(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(_jpeg_bytes(500, 400), "image/jpeg")
        result = await upload_cover(
            upload=upload,
            card_id=card_id,
            session=None,  # type: ignore[arg-type]
            settings=settings,
            card_service=repo,
        )
        assert result.url.startswith(f"/covers/{card_id}.jpg?v=")
        assert (settings.covers_dir / f"{card_id}.jpg").exists()

    async def test_accepts_webp(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(_webp_bytes(300, 300), "image/webp")
        result = await upload_cover(
            upload=upload,
            card_id=card_id,
            session=None,  # type: ignore[arg-type]
            settings=settings,
            card_service=repo,
        )
        assert result.url.startswith(f"/covers/{card_id}.webp?v=")

    async def test_unknown_card_returns_404(
        self, settings: Settings, repo: FakeCardService
    ) -> None:
        upload = FakeUploadFile(_png_bytes(), "image/png")
        with pytest.raises(NotFound) as excinfo:
            await upload_cover(
                upload=upload,
                card_id=uuid4(),
                session=None,  # type: ignore[arg-type]
                settings=settings,
                card_service=repo,
            )
        assert excinfo.value.code == "card_not_found"

    async def test_rejects_bad_content_type(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(_png_bytes(), "image/gif")
        with pytest.raises(UnsupportedMediaType) as excinfo:
            await upload_cover(
                upload=upload,
                card_id=card_id,
                session=None,  # type: ignore[arg-type]
                settings=settings,
                card_service=repo,
            )
        assert excinfo.value.code == "cover_bad_type"

    async def test_rejects_missing_content_type(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(_png_bytes(), None)
        with pytest.raises(UnsupportedMediaType):
            await upload_cover(
                upload=upload,
                card_id=card_id,
                session=None,  # type: ignore[arg-type]
                settings=settings,
                card_service=repo,
            )

    async def test_rejects_oversize_body(
        self,
        tmp_path: Path,
        repo: FakeCardService,
        card_id: UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("JWT_SECRET", "Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_x")
        small = Settings(  # type: ignore[call-arg]
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            STATIC_DIR=tmp_path,
            MAX_COVER_BYTES=1024,  # 1 KiB cap
            MAX_COVER_DIM=2048,
            APP_ENV="test",
            JWT_SECRET="Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_x",
        )
        small.covers_dir.mkdir(parents=True, exist_ok=True)
        upload = FakeUploadFile(_png_bytes(800, 600), "image/png")  # > 1 KiB
        with pytest.raises(PayloadTooLarge) as excinfo:
            await upload_cover(
                upload=upload,
                card_id=card_id,
                session=None,  # type: ignore[arg-type]
                settings=small,
                card_service=repo,
            )
        assert excinfo.value.code == "cover_too_large"

    async def test_rejects_dimension_floor(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(_png_bytes(100, 100), "image/png")
        with pytest.raises(BadRequest) as excinfo:
            await upload_cover(
                upload=upload,
                card_id=card_id,
                session=None,  # type: ignore[arg-type]
                settings=settings,
                card_service=repo,
            )
        assert excinfo.value.code == "cover_dim_invalid"

    async def test_rejects_dimension_cap(
        self,
        tmp_path: Path,
        repo: FakeCardService,
        card_id: UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("JWT_SECRET", "Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_x")
        # Lower MAX_COVER_DIM so we don't have to render a 5000x5000 image
        # to exercise the cap.
        tight = Settings(  # type: ignore[call-arg]
            DATABASE_URL="sqlite+aiosqlite:///:memory:",
            STATIC_DIR=tmp_path,
            MAX_COVER_BYTES=5_242_880,
            MAX_COVER_DIM=300,
            APP_ENV="test",
            JWT_SECRET="Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_x",
        )
        tight.covers_dir.mkdir(parents=True, exist_ok=True)
        upload = FakeUploadFile(_png_bytes(400, 400), "image/png")
        with pytest.raises(BadRequest) as excinfo:
            await upload_cover(
                upload=upload,
                card_id=card_id,
                session=None,  # type: ignore[arg-type]
                settings=tight,
                card_service=repo,
            )
        assert excinfo.value.code == "cover_dim_invalid"

    async def test_rejects_spoofed_mime(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        # JPEG bytes wrapped in a "image/png" Content-Type header.
        upload = FakeUploadFile(_jpeg_bytes(400, 300), "image/png")
        with pytest.raises(BadRequest) as excinfo:
            await upload_cover(
                upload=upload,
                card_id=card_id,
                session=None,  # type: ignore[arg-type]
                settings=settings,
                card_service=repo,
            )
        assert excinfo.value.code == "invalid_image"

    async def test_rejects_garbage_with_image_content_type(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(b"not an image at all" * 50, "image/png")
        with pytest.raises(BadRequest) as excinfo:
            await upload_cover(
                upload=upload,
                card_id=card_id,
                session=None,  # type: ignore[arg-type]
                settings=settings,
                card_service=repo,
            )
        assert excinfo.value.code == "invalid_image"

    async def test_rejects_corrupt_png_passing_signature(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        # A real PNG with the IDAT chunk's CRC corrupted so Pillow's
        # verify() raises. We rebuild the file by hand to avoid rolling
        # the dice on Pillow's tolerance.
        png = bytearray(_png_bytes(400, 300))
        # Find the IDAT chunk; corrupt its last 4 bytes (the CRC32).
        idx = png.find(b"IDAT")
        assert idx > 0, "expected an IDAT chunk in synthetic PNG"
        length = struct.unpack(">I", png[idx - 4 : idx])[0]
        crc_off = idx + 4 + length
        png[crc_off : crc_off + 4] = b"\x00\x00\x00\x00"
        # Sanity: the CRC really is wrong now.
        chunk = bytes(png[idx : idx + 4 + length])
        assert struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF) != bytes(
            png[crc_off : crc_off + 4]
        )
        upload = FakeUploadFile(bytes(png), "image/png")
        with pytest.raises(BadRequest) as excinfo:
            await upload_cover(
                upload=upload,
                card_id=card_id,
                session=None,  # type: ignore[arg-type]
                settings=settings,
                card_service=repo,
            )
        assert excinfo.value.code == "invalid_image"

    async def test_rejects_empty_body(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(b"", "image/png")
        with pytest.raises(BadRequest) as excinfo:
            await upload_cover(
                upload=upload,
                card_id=card_id,
                session=None,  # type: ignore[arg-type]
                settings=settings,
                card_service=repo,
            )
        assert excinfo.value.code == "invalid_image"

    async def test_atomic_write_no_tmp_remains(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(_png_bytes(400, 300), "image/png")
        await upload_cover(
            upload=upload,
            card_id=card_id,
            session=None,  # type: ignore[arg-type]
            settings=settings,
            card_service=repo,
        )
        leftovers = list(settings.covers_dir.glob("*.tmp"))
        assert leftovers == []

    async def test_sibling_extensions_unlinked_on_overwrite(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        # Pretend a previous PNG already exists on disk.
        existing = settings.covers_dir / f"{card_id}.png"
        existing.write_bytes(b"old png stub")
        # Upload a JPEG over it.
        upload = FakeUploadFile(_jpeg_bytes(400, 300), "image/jpeg")
        await upload_cover(
            upload=upload,
            card_id=card_id,
            session=None,  # type: ignore[arg-type]
            settings=settings,
            card_service=repo,
        )
        assert not existing.exists(), "old .png sibling should be unlinked"
        assert (settings.covers_dir / f"{card_id}.jpg").exists()

    async def test_cards_cover_updated_with_cache_buster(
        self, settings: Settings, repo: FakeCardService, card_id: UUID
    ) -> None:
        upload = FakeUploadFile(_png_bytes(400, 300), "image/png")
        result = await upload_cover(
            upload=upload,
            card_id=card_id,
            session=None,  # type: ignore[arg-type]
            settings=settings,
            card_service=repo,
        )
        assert result.url.startswith(f"/covers/{card_id}.png?v=")
        # Cache-buster is a positive integer.
        v = result.url.rsplit("?v=", 1)[1]
        assert v.isdigit() and int(v) > 0
        # Service state mirrors the response.
        assert repo.cards[card_id].cover == result.url


# --------------------------------------------------------------------------- #
# Router-layer tests (admin gate, multipart wiring, error envelope)
# --------------------------------------------------------------------------- #


@pytest.fixture
def app_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """Build a minimal FastAPI app that mounts only the covers router."""

    monkeypatch.setenv("JWT_SECRET", "Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_x")
    monkeypatch.setenv("APP_ENV", "test")

    def _build(repo: FakeCardService, *, admin: bool = True) -> FastAPI:
        from app.core.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("STATIC_DIR", str(tmp_path))
        monkeypatch.setenv("MAX_COVER_BYTES", "1000000")
        monkeypatch.setenv("MAX_COVER_DIM", "2048")
        s = get_settings()
        s.covers_dir.mkdir(parents=True, exist_ok=True)

        app = FastAPI()
        register_handlers(app)
        app.include_router(covers_routes.router, prefix="/api/v1")

        async def _stub_session() -> Any:
            yield None

        async def _stub_admin() -> Any:
            if not admin:
                from app.core.errors import Forbidden

                raise Forbidden(code="forbidden", message="Admin only")
            return object()

        # Override the session dep so the route doesn't try to open a DB
        # connection — the fake service ignores its session argument.
        app.dependency_overrides[get_session] = _stub_session
        # Admin guard is registered directly on the endpoint signature.
        app.dependency_overrides[_require_admin] = _stub_admin

        # Inject the fake service in place of ``CardService(session)``.
        monkeypatch.setattr(
            covers_routes, "CardService", lambda _session: repo
        )
        return app

    return _build


async def _post_cover(
    app: FastAPI,
    *,
    file_bytes: bytes,
    content_type: str,
    card_id: UUID,
    headers: dict[str, str] | None = None,
) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(
            "/api/v1/covers",
            files={"file": ("cover.bin", file_bytes, content_type)},
            data={"card_id": str(card_id)},
            headers=headers or {},
        )


class TestCoverRouter:
    """End-to-end multipart tests, with auth/db deps stubbed."""

    async def test_post_returns_201_and_envelope(
        self, app_factory: Any, card_id: UUID
    ) -> None:
        repo = FakeCardService(cards={card_id: FakeCard(id=card_id)})
        app = app_factory(repo)
        resp = await _post_cover(
            app,
            file_bytes=_png_bytes(400, 300),
            content_type="image/png",
            card_id=card_id,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["width"] == 400
        assert body["height"] == 300
        assert body["url"].startswith(f"/covers/{card_id}.png?v=")

    async def test_post_unknown_card_404(
        self, app_factory: Any
    ) -> None:
        # Service has no cards; upload_cover raises NotFound.
        repo = FakeCardService()
        app = app_factory(repo)
        resp = await _post_cover(
            app,
            file_bytes=_png_bytes(400, 300),
            content_type="image/png",
            card_id=uuid4(),
        )
        assert resp.status_code == 404
        body = resp.json()
        assert body["ok"] is False
        assert body["code"] == "card_not_found"

    async def test_post_bad_content_type_415(
        self, app_factory: Any, card_id: UUID
    ) -> None:
        repo = FakeCardService(cards={card_id: FakeCard(id=card_id)})
        app = app_factory(repo)
        resp = await _post_cover(
            app,
            file_bytes=_png_bytes(400, 300),
            content_type="image/gif",
            card_id=card_id,
        )
        assert resp.status_code == 415
        body = resp.json()
        assert body["code"] == "cover_bad_type"

    async def test_post_dim_too_small_400(
        self, app_factory: Any, card_id: UUID
    ) -> None:
        repo = FakeCardService(cards={card_id: FakeCard(id=card_id)})
        app = app_factory(repo)
        resp = await _post_cover(
            app,
            file_bytes=_png_bytes(50, 50),
            content_type="image/png",
            card_id=card_id,
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "cover_dim_invalid"

    async def test_post_covers_requires_auth(
        self,
        tmp_path: Path,
        card_id: UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without an admin override, an unauthenticated POST is 401."""

        from app.core.config import get_settings

        monkeypatch.setenv("JWT_SECRET", "Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_x")
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("STATIC_DIR", str(tmp_path))
        monkeypatch.setenv("MAX_COVER_BYTES", "1000000")
        monkeypatch.setenv("MAX_COVER_DIM", "2048")
        get_settings.cache_clear()
        s = get_settings()
        s.covers_dir.mkdir(parents=True, exist_ok=True)

        app = FastAPI()
        register_handlers(app)
        app.include_router(covers_routes.router, prefix="/api/v1")

        async def _stub_session() -> Any:
            yield None

        app.dependency_overrides[get_session] = _stub_session

        resp = await _post_cover(
            app,
            file_bytes=_png_bytes(400, 300),
            content_type="image/png",
            card_id=card_id,
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == "unauthenticated"
