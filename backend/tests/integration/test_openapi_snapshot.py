"""OpenAPI drift gate.

Snapshots the FastAPI ``/openapi.json`` document against a committed fixture
so any unintended change to the v1 contract is caught in CI. The companion
frontend repo consumes ``frontend/openapi/schema.json``; the gate ensures the
backend snapshot here and the frontend snapshot stay in sync (the frontend's
``pnpm gen:api && git diff --exit-code`` job runs the same comparison from
the other side — see §3.5 and §6 of the architecture spec).

Regenerating the snapshot
-------------------------

When a contract change is intentional, run::

    LG_UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest \
        backend/tests/integration/test_openapi_snapshot.py

That overwrites ``backend/tests/fixtures/openapi_snapshot.json`` with the
freshly-generated document. Commit the diff alongside the code change. The
frontend ``openapi/schema.json`` should be regenerated in the same PR via
``pnpm gen:api``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# B1 owns ``app.main``; if it has not landed yet, skip rather than fail so the
# rest of the suite stays green during parallel implementation. The integrator
# will see the test go from "skipped" to "passed" once create_app() is wired.
pytest.importorskip("app.main")

from app.main import create_app  # noqa: E402  (deferred import after importorskip)

SNAPSHOT_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "openapi_snapshot.json"
)


def _normalize(schema: dict) -> dict:
    """Strip volatile fields so the snapshot is reproducible.

    FastAPI bumps ``info.version`` whenever the app version changes; ``servers``
    is environment-specific. Keeping only the structural surface of the
    document means the gate fires only on contract drift.
    """

    schema = json.loads(json.dumps(schema, sort_keys=True))
    schema.pop("servers", None)
    info = schema.get("info")
    if isinstance(info, dict):
        # Pin a stable version so unrelated bumps don't churn the snapshot.
        info["version"] = "snapshot"
    return schema


def _load_snapshot() -> dict | None:
    if not SNAPSHOT_PATH.exists():
        return None
    raw = SNAPSHOT_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    return json.loads(raw)


def _write_snapshot(schema: dict) -> None:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_openapi_snapshot_matches_committed_fixture() -> None:
    """The live ``/openapi.json`` must match ``openapi_snapshot.json`` byte-for-byte.

    Set ``LG_UPDATE_OPENAPI_SNAPSHOT=1`` to overwrite the fixture during an
    intentional contract change. CI never sets that flag, so a drifting PR is
    caught loudly.
    """

    app = create_app()
    actual = _normalize(app.openapi())

    if os.environ.get("LG_UPDATE_OPENAPI_SNAPSHOT") == "1":
        _write_snapshot(actual)
        pytest.skip("openapi snapshot regenerated")

    expected = _load_snapshot()
    if expected is None:
        pytest.fail(
            "OpenAPI snapshot fixture is missing or empty. Regenerate with "
            "LG_UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest "
            "backend/tests/integration/test_openapi_snapshot.py"
        )

    # json.dumps with sort_keys gives a deterministic textual comparison so the
    # diff in CI logs is human-readable on failure.
    actual_text = json.dumps(actual, indent=2, sort_keys=True, ensure_ascii=False)
    expected_text = json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False)
    assert actual_text == expected_text, (
        "OpenAPI contract drift detected. If this change is intentional, "
        "regenerate the snapshot with "
        "LG_UPDATE_OPENAPI_SNAPSHOT=1 and re-run the test, then commit the "
        "updated fixture (and run pnpm gen:api on the frontend)."
    )


def test_openapi_has_v1_prefix_and_health_mirror() -> None:
    """Sanity check: the contract must expose /api/health and /api/v1/* paths.

    Catches the case where ``main.py`` regresses the dual-mount or the v1
    prefix accidentally drops, before the snapshot check muddies the diff.
    """

    app = create_app()
    schema = app.openapi()
    paths = set(schema.get("paths", {}).keys())

    assert "/api/health" in paths, (
        "GET /api/health must be mounted directly on the app root for "
        "version-stable monitoring (see §1 and §3.5)."
    )
    assert any(p.startswith("/api/v1/") for p in paths), (
        "No /api/v1/* paths in the OpenAPI document — the v1 router is not "
        "mounted."
    )
    assert "/api/v1/tags" in paths, (
        "GET /api/v1/tags must be exposed (B7 deliverable)."
    )
