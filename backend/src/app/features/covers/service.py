"""Cover upload service.

Performs the full validation + atomic write pipeline described in §3.8 of
the architecture spec:

1. Resolve card by id (404 ``card_not_found``).
2. Reject Content-Type outside ``image/{png,jpeg,webp}`` (415 ``cover_bad_type``).
3. Stream into a :class:`tempfile.SpooledTemporaryFile`, aborting early at
   ``MAX_COVER_BYTES`` (413 ``cover_too_large``).
4. Sniff magic bytes (PNG/JPEG/WebP) — mismatch is 400 ``invalid_image``.
5. Run :py:meth:`PIL.Image.Image.verify` (parser-state-destroying), re-open,
   read dimensions; reject ``<200`` or ``>MAX_COVER_DIM`` (400
   ``cover_dim_invalid`` / ``invalid_image``).
6. Pick the extension from the sniffed type — never trust ``file.filename``.
7. Atomic write: ``<covers_dir>/<card_id>.<ext>.tmp`` then
   :func:`os.replace`. Before the rename, unlink any sibling
   ``<card_id>.*`` with a different extension so a category swap leaves one
   file on disk. Defensive ``resolve()`` check ensures the path stays
   inside the covers directory.
8. Update ``card.cover`` in the same async transaction with a cache-buster.

The service is import-light: it takes the cards service, the async session,
and the upload as plain arguments so it can be unit-tested in isolation.
The router (``routes.py``) does the FastAPI dependency wiring.
"""

from __future__ import annotations

import os
import time
from io import BytesIO
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from PIL import Image, UnidentifiedImageError

from app.core.config import Settings, get_settings
from app.core.errors import (
    BadRequest,
    NotFound,
    PayloadTooLarge,
    UnsupportedMediaType,
)
from app.features.cards.schemas import CardRead
from app.features.covers.schemas import CoverUploadResponse

if TYPE_CHECKING:
    from fastapi import UploadFile
    from sqlalchemy.ext.asyncio import AsyncSession


# Streaming chunk size: 64 KiB is a comfortable middle ground between
# syscall overhead and memory pressure given the 5 MiB cap.
_CHUNK_SIZE: Final[int] = 64 * 1024

# Spool-to-disk threshold for :class:`SpooledTemporaryFile`. Smaller than
# the cap so we don't burn 5 MiB of resident memory per concurrent upload.
_SPOOL_MAX: Final[int] = 1 * 1024 * 1024

# Minimum image dimension (px). Per §3.8 step 5: covers below 200x200 are
# rejected. The maximum is parameterised via ``Settings.MAX_COVER_DIM``.
_MIN_DIM: Final[int] = 200

# Allowed (sniffed) MIME types mapped to canonical file extensions.
_MIME_TO_EXT: Final[dict[str, str]] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

# Allowed extensions used both for picking the destination filename and
# for unlinking stale siblings on overwrite.
_ALLOWED_EXTS: Final[tuple[str, ...]] = ("png", "jpg", "jpeg", "webp")


def _sniff_mime(head: bytes) -> str | None:
    """Identify ``head`` (>=12 bytes) as PNG / JPEG / WebP.

    Returns the canonical MIME type, or ``None`` if no signature matches.
    Reads only file headers — there is no full decode here; that comes
    later via Pillow.
    """

    if len(head) >= 8 and head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(head) >= 3 and head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _spool_upload(upload: UploadFile, max_bytes: int) -> SpooledTemporaryFile[bytes]:
    """Copy ``upload`` into a spooled temp file, aborting at ``max_bytes``.

    Reads in :data:`_CHUNK_SIZE` chunks. Raises :class:`PayloadTooLarge`
    the moment the running total exceeds the cap, so a malicious client
    cannot exhaust disk by streaming an unbounded body.
    """

    spool: SpooledTemporaryFile[bytes] = SpooledTemporaryFile(  # noqa: SIM115
        max_size=_SPOOL_MAX, mode="w+b"
    )
    total = 0
    while True:
        chunk = upload.file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            spool.close()
            raise PayloadTooLarge(
                code="cover_too_large",
                message="Cover file exceeds the 5 MiB limit",
            )
        spool.write(chunk)
    spool.seek(0)
    return spool


def _validate_image(data: bytes, max_dim: int) -> tuple[str, int, int]:
    """Validate ``data`` is a real PNG/JPEG/WebP within the size envelope.

    Returns ``(canonical_mime, width, height)``. Raises
    :class:`BadRequest` (``invalid_image`` / ``cover_dim_invalid``) on
    failure. ``Pillow.verify`` consumes the parser state, so we open a
    second instance to read dimensions.
    """

    # Step 1: magic-byte sniff. Cheaper than letting Pillow detect.
    sniffed = _sniff_mime(data[:32])
    if sniffed is None:
        raise BadRequest(
            code="invalid_image",
            message="Cover file is not a recognised image",
        )

    # Step 2: Pillow integrity check. ``verify`` raises on truncated /
    # malformed payloads. Re-open afterwards to read dims (verify
    # destroys parser state).
    #
    # Pillow's PNG decoder occasionally raises :class:`SyntaxError`
    # (e.g. "broken PNG file") in addition to OSError/ValueError —
    # surface all four as the same machine code.
    try:
        with Image.open(BytesIO(data)) as probe:
            probe.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise BadRequest(
            code="invalid_image",
            message="Cover file is not a valid image",
        ) from exc

    try:
        with Image.open(BytesIO(data)) as img:
            pil_format = (img.format or "").upper()
            width, height = img.size
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise BadRequest(
            code="invalid_image",
            message="Cover file is not a valid image",
        ) from exc

    # Step 3: cross-check Pillow's detected format with the magic-byte
    # sniff. A mismatch means the bytes are forged — refuse.
    expected_pil: dict[str, str] = {
        "image/png": "PNG",
        "image/jpeg": "JPEG",
        "image/webp": "WEBP",
    }
    if pil_format != expected_pil[sniffed]:
        raise BadRequest(
            code="invalid_image",
            message="Cover file content does not match its declared image type",
        )

    # Step 4: dimension floor + cap.
    if width < _MIN_DIM or height < _MIN_DIM:
        raise BadRequest(
            code="cover_dim_invalid",
            message=f"Cover dimensions must be at least {_MIN_DIM}x{_MIN_DIM} pixels",
        )
    if width > max_dim or height > max_dim:
        raise BadRequest(
            code="cover_dim_invalid",
            message=f"Cover dimensions must not exceed {max_dim}x{max_dim} pixels",
        )

    return sniffed, width, height


def _safe_join(base: Path, name: str) -> Path:
    """Join ``name`` under ``base`` and refuse path traversal.

    The filename is constructed from the validated card UUID + extension
    so traversal is structurally impossible, but the defensive check
    documents intent and survives future refactors.
    """

    candidate = (base / name).resolve()
    base_resolved = base.resolve()
    if base_resolved not in candidate.parents and candidate != base_resolved:
        raise BadRequest(
            code="invalid_image",
            message="Refusing to write cover outside the covers directory",
        )
    return candidate


def _unlink_siblings(covers_dir: Path, card_id: UUID, keep_ext: str) -> None:
    """Remove ``<card_id>.<other-ext>`` siblings before the atomic replace.

    Called *before* :func:`os.replace` so a category-switching upload
    leaves exactly one cover on disk. ``ENOENT`` is ignored — the sibling
    may simply not exist.
    """

    stem = str(card_id)
    for ext in _ALLOWED_EXTS:
        if ext == keep_ext:
            continue
        sibling = covers_dir / f"{stem}.{ext}"
        try:
            sibling.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Best-effort cleanup; do not let a stale sibling poison the
            # primary upload. The next successful upload will retry.
            pass


def _write_atomically(target: Path, data: bytes) -> None:
    """Write ``data`` to ``target`` via ``.tmp`` + :func:`os.replace`.

    On POSIX :func:`os.replace` is atomic within the same filesystem;
    on Windows it's atomic in practice for our case (single writer, same
    volume). A torn write therefore can never present a half-flushed
    cover to readers.
    """

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    # ``wb`` + explicit fsync gives durability even if the worker is
    # killed mid-flight.
    with tmp_path.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, target)


async def upload_cover(
    *,
    upload: UploadFile,
    card_id: UUID,
    session: AsyncSession,
    card_service: Any,
    settings: Settings | None = None,
) -> CoverUploadResponse:
    """Validate, persist, and link a cover for ``card_id``.

    The caller (router) supplies the FastAPI ``UploadFile``, the resolved
    ``card_id``, an open ``AsyncSession``, and a card service that owns
    the cards repository internally. ``settings`` is optional — when
    omitted the cached ``get_settings()`` singleton is used so test
    callers can either pin a custom settings instance or share the
    process-wide config.

    The ``card_service`` only needs to expose two methods:

    * ``get_by_id(card_id)`` — return the row or ``None``.
    * ``attach_cover(card_id, url)`` — persist the new cover URL and
      return the refreshed row (raises 404 if the card vanished).

    Raises:
        NotFound: ``card_not_found`` — no card with the given id.
        UnsupportedMediaType: ``cover_bad_type`` — Content-Type rejected.
        PayloadTooLarge: ``cover_too_large`` — body exceeded the cap.
        BadRequest: ``invalid_image`` / ``cover_dim_invalid`` — failed
            sniff, Pillow verify, format mismatch, or dimension bounds.

    Returns:
        CoverUploadResponse: With the new public URL (cache-busted) and
        the updated ``CardRead`` payload.
    """

    settings = settings if settings is not None else get_settings()

    # --- Step 1: resolve card. Done first so we don't spend cycles
    # validating an upload for a card that doesn't exist.
    card = await card_service.get_by_id(card_id)
    if card is None:
        raise NotFound(code="card_not_found", message="Card not found")

    # --- Step 2: declared Content-Type gate. The real check is the
    # magic-byte sniff later, but rejecting obvious mismatches here saves
    # us the streaming cost on garbage uploads.
    declared = (upload.content_type or "").lower().split(";", 1)[0].strip()
    if declared not in _MIME_TO_EXT:
        raise UnsupportedMediaType(
            code="cover_bad_type",
            message="Cover must be PNG, JPEG, or WebP",
        )

    # --- Step 3: spool to disk with an early-abort size cap.
    spool = _spool_upload(upload, settings.MAX_COVER_BYTES)
    try:
        spool.seek(0)
        data = spool.read()
    finally:
        spool.close()

    if not data:
        raise BadRequest(
            code="invalid_image",
            message="Cover file is empty",
        )

    # --- Steps 4 + 5: magic-byte sniff + Pillow verify + dimensions.
    sniffed, width, height = _validate_image(data, settings.MAX_COVER_DIM)

    # --- Step 5a: the declared Content-Type must match what the bytes
    # actually are — otherwise we'd be writing a spoofed file under the
    # wrong extension at the request of an attacker. The spec calls this
    # out as "MIME confirmed via magic-byte sniff": confirmation means
    # equality, not just plausibility.
    if sniffed != declared:
        raise BadRequest(
            code="invalid_image",
            message="Cover content type does not match the file bytes",
        )

    # --- Step 6: extension from sniffed type, NOT filename.
    ext = _MIME_TO_EXT[sniffed]
    filename = f"{card_id}.{ext}"

    # --- Step 7: atomic write + sibling cleanup. Sibling cleanup runs
    # before the rename so a future read (via nginx alias) never sees two
    # files for the same card_id.
    covers_dir = settings.covers_dir
    target = _safe_join(covers_dir, filename)
    _unlink_siblings(covers_dir, card_id, ext)
    _write_atomically(target, data)

    # --- Step 8: DB update. The cache-buster pins the URL to this exact
    # version so nginx's ``Cache-Control: public, immutable`` can serve
    # the file without coordinating with the backend.
    cache_buster = int(time.time())
    public_url = f"{settings.COVERS_PUBLIC_PREFIX}/{filename}?v={cache_buster}"
    updated_card = await card_service.attach_cover(card_id, public_url)

    # Project the ORM row through ``CardRead`` so the wire shape is typed
    # and the generated openapi-typescript schema picks it up.
    card_payload = CardRead.model_validate(updated_card)

    return CoverUploadResponse(
        ok=True,
        url=public_url,
        width=width,
        height=height,
        bytes=len(data),
        card=card_payload,
    )


__all__ = ["CoverUploadResponse", "upload_cover"]
