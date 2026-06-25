"""Unit tests for ``scripts.migrate_from_json``.

The tests stand up an in-memory aiosqlite engine, create the schema via
``Base.metadata.create_all`` (no Alembic in the test loop), seed the admin
user, then run the migration against the committed fixture cards.json.

Coverage goals (per phase-2 §9 row B8 deliverable):
- happy path: external + local rows insert with correct fields
- archived flag carries through
- missing markdown is aborted gracefully (no DB write for that row)
- orphan notes are surfaced but not inserted
- ``group`` defaults to None when legacy data omits it
- idempotency: second run inserts zero new rows
- ``--dry-run`` rolls back the entire transaction
- ``--report-html`` writes a non-empty HTML audit
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ``backend/scripts`` is not on ``pythonpath`` by default (pyproject pins only
# ``src``). Adding the parent directory of ``scripts`` keeps the import as
# ``scripts.migrate_from_json`` without poking at the build config.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.migrate_from_json import (  # noqa: E402
    MigrationPlan,
    RowReport,
    _build_arg_parser,
    find_orphan_notes,
    load_legacy_cards,
    render_report_html,
    run_migration,
)

from app.core.db import Base  # noqa: E402
from app.features.auth.models import User  # noqa: E402
from app.features.cards.models import Card  # noqa: E402
from scripts import migrate_from_json  # noqa: E402

# Fixtures live alongside the tests: tests/fixtures/{cards.json,notes/*.md}.
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE_JSON = FIXTURES_DIR / "cards.json"
FIXTURE_NOTES = FIXTURES_DIR / "notes"


# ---------------------------------------------------------------------------
# Engine + session fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_engine() -> AsyncIterator[Any]:
    """Fresh in-memory SQLite engine per test (full schema isolation)."""

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(async_engine: Any) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=async_engine, expire_on_commit=False, class_=AsyncSession
    )


@pytest_asyncio.fixture
async def seeded_admin(session_factory: async_sessionmaker[AsyncSession]) -> User:
    """Insert a single admin row before each test."""

    async with session_factory() as session:
        user = User(
            username="admin",
            password_hash="$2b$12$placeholderplaceholderplaceholderplaceholderpl",
            role="admin",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


def _identity_render(text: str) -> str:
    """Stand-in for ``services.markdown.render_markdown``.

    B3 owns the real renderer; the migration test pins behaviour against a
    deterministic, no-op pipeline so we don't couple to nh3's allowlist
    evolution.
    """

    return f"<RENDERED>{text}</RENDERED>"


# ---------------------------------------------------------------------------
# load_legacy_cards / find_orphan_notes
# ---------------------------------------------------------------------------


def test_load_legacy_cards_returns_list_of_dicts() -> None:
    cards = load_legacy_cards(FIXTURE_JSON)
    assert isinstance(cards, list)
    assert len(cards) >= 5
    assert all(isinstance(c, dict) for c in cards)
    assert cards[0]["id"] == "first-local-article"


def test_load_legacy_cards_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_legacy_cards(tmp_path / "absent.json")


def test_load_legacy_cards_rejects_non_list(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError, match="list at top level"):
        load_legacy_cards(bad)


def test_find_orphan_notes_lists_unreferenced_files() -> None:
    cards = load_legacy_cards(FIXTURE_JSON)
    orphans = find_orphan_notes(FIXTURE_NOTES, cards)
    assert "orphan-draft.md" in orphans
    # the referenced markdown files must not appear
    assert "first-local-article.md" not in orphans
    assert "third-archived-local.md" not in orphans


# ---------------------------------------------------------------------------
# CLI arg parser
# ---------------------------------------------------------------------------


def test_arg_parser_requires_json_and_notes() -> None:
    parser = _build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(
        [
            "--json-file",
            "x.json",
            "--notes-dir",
            "notes",
            "--owner-username",
            "admin",
            "--dry-run",
        ]
    )
    assert args.dry_run is True
    assert args.owner_username == "admin"
    assert args.report_html is None


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_happy_path(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_admin: User,
) -> None:
    async with session_factory() as session:
        plan = await run_migration(
            json_path=FIXTURE_JSON,
            notes_dir=FIXTURE_NOTES,
            owner_username="admin",
            session=session,
            dry_run=False,
            render_markdown=_identity_render,
        )

    # 3 importable rows (1st local, 2nd external, 3rd archived local),
    # 1 external without created_at (fifth), 1 abort (fourth missing md).
    assert plan.inserted == 4
    assert plan.aborts == 1
    assert plan.skipped == 0
    # The orphan-draft.md fixture must surface.
    assert "orphan-draft.md" in plan.orphan_notes

    async with session_factory() as session:
        cards = (await session.execute(select(Card))).scalars().all()

    by_slug = {c.slug: c for c in cards}
    assert "first-local-article" in by_slug
    assert "second-external-link" in by_slug
    assert "third-archived-local" in by_slug
    assert "fifth-no-created-at" in by_slug
    assert "fourth-missing-md" not in by_slug  # aborted

    first = by_slug["first-local-article"]
    assert first.category == "local"
    assert first.body is not None and first.body.startswith("# First local article")
    assert first.body_html == _identity_render(first.body)
    # tag dedupe (case-insensitive) collapses 'alpha' + 'Alpha' down to one
    assert len(first.tags) == 2
    assert any(t.lower() == "alpha" for t in first.tags)
    assert first.group == "技术类"

    second = by_slug["second-external-link"]
    assert second.category == "external"
    assert second.url == "https://example.com/second"
    assert second.body is None
    assert second.body_html is None

    third = by_slug["third-archived-local"]
    assert third.archived is True

    fifth = by_slug["fifth-no-created-at"]
    assert fifth.category == "external"
    assert fifth.group is None


# ---------------------------------------------------------------------------
# Missing owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_owner_aborts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(LookupError, match="not found"):
            await run_migration(
                json_path=FIXTURE_JSON,
                notes_dir=FIXTURE_NOTES,
                owner_username="ghost",
                session=session,
                render_markdown=_identity_render,
            )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_admin: User,
) -> None:
    async with session_factory() as session:
        first = await run_migration(
            json_path=FIXTURE_JSON,
            notes_dir=FIXTURE_NOTES,
            owner_username="admin",
            session=session,
            render_markdown=_identity_render,
        )
    async with session_factory() as session:
        second = await run_migration(
            json_path=FIXTURE_JSON,
            notes_dir=FIXTURE_NOTES,
            owner_username="admin",
            session=session,
            render_markdown=_identity_render,
        )
        cards = (await session.execute(select(Card))).scalars().all()

    assert first.inserted >= 1
    assert second.inserted == 0
    # Skipped count equals the number of rows the first run inserted.
    assert second.skipped == first.inserted
    # Total card count must not have grown between runs.
    assert len(cards) == first.inserted


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_rolls_back(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_admin: User,
) -> None:
    async with session_factory() as session:
        plan = await run_migration(
            json_path=FIXTURE_JSON,
            notes_dir=FIXTURE_NOTES,
            owner_username="admin",
            session=session,
            dry_run=True,
            render_markdown=_identity_render,
        )

    async with session_factory() as session:
        cards = (await session.execute(select(Card))).scalars().all()

    assert plan.inserted >= 1
    assert plan.dry_run is True
    # Crucially: zero rows visible after rollback.
    assert cards == []


# ---------------------------------------------------------------------------
# Missing markdown abort path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_markdown_aborts_row_only(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_admin: User,
) -> None:
    async with session_factory() as session:
        plan = await run_migration(
            json_path=FIXTURE_JSON,
            notes_dir=FIXTURE_NOTES,
            owner_username="admin",
            session=session,
            render_markdown=_identity_render,
        )

    aborted = [r for r in plan.rows if r.status == "aborted"]
    assert len(aborted) == 1
    assert aborted[0].legacy_id == "fourth-missing-md"
    assert any("markdown file missing" in n for n in aborted[0].notes)

    async with session_factory() as session:
        cards = (await session.execute(select(Card))).scalars().all()
    # The aborted row was never inserted but the rest were.
    assert all(c.slug != "fourth-missing-md" for c in cards)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------


def test_render_report_html_emits_summary_and_rows() -> None:
    plan = MigrationPlan(
        rows=[
            RowReport(
                legacy_id="x",
                title="<bold>X</bold>",
                status="inserted",
                new_id="11111111-1111-1111-1111-111111111111",
                category="local",
                body_html_bytes=42,
            ),
            RowReport(
                legacy_id="y",
                title="Y",
                status="aborted",
                notes=["missing markdown"],
            ),
        ],
        inserted=1,
        aborts=1,
        orphan_notes=["orphan-draft.md"],
        json_path=Path("cards.json"),
        notes_dir=Path("notes"),
        owner_username="admin",
    )
    html = render_report_html(plan)
    assert "<!doctype html>" in html
    assert "inserted: 1" in html
    assert "aborts: 1" in html
    # HTML-escapes the title text.
    assert "&lt;bold&gt;X&lt;/bold&gt;" in html
    assert "orphan-draft.md" in html
    assert "status-aborted" in html


@pytest.mark.asyncio
async def test_main_writes_report_html(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    async_engine: Any,
    session_factory: async_sessionmaker[AsyncSession],
    seeded_admin: User,
) -> None:
    """End-to-end invocation with --report-html.

    We patch the script's settings + session factory to use the in-memory
    engine so the test doesn't depend on a real .env or a writable cwd.
    Because this test is itself running inside an asyncio loop, we cannot
    call ``main()`` directly (it uses ``asyncio.run``). Instead we exercise
    the underlying ``_run_with_settings`` coroutine + ``render_report_html``,
    which together implement everything the CLI does.
    """

    from app.core import db as db_module
    from app.core.config import Settings

    monkeypatch.setattr(db_module, "_engine", async_engine, raising=False)
    monkeypatch.setattr(db_module, "_session_factory", session_factory, raising=False)

    fake_settings = Settings(  # type: ignore[call-arg]
        JWT_SECRET="Z9mK0vQ8tP1wL3xR7yS5jH2nB4cF6aE0G8hT_secret_for_tests_only",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    monkeypatch.setattr(migrate_from_json, "_resolve_render_markdown", lambda: _identity_render)
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: fake_settings,
    )

    args = _build_arg_parser().parse_args(
        [
            "--json-file",
            str(FIXTURE_JSON),
            "--notes-dir",
            str(FIXTURE_NOTES),
            "--owner-username",
            "admin",
            "--report-html",
            str(tmp_path / "report.html"),
        ]
    )
    plan = await migrate_from_json._run_with_settings(args)
    report_path = args.report_html
    report_path.write_text(migrate_from_json.render_report_html(plan), encoding="utf-8")

    assert plan.inserted >= 1
    assert report_path.exists()
    html = report_path.read_text(encoding="utf-8")
    assert "LinkGarden migration report" in html
    assert "first-local-article" in html
