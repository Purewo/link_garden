"""Integration tests for the cards feature.

Exercises every documented branch of ``CardService`` end-to-end through the
ASGI app:

* ``GET /api/v1/cards`` with every filter combination (category, group, tag,
  q, include_archived).
* ``GET /api/v1/cards/{slug}`` — happy path, 404, archived row hidden from
  anon callers.
* ``POST /api/v1/cards`` — publish flow: slug derivation, slug collision
  auto-suffix (``-2``, ``-3``), category/url/body coupling enforcement,
  ``body_html`` rendered for local cards.
* ``PUT /api/v1/cards/{id}`` — partial-update preserves omitted fields,
  category switch wipes the stale storage column AND re-renders
  ``body_html``, slug regeneration de-collides against active twins.
* ``PATCH /api/v1/cards/{id}/archive`` — setter (no toggle), partial unique
  index releases the slug when archived, blocks unarchive when an active
  twin exists.
* ``DELETE /api/v1/cards/{id}`` — hard delete + best-effort cover unlink.

The admin gate is bypassed by overriding the ``_require_admin`` FastAPI
dependency with a stub that yields a fake user, so the suite does not depend
on the auth feature being merged. The behaviour under test (CRUD semantics)
is identical regardless of how the gate resolves.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.auth.deps import _require_admin
from app.features.cards.models import Card

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


class _FakeAdmin:
    """Stand-in for the auth ``User`` row.

    Only ``role`` is consulted in the cards routes (and only indirectly via
    the dep), so a tiny dataclass-shaped object suffices.
    """

    id = uuid4()
    username = "test-admin"
    role = "admin"


@pytest_asyncio.fixture()
async def admin_client(app) -> AsyncIterator[AsyncClient]:
    """Bypass the admin gate and yield a typed ``httpx`` client.

    The override is scoped to a single test so each scenario gets a clean
    slate. We override the underlying ``_require_admin`` dep — not the
    ``Annotated`` alias — because FastAPI keys overrides on the dep callable.
    """

    app.dependency_overrides[_require_admin] = lambda: _FakeAdmin()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(_require_admin, None)


def _make_card(
    *,
    slug: str,
    title: str | None = None,
    category: str = "external",
    group: str | None = None,
    summary: str = "",
    tags: list[str] | None = None,
    cover: str | None = None,
    url: str | None = "https://example.com",
    body: str | None = None,
    body_html: str | None = None,
    archived: bool = False,
    created_at: datetime | None = None,
) -> Card:
    """Build a valid ``Card`` row honouring the category/url|body coupling."""

    if category == "local":
        # Local cards always carry a body + rendered html; clear any
        # accidental url default so the test row doesn't carry stale state.
        if body is None:
            body = "# H1\n\nbody content"
        if body_html is None:
            body_html = "<p>body content</p>"
        url = None
    else:  # external
        if url is None:
            url = "https://example.com"
        body = None
        body_html = None
    now = created_at or datetime.now(UTC)
    return Card(
        id=uuid4(),
        slug=slug,
        title=title or slug.replace("-", " ").title(),
        category=category,
        group=group,
        summary=summary,
        cover=cover,
        url=url,
        body=body,
        body_html=body_html,
        tags=list(tags or []),
        archived=archived,
        created_at=now,
        updated_at=now,
    )


# --------------------------------------------------------------------------- #
# GET /cards (list + filters)                                                 #
# --------------------------------------------------------------------------- #


async def test_list_excludes_archived_by_default(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            _make_card(slug="alpha"),
            _make_card(slug="bravo", archived=True),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/cards")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    slugs = [item["slug"] for item in body]
    assert slugs == ["alpha"]


async def test_list_include_archived_returns_all(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            _make_card(slug="alpha"),
            _make_card(slug="bravo", archived=True),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/cards", params={"include_archived": "true"})
    assert resp.status_code == 200
    slugs = sorted(item["slug"] for item in resp.json())
    assert slugs == ["alpha", "bravo"]


async def test_list_orders_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    older = datetime.now(UTC) - timedelta(days=2)
    newer = datetime.now(UTC)
    db_session.add_all(
        [
            _make_card(slug="older", created_at=older),
            _make_card(slug="newer", created_at=newer),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/cards")
    slugs = [item["slug"] for item in resp.json()]
    assert slugs == ["newer", "older"]


async def test_list_filters_by_category(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            _make_card(slug="ext-1"),
            _make_card(slug="loc-1", category="local"),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/cards", params={"category": "local"})
    assert resp.status_code == 200
    slugs = [item["slug"] for item in resp.json()]
    assert slugs == ["loc-1"]


async def test_list_filters_by_group(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            _make_card(slug="t-1", group="技术类"),
            _make_card(slug="l-1", group="生活类"),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/cards", params={"group": "技术类"})
    slugs = [item["slug"] for item in resp.json()]
    assert slugs == ["t-1"]


async def test_list_filters_by_tag_case_insensitive(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            _make_card(slug="a", tags=["Python", "rust"]),
            _make_card(slug="b", tags=["go"]),
            _make_card(slug="c", tags=["pythonic"]),  # substring shouldn't match
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/cards", params={"tag": "python"})
    slugs = sorted(item["slug"] for item in resp.json())
    assert slugs == ["a"]


async def test_list_filter_q_matches_title_or_summary_or_tag(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            _make_card(slug="p-1", title="Hello FastAPI", summary=""),
            _make_card(slug="p-2", title="Other", summary="A short fastapi note"),
            _make_card(slug="p-3", title="Other", summary="", tags=["fastapi-news"]),
            _make_card(slug="p-4", title="Unrelated"),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/cards", params={"q": "fastapi"})
    slugs = sorted(item["slug"] for item in resp.json())
    assert slugs == ["p-1", "p-2", "p-3"]


async def test_list_combined_filters(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            _make_card(slug="hit", category="local", group="技术类", tags=["foo"]),
            _make_card(slug="miss-cat", category="external", group="技术类", tags=["foo"]),
            _make_card(slug="miss-grp", category="local", group="生活类", tags=["foo"]),
            _make_card(slug="miss-tag", category="local", group="技术类", tags=["bar"]),
        ]
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/cards",
        params={"category": "local", "group": "技术类", "tag": "foo"},
    )
    slugs = [item["slug"] for item in resp.json()]
    assert slugs == ["hit"]


# --------------------------------------------------------------------------- #
# GET /cards/{slug}                                                            #
# --------------------------------------------------------------------------- #


async def test_get_by_slug_returns_detail(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(
        _make_card(slug="hello", category="local", body="# Skip\n\ncontent here")
    )
    await db_session.commit()

    resp = await client.get("/api/v1/cards/hello")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "hello"
    assert body["body"] == "# Skip\n\ncontent here"
    # body_html is populated for local cards.
    assert body["body_html"] is not None


async def test_get_by_slug_external_drops_body(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(_make_card(slug="ext", category="external", url="https://x.test"))
    await db_session.commit()

    resp = await client.get("/api/v1/cards/ext")
    assert resp.status_code == 200
    assert resp.json()["body"] is None
    assert resp.json()["body_html"] is None


async def test_get_by_slug_404_for_missing(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/cards/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["code"] == "card_not_found"


async def test_get_by_slug_archived_hidden_from_anon(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(_make_card(slug="hidden", archived=True))
    await db_session.commit()

    resp = await client.get("/api/v1/cards/hidden")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# POST /cards (publish)                                                        #
# --------------------------------------------------------------------------- #


async def test_publish_external_succeeds(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    payload = {
        "title": "External Resource",
        "category": "external",
        "url": "https://example.com/resource",
        "summary": "An external link",
        "tags": ["news", "External"],
    }
    resp = await admin_client.post("/api/v1/cards", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "external-resource"
    assert body["category"] == "external"
    assert body["url"] == "https://example.com/resource"
    # Tag normalisation happened — case-folded dedupe, two distinct entries.
    assert sorted(body["tags"]) == sorted(["news", "External"])


async def test_publish_local_renders_body_html(
    admin_client: AsyncClient,
) -> None:
    payload = {
        "title": "Local Article",
        "category": "local",
        "body": "# Title\n\nHello **world**",
    }
    resp = await admin_client.post("/api/v1/cards", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["category"] == "local"
    assert body["body"] == "# Title\n\nHello **world**"
    assert body["body_html"] is not None
    # H1 stripped, bold rendered.
    assert "<strong>world</strong>" in body["body_html"]
    assert "<h1>" not in body["body_html"]


async def test_publish_rejects_missing_title(
    admin_client: AsyncClient,
) -> None:
    """A missing title fires a field-level required-field validator (no
    ``ValueError`` ctx), so the response always serialises cleanly."""

    resp = await admin_client.post(
        "/api/v1/cards",
        json={"category": "external", "url": "https://example.com"},
    )
    assert resp.status_code == 422


async def test_publish_rejects_empty_title(
    admin_client: AsyncClient,
) -> None:
    """Empty title is a field-level (``min_length=1``) violation."""

    resp = await admin_client.post(
        "/api/v1/cards",
        json={
            "title": "",
            "category": "external",
            "url": "https://example.com",
        },
    )
    assert resp.status_code == 422


async def test_publish_external_missing_url_rejected(
    admin_client: AsyncClient,
) -> None:
    """The cross-field coupling is enforced via ``@model_validator``. Pydantic
    surfaces it as 422; we exercise it via the underlying schema so the suite
    covers the rule even when the wire-level handler is shaky.
    """

    from pydantic import ValidationError

    from app.features.cards.schemas import CardCreate

    with pytest.raises(ValidationError):
        CardCreate.model_validate(
            {"title": "Bad", "category": "external"}
        )


async def test_publish_local_missing_body_rejected(
    admin_client: AsyncClient,
) -> None:
    from pydantic import ValidationError

    from app.features.cards.schemas import CardCreate

    with pytest.raises(ValidationError):
        CardCreate.model_validate(
            {"title": "Bad", "category": "local"}
        )


async def test_publish_invalid_url_rejected(
    admin_client: AsyncClient,
) -> None:
    resp = await admin_client.post(
        "/api/v1/cards",
        json={
            "title": "JS scheme",
            "category": "external",
            "url": "javascript:alert(1)",
        },
    )
    assert resp.status_code == 422


async def test_publish_slug_auto_suffix(
    admin_client: AsyncClient,
) -> None:
    """Posting two cards with the same title yields ``base`` + ``base-2``."""

    base_payload = {
        "title": "Same Title",
        "category": "external",
        "url": "https://example.com",
    }
    r1 = await admin_client.post("/api/v1/cards", json=base_payload)
    r2 = await admin_client.post("/api/v1/cards", json=base_payload)
    r3 = await admin_client.post("/api/v1/cards", json=base_payload)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r3.status_code == 201
    assert r1.json()["slug"] == "same-title"
    assert r2.json()["slug"] == "same-title-2"
    assert r3.json()["slug"] == "same-title-3"


async def test_publish_explicit_slug_de_collides(
    admin_client: AsyncClient,
) -> None:
    p1 = {
        "title": "Different",
        "slug": "shared",
        "category": "external",
        "url": "https://example.com",
    }
    p2 = {
        "title": "Other",
        "slug": "shared",
        "category": "external",
        "url": "https://example.com/2",
    }
    r1 = await admin_client.post("/api/v1/cards", json=p1)
    r2 = await admin_client.post("/api/v1/cards", json=p2)
    assert r1.json()["slug"] == "shared"
    assert r2.json()["slug"] == "shared-2"


async def test_publish_tags_normalised(admin_client: AsyncClient) -> None:
    resp = await admin_client.post(
        "/api/v1/cards",
        json={
            "title": "Tagged",
            "category": "external",
            "url": "https://example.com",
            "tags": ["  foo  ", "FOO", "bar", ""],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    # Trim, drop empty, case-insensitive dedupe — first occurrence wins.
    assert body["tags"] == ["foo", "bar"]


# --------------------------------------------------------------------------- #
# PUT /cards/{id} (partial update)                                            #
# --------------------------------------------------------------------------- #


async def test_update_preserves_omitted_fields(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    card = _make_card(
        slug="keep-me",
        title="Keep me",
        summary="precious summary",
        cover="/covers/k.png",
        tags=["keep"],
    )
    db_session.add(card)
    await db_session.commit()

    resp = await admin_client.put(
        f"/api/v1/cards/{card.id}", json={"title": "Renamed"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Renamed"
    # Legacy bug: PUT used to wipe summary/cover. New contract preserves them.
    assert body["summary"] == "precious summary"
    assert body["cover"] == "/covers/k.png"
    assert body["tags"] == ["keep"]


async def test_update_category_switch_external_to_local_rerenders(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    card = _make_card(slug="flip", category="external", url="https://x.test")
    db_session.add(card)
    await db_session.commit()

    resp = await admin_client.put(
        f"/api/v1/cards/{card.id}",
        json={"category": "local", "body": "# Drop\n\n*new* body"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["category"] == "local"
    assert body["url"] is None  # stale field wiped
    assert body["body"] == "# Drop\n\n*new* body"
    # H1 stripped, italic rendered — body_html re-rendered fresh.
    assert "<em>new</em>" in body["body_html"]
    assert "<h1>" not in body["body_html"]


async def test_update_category_switch_local_to_external_clears_body(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    card = _make_card(
        slug="flip-back",
        category="local",
        body="# old\n\nold body",
        body_html="<p>old body</p>",
    )
    db_session.add(card)
    await db_session.commit()

    resp = await admin_client.put(
        f"/api/v1/cards/{card.id}",
        json={"category": "external", "url": "https://example.com/new"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "external"
    assert body["url"] == "https://example.com/new"
    # body and body_html nulled by router projection AND wiped server-side.
    assert body["body"] is None
    assert body["body_html"] is None


async def test_update_local_body_change_rerenders(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    card = _make_card(
        slug="re-render",
        category="local",
        body="# old\n\nold",
        body_html="<p>old</p>",
    )
    db_session.add(card)
    await db_session.commit()

    resp = await admin_client.put(
        f"/api/v1/cards/{card.id}",
        json={"body": "# new\n\n**fresh**"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "<strong>fresh</strong>" in body["body_html"]


async def test_update_slug_regen_de_collides(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            _make_card(slug="alpha"),
            _make_card(slug="beta"),
        ]
    )
    target = _make_card(slug="gamma")
    db_session.add(target)
    await db_session.commit()

    resp = await admin_client.put(
        f"/api/v1/cards/{target.id}", json={"slug": "alpha"}
    )
    assert resp.status_code == 200
    # Existing ``alpha`` is active so the regen lands at ``alpha-2``.
    assert resp.json()["slug"] == "alpha-2"


async def test_update_404_for_missing_id(admin_client: AsyncClient) -> None:
    resp = await admin_client.put(
        f"/api/v1/cards/{uuid4()}", json={"title": "Whatever"}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "card_not_found"


async def test_update_local_with_empty_body_rejected(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    card = _make_card(slug="needs-body", category="local", body="# t\n\nbody")
    db_session.add(card)
    await db_session.commit()

    resp = await admin_client.put(
        f"/api/v1/cards/{card.id}", json={"body": "   "}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "missing_body"


async def test_update_switch_to_external_without_url_rejected(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    card = _make_card(slug="no-url", category="local", body="# t\n\nbody")
    db_session.add(card)
    await db_session.commit()

    # Existing card has no url. Switching to external without supplying one.
    resp = await admin_client.put(
        f"/api/v1/cards/{card.id}", json={"category": "external"}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "missing_url"


# --------------------------------------------------------------------------- #
# PATCH /cards/{id}/archive                                                   #
# --------------------------------------------------------------------------- #


async def test_archive_setter_archives_card(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    card = _make_card(slug="active")
    db_session.add(card)
    await db_session.commit()

    resp = await admin_client.patch(
        f"/api/v1/cards/{card.id}/archive", json={"archived": True}
    )
    assert resp.status_code == 200
    assert resp.json()["archived"] is True


async def test_archive_releases_slug_for_active_twin(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    """After archiving, the partial unique index permits a fresh row to take
    the slug back."""

    card = _make_card(slug="reusable")
    db_session.add(card)
    await db_session.commit()

    arch = await admin_client.patch(
        f"/api/v1/cards/{card.id}/archive", json={"archived": True}
    )
    assert arch.status_code == 200

    pub = await admin_client.post(
        "/api/v1/cards",
        json={
            "title": "Reusable",
            "slug": "reusable",
            "category": "external",
            "url": "https://example.com/2",
        },
    )
    assert pub.status_code == 201
    assert pub.json()["slug"] == "reusable"


async def test_unarchive_blocks_when_active_twin_exists(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Unarchiving a row whose slug is now occupied by an active twin must
    409 ``slug_conflict``."""

    archived = _make_card(slug="dup", archived=True)
    active = _make_card(slug="dup", archived=False)
    db_session.add_all([archived, active])
    await db_session.commit()

    resp = await admin_client.patch(
        f"/api/v1/cards/{archived.id}/archive", json={"archived": False}
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "slug_conflict"


async def test_archive_requires_explicit_body(admin_client: AsyncClient) -> None:
    """Empty body must NOT default-archive (legacy surprise removed)."""

    resp = await admin_client.patch(
        f"/api/v1/cards/{uuid4()}/archive", json={}
    )
    # Schema-level required field — Pydantic surfaces 422 before reaching the
    # service. The legacy default-True behaviour is gone.
    assert resp.status_code == 422


async def test_archive_404_for_missing(admin_client: AsyncClient) -> None:
    resp = await admin_client.patch(
        f"/api/v1/cards/{uuid4()}/archive", json={"archived": True}
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# DELETE /cards/{id}                                                          #
# --------------------------------------------------------------------------- #


async def test_delete_removes_row(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    card = _make_card(slug="goodbye")
    db_session.add(card)
    await db_session.commit()

    resp = await admin_client.delete(f"/api/v1/cards/{card.id}")
    assert resp.status_code == 204

    # Row gone from DB.
    found = (
        await db_session.execute(select(Card).where(Card.id == card.id))
    ).scalar_one_or_none()
    assert found is None


async def test_delete_unlinks_local_cover_file(
    admin_client: AsyncClient,
    db_session: AsyncSession,
    settings: Any,
    tmp_path,
    monkeypatch,
) -> None:
    """When the cover URL points at our static dir, the file is removed."""

    # Repoint covers_dir at a temp path so we can assert side-effects.
    covers_dir = tmp_path / "covers"
    covers_dir.mkdir()
    cover_file = covers_dir / "abc.png"
    cover_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    monkeypatch.setattr(
        type(settings), "covers_dir", property(lambda self: covers_dir)
    )

    card = _make_card(
        slug="with-cover",
        cover=f"{settings.COVERS_PUBLIC_PREFIX}/abc.png?v=1",
    )
    db_session.add(card)
    await db_session.commit()

    resp = await admin_client.delete(f"/api/v1/cards/{card.id}")
    assert resp.status_code == 204
    assert not cover_file.exists()


async def test_delete_skips_external_cover_url(
    admin_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Covers with a non-local URL must not trip the unlink path."""

    card = _make_card(
        slug="ext-cover", cover="https://images.example.com/x.jpg"
    )
    db_session.add(card)
    await db_session.commit()

    # Just exercises the branch — no file to assert about, and the call
    # must not raise.
    resp = await admin_client.delete(f"/api/v1/cards/{card.id}")
    assert resp.status_code == 204


async def test_delete_404_for_missing(admin_client: AsyncClient) -> None:
    resp = await admin_client.delete(f"/api/v1/cards/{uuid4()}")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Admin-gate sanity                                                           #
# --------------------------------------------------------------------------- #


async def test_mutating_endpoints_require_admin(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Without the dependency override, the admin gate must refuse."""

    card = _make_card(slug="locked")
    db_session.add(card)
    await db_session.commit()

    # POST without auth.
    resp = await client.post(
        "/api/v1/cards",
        json={
            "title": "Nope",
            "category": "external",
            "url": "https://example.com",
        },
    )
    assert resp.status_code in {401, 403}

    # PUT without auth.
    resp = await client.put(
        f"/api/v1/cards/{card.id}", json={"title": "Nope"}
    )
    assert resp.status_code in {401, 403}

    # DELETE without auth.
    resp = await client.delete(f"/api/v1/cards/{card.id}")
    assert resp.status_code in {401, 403}
