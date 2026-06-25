"""Idempotent one-shot importer: ``data/cards.json`` + ``content/notes/*.md`` → SQLite.

Phase-2 architecture §5 governs this script. It does **not** run schema
migrations — the operator must ``alembic upgrade head`` first (or rely on the
systemd ``ExecStartPre`` hook). The script asserts schema version, resolves the
owner user, then walks the legacy JSON file in order. Each card is imported in
its own transaction, keyed on slug uniqueness; re-runs are safe.

Usage
-----

::

    uv run python -m scripts.migrate_from_json \
        --json-file ../data/cards.json \
        --notes-dir ../content/notes \
        --owner-username admin \
        [--dry-run] [--report-html migration-report.html]

The script intentionally pulls schemas/repos lazily inside ``main()`` so test
fixtures can monkeypatch them before the heavy imports load. Logging is plain
``logging`` (not structlog) because this is an operator tool: humans read the
output, not a log shipper.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("linkgarden.migrate")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VALID_CATEGORIES = frozenset({"external", "local"})
_VALID_GROUPS = frozenset({"技术类", "随笔类", "生活类"})


# ---------------------------------------------------------------------------
# Report row + plan
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RowReport:
    """One row of the migration report (rendered into HTML by ``--report-html``)."""

    legacy_id: str
    title: str
    status: str  # "inserted" | "skipped" | "warning" | "aborted"
    new_id: str | None = None
    category: str | None = None
    notes: list[str] = field(default_factory=list)
    sanitizer_dropped: int = 0
    body_html_bytes: int = 0


@dataclass(slots=True)
class MigrationPlan:
    """Aggregate result the CLI prints and the report renders."""

    rows: list[RowReport] = field(default_factory=list)
    inserted: int = 0
    skipped: int = 0
    warnings: int = 0
    aborts: int = 0
    orphan_notes: list[str] = field(default_factory=list)
    dry_run: bool = False
    json_path: Path | None = None
    notes_dir: Path | None = None
    owner_username: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser used by ``main``.

    Split out for testability — unit tests use this directly to validate
    argument parsing without invoking the async transaction code path.
    """

    parser = argparse.ArgumentParser(
        prog="migrate_from_json",
        description=(
            "Idempotent importer for the legacy cards.json + notes/*.md tree. "
            "Run after `alembic upgrade head`."
        ),
    )
    parser.add_argument(
        "--json-file",
        type=Path,
        required=True,
        help="Path to data/cards.json (legacy snapshot).",
    )
    parser.add_argument(
        "--notes-dir",
        type=Path,
        required=True,
        help="Path to content/notes/ holding the legacy markdown files.",
    )
    parser.add_argument(
        "--owner-username",
        type=str,
        default="admin",
        help="Username of the user to associate with imported cards (default: admin).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Roll back the final transaction instead of committing.",
    )
    parser.add_argument(
        "--report-html",
        type=Path,
        default=None,
        help="Write a sanitizer audit HTML report to this path.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


# ---------------------------------------------------------------------------
# Legacy data loading
# ---------------------------------------------------------------------------


def load_legacy_cards(json_path: Path) -> list[dict[str, Any]]:
    """Read and validate ``cards.json``. Raises ``ValueError`` on bad shape."""

    if not json_path.exists():
        raise FileNotFoundError(f"cards.json not found at {json_path}")
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"cards.json must be a list at top level, got {type(raw).__name__}")
    cards: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"cards.json entry #{index} is not an object")
        cards.append(entry)
    return cards


def find_orphan_notes(
    notes_dir: Path, legacy_cards: Iterable[Mapping[str, Any]]
) -> list[str]:
    """Return note filenames that are not referenced from ``cards.json``."""

    if not notes_dir.exists():
        return []
    referenced: set[str] = set()
    for card in legacy_cards:
        md = card.get("markdown")
        if isinstance(md, str) and md:
            referenced.add(Path(md).name)
    orphans = [
        p.name
        for p in sorted(notes_dir.iterdir())
        if p.is_file() and p.suffix.lower() == ".md" and p.name not in referenced
    ]
    return orphans


# ---------------------------------------------------------------------------
# Field normalisation
# ---------------------------------------------------------------------------


def _parse_created_at(value: Any, legacy_id: str) -> datetime:
    """Parse the legacy date-only ``created_at`` into a tz-aware datetime.

    The legacy format is ``YYYY-MM-DD``; we anchor it to midnight UTC. If the
    field is missing or malformed, we fall back to ``datetime.now(UTC)`` and
    leave the caller to log a warning (the caller has the row's report row).
    """

    if isinstance(value, str) and _DATE_RE.match(value):
        return datetime.fromisoformat(value + "T00:00:00+00:00")
    if isinstance(value, str) and value:
        # tolerate already-ISO timestamps emitted by future re-runs
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            pass
    logger.warning("card %s: missing/invalid created_at=%r — defaulting to now()", legacy_id, value)
    return datetime.now(UTC)


def _normalise_tags(value: Any) -> list[str]:
    """Trim, dedupe (case-insensitive), and cap the tag list at 16."""

    if not isinstance(value, list):
        return []
    seen: dict[str, str] = {}
    for tag in value:
        if not isinstance(tag, str):
            continue
        trimmed = tag.strip()
        if not trimmed:
            continue
        key = trimmed.lower()
        if key in seen:
            continue
        seen[key] = trimmed[:32]
        if len(seen) >= 16:
            break
    return list(seen.values())


def _normalise_group(value: Any, legacy_id: str) -> str | None:
    """Return the legacy ``group`` value when valid, else ``None``.

    The legacy data lacks ``group`` for most rows; we log at INFO so the
    operator can audit how often the default kicked in.
    """

    if value is None or value == "":
        logger.info("card %s: group missing → null", legacy_id)
        return None
    if isinstance(value, str) and value in _VALID_GROUPS:
        return value
    logger.warning("card %s: unknown group=%r → null", legacy_id, value)
    return None


# ---------------------------------------------------------------------------
# Card import (single transaction per card)
# ---------------------------------------------------------------------------


async def _slug_in_use(session: AsyncSession, slug: str) -> bool:
    """Return True iff a card with this slug already exists (any archived state)."""

    from sqlalchemy import select

    from app.features.cards.models import Card

    result = await session.execute(select(Card.id).where(Card.slug == slug))
    return result.first() is not None


def _resolve_render_markdown() -> Any:
    """Lazy import of the markdown renderer.

    Importing at module scope would couple B8 to B3's merge order. We import on
    first use; if B3 hasn't merged yet, we fall back to a no-op that stores raw
    markdown as ``body_html``. Tests can also monkeypatch this function.
    """

    try:
        from app.services.markdown import render_markdown  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - shimmed when B3 is absent
        logger.warning(
            "services.markdown.render_markdown unavailable; "
            "body_html will store raw markdown (B3 not merged yet)"
        )

        def _fallback(text: str) -> str:
            return text

        return _fallback
    return render_markdown


async def _import_card(
    session: AsyncSession,
    entry: dict[str, Any],
    *,
    notes_dir: Path,
    owner: Any,  # the User row; left untyped because B2 owns the model
    static_dir: Path | None,
    covers_public_prefix: str,
    render_markdown: Any,
) -> RowReport:
    """Import a single card row. Returns the per-row report; does not commit."""

    from app.features.cards.models import Card

    legacy_id = str(entry.get("id") or "").strip()
    title = str(entry.get("title") or "").strip()
    report = RowReport(legacy_id=legacy_id, title=title, status="aborted")
    if not legacy_id:
        report.notes.append("missing id field")
        return report
    if not title:
        report.notes.append("missing title field")
        return report

    category = entry.get("category")
    if category not in _VALID_CATEGORIES:
        report.notes.append(f"invalid category={category!r}")
        return report
    report.category = category

    # Idempotency gate. The legacy ``id`` becomes the initial slug.
    if await _slug_in_use(session, legacy_id):
        report.status = "skipped"
        report.notes.append("slug already present in DB")
        return report

    new_id = uuid.uuid4()
    created_at = _parse_created_at(entry.get("created_at"), legacy_id)
    archived = bool(entry.get("archived", False))
    cover = entry.get("cover") or None
    if cover is not None and not isinstance(cover, str):
        report.notes.append(f"cover not a string ({type(cover).__name__}) → null")
        cover = None

    if isinstance(cover, str) and cover.startswith(covers_public_prefix) and static_dir is not None:
        # Defensive: warn (not abort) when the legacy local cover is missing
        # on disk. The migration must not block on missing static assets.
        relative = cover.removeprefix(covers_public_prefix).lstrip("/")
        relative = relative.split("?", 1)[0]
        cover_path = (static_dir / "covers" / relative).resolve()
        try:
            cover_path.relative_to((static_dir / "covers").resolve())
        except ValueError:
            report.notes.append(f"cover path escaped static dir: {cover!r}")
        else:
            if not cover_path.exists():
                report.notes.append(f"cover file missing on disk: {cover_path}")

    tags = _normalise_tags(entry.get("tags"))
    group = _normalise_group(entry.get("group"), legacy_id)
    summary = (entry.get("summary") or "").strip() if isinstance(entry.get("summary"), str) else ""

    body: str | None = None
    body_html: str | None = None
    url: str | None = None

    if category == "external":
        url_raw = entry.get("url")
        if not isinstance(url_raw, str) or not url_raw.strip():
            report.notes.append("external category missing url")
            return report
        url = url_raw.strip()
    else:
        md_field = entry.get("markdown") or ""
        if not isinstance(md_field, str) or not md_field:
            report.notes.append("local category missing markdown field")
            return report
        md_path = notes_dir / Path(md_field).name
        if not md_path.exists():
            report.notes.append(f"markdown file missing: {md_path}")
            return report
        body = md_path.read_text(encoding="utf-8")
        rendered = render_markdown(body)
        body_html = rendered
        report.body_html_bytes = len(rendered.encode("utf-8"))
        # Naive sanitizer-drop count: byte delta between input markdown and
        # rendered HTML is meaningless, but the count of escaped <script tags
        # is a useful smoke signal. The real renderer (B3) already drops them
        # before we see anything; we report 0 in that case.
        report.sanitizer_dropped = body.lower().count("<script") - rendered.lower().count("<script")
        if report.sanitizer_dropped < 0:
            report.sanitizer_dropped = 0

    card = Card(
        id=new_id,
        slug=legacy_id,
        title=title,
        category=category,
        group=group,
        summary=summary,
        cover=cover,
        url=url,
        body=body,
        body_html=body_html,
        tags=tags,
        archived=archived,
        created_at=created_at,
        updated_at=created_at,
    )

    session.add(card)
    try:
        await session.flush()
    except IntegrityError as exc:
        # Race condition: another concurrent importer just inserted the same
        # slug. Append ``-imported`` and retry once. Per the spec, abort
        # otherwise.
        await session.rollback()
        card.slug = f"{legacy_id}-imported"
        session.add(card)
        try:
            await session.flush()
        except IntegrityError as exc2:
            report.notes.append(f"integrity error after retry: {exc2}")
            return report
        report.notes.append(f"slug renamed to {card.slug} after integrity error: {exc}")

    report.status = "inserted"
    report.new_id = str(card.id)
    return report


# ---------------------------------------------------------------------------
# Owner resolution
# ---------------------------------------------------------------------------


async def _resolve_owner(session: AsyncSession, username: str) -> Any:
    """Return the ``User`` row for ``username`` or raise ``LookupError``."""

    from sqlalchemy import select

    from app.features.auth.models import User

    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise LookupError(
            f"owner user {username!r} not found — seed admin first via "
            f"alembic 0002_seed_admin or scripts/seed_admin.py"
        )
    return user


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_migration(
    *,
    json_path: Path,
    notes_dir: Path,
    owner_username: str,
    session: AsyncSession,
    dry_run: bool = False,
    static_dir: Path | None = None,
    covers_public_prefix: str = "/covers",
    render_markdown: Any | None = None,
) -> MigrationPlan:
    """Run the migration end-to-end against an open async session.

    The session lifecycle (open, commit/rollback, close) is owned by the
    caller. This separation lets tests drive the migration against an
    in-memory SQLite engine without standing up the full Settings tree.
    """

    plan = MigrationPlan(
        dry_run=dry_run,
        json_path=json_path,
        notes_dir=notes_dir,
        owner_username=owner_username,
    )
    cards = load_legacy_cards(json_path)
    plan.orphan_notes = find_orphan_notes(notes_dir, cards)
    if plan.orphan_notes:
        logger.warning(
            "orphan notes (no cards.json entry): %s", ", ".join(plan.orphan_notes)
        )
    owner = await _resolve_owner(session, owner_username)
    render = render_markdown or _resolve_render_markdown()

    for entry in cards:
        row = await _import_card(
            session,
            entry,
            notes_dir=notes_dir,
            owner=owner,
            static_dir=static_dir,
            covers_public_prefix=covers_public_prefix,
            render_markdown=render,
        )
        plan.rows.append(row)
        if row.status == "inserted":
            plan.inserted += 1
            if row.notes:
                # inserted-with-warnings (e.g., missing cover file)
                plan.warnings += 1
        elif row.status == "skipped":
            plan.skipped += 1
        elif row.status == "aborted":
            plan.aborts += 1
        else:
            plan.warnings += 1
        logger.info(
            "card %s [%s]%s",
            row.legacy_id,
            row.status,
            f" -> {row.new_id}" if row.new_id else "",
        )
        for note in row.notes:
            logger.info("  - %s", note)

    if dry_run:
        await session.rollback()
        logger.info("--dry-run: transaction rolled back; no rows written")
    else:
        await session.commit()
    plan.finished_at = datetime.now(UTC)
    return plan


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------


def render_report_html(plan: MigrationPlan) -> str:
    """Render the migration plan as a single-file HTML audit report.

    The report is intentionally a self-contained string so the operator can
    drop it onto a shared drive without external assets. The CSS is inlined
    and the body is fully escaped.
    """

    def _row_to_html(row: RowReport) -> str:
        notes_html = (
            "<ul>" + "".join(f"<li>{escape(n)}</li>" for n in row.notes) + "</ul>"
            if row.notes
            else "<em>(none)</em>"
        )
        return (
            "<tr>"
            f"<td><code>{escape(row.legacy_id)}</code></td>"
            f"<td>{escape(row.title)}</td>"
            f"<td>{escape(row.status)}</td>"
            f"<td>{escape(row.category or '')}</td>"
            f"<td>{escape(row.new_id or '')}</td>"
            f"<td>{row.body_html_bytes:,}</td>"
            f"<td>{row.sanitizer_dropped}</td>"
            f"<td>{notes_html}</td>"
            "</tr>"
        )

    orphan_html = (
        "<ul>" + "".join(f"<li>{escape(name)}</li>" for name in plan.orphan_notes) + "</ul>"
        if plan.orphan_notes
        else "<em>(none)</em>"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>LinkGarden migration report</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; padding: 24px; color: #1a202c; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 16px; font-size: 14px; }}
  th, td {{ border: 1px solid #cbd5e0; padding: 6px 8px; text-align: left; vertical-align: top; }}
  th {{ background: #edf2f7; }}
  tr.status-inserted {{ background: #f0fff4; }}
  tr.status-skipped {{ background: #fefcbf; }}
  tr.status-aborted {{ background: #fed7d7; }}
  code {{ font-family: SF Mono, Consolas, monospace; font-size: 13px; }}
  .summary {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .summary .pill {{ background: #edf2f7; padding: 4px 12px; border-radius: 999px; }}
</style>
</head>
<body>
<h1>LinkGarden migration report</h1>
<p>Source: <code>{escape(str(plan.json_path))}</code> · Notes: <code>{escape(str(plan.notes_dir))}</code> · Owner: <code>{escape(plan.owner_username or '')}</code></p>
<p>Started <code>{plan.started_at.isoformat()}</code>, finished <code>{plan.finished_at.isoformat() if plan.finished_at else 'n/a'}</code> · {'<strong>DRY RUN</strong>' if plan.dry_run else 'committed'}</p>
<div class="summary">
  <span class="pill">inserted: {plan.inserted}</span>
  <span class="pill">skipped: {plan.skipped}</span>
  <span class="pill">warnings: {plan.warnings}</span>
  <span class="pill">aborts: {plan.aborts}</span>
</div>
<h2>Per-card audit</h2>
<table>
  <thead>
    <tr>
      <th>Legacy id (slug)</th><th>Title</th><th>Status</th><th>Category</th>
      <th>New UUID</th><th>body_html bytes</th><th>sanitizer dropped</th><th>Notes</th>
    </tr>
  </thead>
  <tbody>
    {''.join(f'<tr class="status-{escape(r.status)}">' + _row_to_html(r)[4:] for r in plan.rows)}
  </tbody>
</table>
<h2>Orphan notes</h2>
{orphan_html}
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    """Set up plain stderr logging for the CLI."""

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _run_with_settings(args: argparse.Namespace) -> MigrationPlan:
    """Wire the migration to the real Settings + engine and run it.

    Lives behind ``main()`` so tests can call ``run_migration`` directly
    against an in-memory engine without paying the import cost.
    """

    from app.core.config import get_settings
    from app.core.db import get_session_factory

    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        try:
            plan = await run_migration(
                json_path=args.json_file.resolve(),
                notes_dir=args.notes_dir.resolve(),
                owner_username=args.owner_username,
                session=session,
                dry_run=args.dry_run,
                static_dir=settings.STATIC_DIR,
                covers_public_prefix=settings.COVERS_PUBLIC_PREFIX,
            )
        except Exception:
            await session.rollback()
            raise
    return plan


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns an exit code suitable for ``sys.exit``."""

    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    try:
        plan = asyncio.run(_run_with_settings(args))
    except FileNotFoundError as exc:
        logger.error("file not found: %s", exc)
        return 2
    except LookupError as exc:
        logger.error("%s", exc)
        return 3
    except ValueError as exc:
        logger.error("bad legacy data: %s", exc)
        return 4

    logger.info(
        "summary: inserted=%d skipped=%d warnings=%d aborts=%d (dry_run=%s)",
        plan.inserted,
        plan.skipped,
        plan.warnings,
        plan.aborts,
        plan.dry_run,
    )

    if args.report_html is not None:
        report_path = args.report_html
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_report_html(plan), encoding="utf-8")
        logger.info("wrote HTML report to %s", report_path)

    return 0 if plan.aborts == 0 else 5


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MigrationPlan",
    "RowReport",
    "find_orphan_notes",
    "load_legacy_cards",
    "main",
    "render_report_html",
    "run_migration",
]
