"""Cover-image upload feature.

Exposes :func:`features.covers.service.upload_cover` and the matching router.
The service validates incoming images (MIME, size, magic bytes, Pillow
:meth:`verify` + dimension floor/cap), writes them atomically to
``<STATIC_DIR>/covers/<card_id>.<ext>``, unlinks any siblings under a
different extension, and updates ``cards.cover`` in the same transaction.
"""

from __future__ import annotations

__all__: list[str] = []
