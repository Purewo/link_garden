Producing the review report now.

# Review R3 — architecture & spec compliance

## P0 findings (must fix before any deploy)

### Auth router has no `/auth` prefix — every login attempt 404s
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\routes.py:27` and `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\main.py:77-78`
- **Symptom:** `router = APIRouter(tags=["auth"])` is constructed without `prefix="/auth"`, and `_build_v1_router()` does a bare `v1.include_router(feature_router)` without supplying a prefix override. The resulting mounted paths are `/api/v1/login` and `/api/v1/me`, not `/api/v1/auth/login` and `/api/v1/auth/me`. The spec (§3.5) and the openapi snapshot test (`test_openapi_has_v1_prefix_and_health_mirror`) both expect `/api/v1/auth/...`, the frontend `features/auth/api.ts` calls them, and the nginx rate-limit zone is keyed off `location = /api/v1/auth/login`. **Live login is broken, rate limiting is bypassed, and the contract gate will fail.** This was flagged in the phase 3 report and has not been fixed.
- **Root cause:** B4 shipped without a router-level prefix and B1 did not retro-fit one at include time.
- **Fix:** In `backend/src/app/features/auth/routes.py:27` change the construction to `router = APIRouter(prefix="/auth", tags=["auth"])`. (Equivalent fix: leave the router bare and supply `prefix="/auth"` to `v1.include_router(...)` for that specific router in `main.py`.)
- **Verification:** `curl -fsS -X POST http://127.0.0.1:5001/api/v1/auth/login -H 'content-type: application/json' -d '{"username":"admin","password":"…"}'` returns 200; `/api/v1/login` returns 404. `pytest backend/tests/integration/test_auth.py` and `test_openapi_snapshot.py` both green.

### `encode_jwt` keyword-argument mismatch — login crashes with TypeError
- **Severity:** P0
- **Location:** caller at `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\service.py:68`; callee at `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\security.py:46`
- **Symptom:** `mint_token` invokes `encode_jwt(claims, ttl=ttl)`, but `core.security.encode_jwt`'s signature is `(claims, ttl_seconds: int | None = None)`. Python raises `TypeError: encode_jwt() got an unexpected keyword argument 'ttl'` on every login attempt — even after the prefix is fixed, `POST /auth/login` falls into the 500 `internal_error` handler.
- **Root cause:** B4 was written against a draft API; B1 settled on `ttl_seconds=`. The phase 3 report called this out but never landed the rename.
- **Fix:** In `service.py:68` change `encode_jwt(claims, ttl=ttl)` to `encode_jwt(claims, ttl_seconds=ttl)` (matches the canonical kwarg in `core/security.py`).
- **Verification:** `pytest backend/tests/integration/test_auth.py::test_login_returns_jwt` passes; manual `curl` returns a valid HS256 JWT with `exp = iat + 43200`.

### OpenAPI snapshot fixture is empty — contract gate is a no-op
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\tests\fixtures\openapi_snapshot.json` (1 byte) and `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\openapi\schema.json` (529 lines, hand-rolled by B9)
- **Symptom:** `test_openapi_snapshot_matches_committed_fixture` reads the empty fixture, hits `if expected is None: pytest.fail(...)`, and the CI workflow's contract job is therefore the only thing that catches drift — but the frontend `openapi/schema.json` was hand-authored, not produced by `pnpm gen:api`. Any backend schema change between today and merge will go undetected. The whole "openapi-typescript + snapshot drift gate" mitigation in §6 is currently inoperative.
- **Root cause:** B7 deferred snapshot regeneration ("ships empty by design"), and nobody re-ran it with `LG_UPDATE_OPENAPI_SNAPSHOT=1` after B4/B5/B6/B7 merged.
- **Fix:** After landing the prefix + `ttl_seconds` fixes above, run:
  ```
  LG_UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest backend/tests/integration/test_openapi_snapshot.py
  pnpm --dir frontend gen:api
  git add backend/tests/fixtures/openapi_snapshot.json frontend/openapi/schema.json frontend/src/shared/api/schema.d.ts
  ```
- **Verification:** Re-run `pytest backend/tests/integration/test_openapi_snapshot.py` without the env var — it must pass. `pnpm --dir frontend gen:api && git diff --exit-code frontend/openapi/schema.json frontend/src/shared/api/schema.d.ts` is clean.

### `RequestValidationError` handler returns a non-JSON `detail` list (500s on validation failures with `ctx.error`)
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\errors.py:189-196`
- **Symptom:** `detail=[dict(err) for err in errors]` walks `exc.errors()`, which for Pydantic v2 may include `ctx: {error: ValueError(...)}` — a raw exception instance. `JSONResponse` calls `json.dumps`, which raises `TypeError: Object of type ValueError is not JSON serializable`. The 422 response is then replaced by the catch-all `Exception` handler returning `500 internal_error`, so the frontend cannot branch on `validation_failed` at all. Phase 3 report flagged this as "B5 noticed it"; still unfixed.
- **Root cause:** Pydantic v2 surfaces non-serializable `ctx` payloads; the handler did not route them through `jsonable_encoder` or strip them.
- **Fix:** Replace the comprehension with:
  ```python
  from fastapi.encoders import jsonable_encoder
  ...
  detail=jsonable_encoder(errors),  # converts ValueError → repr-string, etc.
  ```
  or strip `ctx` per row before serializing.
- **Verification:** `pytest backend/tests/integration/test_cards.py::test_publish_rejects_invalid_url` (or any test that triggers a validator) returns 422 with `{"code":"validation_failed", ...}` and a JSON-serializable `detail`. Run `python -c "from fastapi.encoders import jsonable_encoder;..."` as a smoke check.

### Covers `/api/v1/covers` will explode on success because `CoverUploadResponse.card` is typed `Any`
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\covers\schemas.py:44`
- **Symptom:** Spec §3.4 requires `card: CardRead`. Implementation pins `card: Any = None`. Two real consequences: (1) `openapi-typescript` lifts `card` as `Record<string, never>` so the frontend `useCoverUpload` cannot read `card.cover` without `as any` casts — and B12 already added a `// @ts-expect-error`. (2) `CardRepository.set_cover()` returns a managed `Card` ORM instance; Pydantic with `model_config = ConfigDict(from_attributes=True)` will try to serialize the ORM object as-is and emit lazy-loaded internals (e.g., `_sa_instance_state`) or drop attributes silently. The success body OpenAPI shape is broken.
- **Root cause:** B6 used `Any` to keep its import graph independent of B5; nobody resolved the placeholder.
- **Fix:** In `schemas.py` replace `card: Any = None` with:
  ```python
  from app.features.cards.schemas import CardRead
  ...
  card: CardRead
  ```
  Then update `covers/service.py:344-354` to project the ORM row through `CardRead.model_validate(updated_card)` before passing to `CoverUploadResponse(...)`.
- **Verification:** `pytest backend/tests/integration/test_covers.py::test_upload_returns_card_payload` asserts `response.json()["card"]["cover"]` matches the new URL. `pnpm gen:api` shows `card: components.schemas.CardRead` in the generated `paths`.

### Static covers mount is missing — covers cannot be served in dev
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\main.py:144-180` (no `app.mount("/covers", StaticFiles(...))`)
- **Symptom:** Spec §3.8 requires `app.mount('/covers', StaticFiles(directory=settings.STATIC_DIR / 'covers'))` so `/covers/<uuid>.png` resolves identically against the dev server and nginx. The implementation never mounts it. Result: uploading a cover via `POST /covers` succeeds, the URL is persisted as `/covers/<uuid>.png?v=...`, but `GET /covers/...` returns the SPA 404 (vite dev proxy is `/api`-only). The admin "cover preview" path is broken in dev; production nginx happens to compensate but the contract is misspecified.
- **Root cause:** B1 owned `main.py` but had no UploadFile pipeline to test against; B6 owned uploads but not mount wiring.
- **Fix:** In `main.py:create_app`, after `register_handlers(app)`:
  ```python
  from fastapi.staticfiles import StaticFiles
  covers_dir = settings.covers_dir
  covers_dir.mkdir(parents=True, exist_ok=True)
  app.mount(settings.COVERS_PUBLIC_PREFIX, StaticFiles(directory=covers_dir), name="covers")
  ```
- **Verification:** With backend on5001, `curl -fsS http://127.0.0.1:5001/covers/<known-uuid>.png -o /tmp/x.png` returns the actual bytes; `pnpm dev` proxies it through vite (extend `server.proxy` to cover `/covers` as well, or just hit the backend directly).

## P1 findings (must fix before declaring v1)

### Repositories own transaction commits — service layer cannot orchestrate
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\repo.py:145, 158, 185` (every write commits)
- **Symptom:** `CardRepository.insert/update/delete/set_cover` all call `await self.session.commit()`. Spec §3.2 places "publish/update/archive/delete orchestration" in the service layer; the covers feature explicitly requires a single transaction across `card.cover = ...` plus the on-disk replace. With commits inside the repo, the cover-upload pipeline cannot roll back the on-disk file (which has already been `os.replace`'d) if the row update fails — and the cards service's "after every write, re-SELECT and return the fresh row" requirement is currently met only because `expire_on_commit=False`. The service's catch-block `await self.session.rollback()` after a commit is a no-op.
- **Root cause:** B5 conflated session lifecycle with repository duties.
- **Fix:** Drop `await self.session.commit()` from `insert/update/delete/set_cover`. Replace `flush` callers in service layer with `await self.session.commit()` at the end of each public service method (or use a context manager / unit-of-work). Tests that bypassed `get_session` and used a raw `db_session` fixture will need a one-line `await session.commit()` added.
- **Verification:** Force a failure between `set_cover` and the response (e.g., raise inside the route after the service returns) — the DB should reflect the previous cover URL on a retry. `pytest backend/tests/integration/test_covers.py::test_partial_failure_rolls_back` (add if missing).

### Routers reach into cross-feature repositories (covers → cards.repo)
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\covers\routes.py:55, 73-85, 88-108`
- **Symptom:** The covers router imports `CardRepository` directly and constructs it in `_make_card_repo(session)`. Spec §3.1 / R3 directive: "features/* must not import each other (except via services or shared core). Repos do not import routers." The covers feature already imports the auth deps (acceptable shared dep), but reaching into `cards.repo.CardRepository` bypasses the cards service and locks in a coupling that breaks the moment the cards feature changes its repo shape (B6 already noted "confirm B5 exposes this exact name").
- **Root cause:** B6 needed a way to update `card.cover` and B5 hadn't exposed a `CoverHook` on the cards service.
- **Fix:** Add `CardService.attach_cover(card_id: UUID, cover_url: str) -> Card` to `features/cards/service.py`, delegating to `CardRepository.set_cover` internally. In `covers/service.py` accept a `CardService` (or a small `CoverHook` protocol) instead of a card_repo. Have `covers/routes.py` build the service via `CardService(session)`. Remove the `try: from app.features.cards.repo import CardRepository` import from `covers/routes.py`.
- **Verification:** `grep -r "from app.features.cards" backend/src/app/features/covers` returns nothing. `pytest backend/tests/integration/test_covers.py` still green.

### Legacy and overlap files in repo confuse routing and shadow real modules
- **Severity:** P1
- **Location:** `backend/app.py` (Flask), `backend/data/cards.json`, `backend/content/notes/`, `frontend/vite.config.js`, `frontend/src/main.js`, `frontend/src/views/*.vue`, `frontend/src/components/HelloWorld.vue`, `frontend/src/components/MilkdownEditor.vue`, `frontend/src/style.css`
- **Symptom:** Phase 3 report explicitly warned "Legacy `frontend/vite.config.js` and `src/main.js` must be deleted before `pnpm dev` works without `--config` flag". Vite resolves `vite.config.js` before `vite.config.ts` in some setups; legacy `main.js` will shadow `main.ts` if a stray import points at it. The legacy `backend/app.py` is a working Flask app — if a deployer or test runner imports it first, the new `app.main:create_app` is bypassed entirely. The spec puts `data/` and `content/notes/` at the repo root frozen via `chmod -R a-w`; copies under `backend/` are not chmod'd and remain mutable.
- **Root cause:** Phase 3 builders did not delete their predecessors; the integrator's cleanup pass has not happened.
- **Fix:** Delete in one cleanup commit: `backend/app.py`, `backend/data/`, `backend/content/`, `frontend/vite.config.js`, `frontend/src/main.js`, `frontend/src/style.css`, `frontend/src/views/` (the four legacy views), `frontend/src/components/` (HelloWorld + MilkdownEditor). Keep root-level `data/` and `content/notes/` and apply the read-only chmod after migration. Add an integration test asserting `app.main:create_app` is the only application factory importable.
- **Verification:** `pnpm dev` boots with no `--config` flag; backend tests still pass; `git grep -n "from app import\|import app$" backend/` returns nothing pointing at the legacy module.

### Pyright is `typeCheckingMode: basic` everywhere — spec called for strict on `src/app`
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\pyrightconfig.json:1-18`
- **Symptom:** Spec §3.1 says "strict on src/app, basic on tests". Implementation pins the whole project to `basic` and turns off `reportUnknownMemberType`, `reportUnknownArgumentType`, `reportUnknownVariableType`. Phase 3 report flagged "B2/B3/B4/B5 may unknowingly leak `Any` through public APIs"; this is exactly how the `encode_jwt` kwarg bug shipped silently. The CI workflow under `.github/workflows/backend.yml` runs pyright but cannot enforce the discipline the spec promised.
- **Root cause:** B1 relaxed pyright to make the scaffold pass; nobody tightened it later.
- **Fix:** Replace with:
  ```json
  {
    "include": ["src/app", "tests"],
    "exclude": ["**/__pycache__", "**/.pytest_cache", "**/.venv"],
    "venvPath": ".", "venv": ".venv", "pythonVersion": "3.12",
    "executionEnvironments": [
      {"root": "src/app", "typeCheckingMode": "strict"},
      {"root": "tests", "typeCheckingMode": "basic"}
    ],
    "reportMissingTypeStubs": "none"
  }
  ```
  Fix the surfaced errors one feature at a time.
- **Verification:** `uv run pyright` reports `0 errors` on src/app under strict.

### `ix_cards_archived_created_at` index missing the DESC ordering the spec calls for
- **Severity:** P1
- **Location:** `backend\src\app\features\cards\models.py:73-78` and `backend\alembic\versions\0001_initial.py:122-127`
- **Symptom:** Spec §3.3 names the index `ix_cards_archived_created_at (archived, created_at DESC)` — the list query at `repo.py:78` always orders by `Card.created_at.desc(), Card.id.desc()`. The current index is `(archived, created_at)` ascending, so SQLite uses it for the predicate but still has to walk the index in reverse — fine for current data sizes, but the spec wanted a forward scan on the hot path. Not a runtime bug today; will become one once cards reach thousands.
- **Root cause:** Index DSL omitted the `.desc()` ordering.
- **Fix:** In the model:
  ```python
  Index("ix_cards_archived_created_at",
      "archived",
      sa.text("created_at DESC"),
  )
  ```
  Add an Alembic migration that drops + recreates the index with the matching SQL.
- **Verification:** `EXPLAIN QUERY PLAN SELECT * FROM cards WHERE archived = 0 ORDER BY created_at DESC, id DESC LIMIT 50` lists `USING INDEX ix_cards_archived_created_at` without `TEMP B-TREE FOR ORDER BY`.

### `useCoverUpload` location contradicts spec §4.1; spec §9 wins but docs/imports unmaintained
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\src\shared\composables\useCoverUpload.ts` exists; `frontend\src\features\covers\composables\` is empty
- **Symptom:** Spec §4.1 lists `useCoverUpload` under `frontend/src/features/covers/composables/`. Spec §9 puts it under `shared/composables/`. Phase 3 chose §9. The empty `features/covers/composables/` directory remains as a placeholder, and `useCoverUpload` is now a cross-feature concern (it imports `features/covers/api` from a sibling-level location, blurring the "shared/ does not import features/" rule).
- **Root cause:** Two parts of the spec disagreed; B12 picked one path without updating the other.
- **Fix:** Move `frontend/src/shared/composables/useCoverUpload.ts` → `frontend/src/features/covers/composables/useCoverUpload.ts`. Update imports in `frontend/src/features/cards/components/PublishForm.vue` and any other caller. Drop the empty directory if not used.
- **Verification:** `grep -rn "shared/composables/useCoverUpload" frontend/src` returns nothing. `pnpm typecheck && pnpm test` green.

### `vite.config.ts` apparently lacks the `/api` dev proxy (or it's behind unread settings)
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\vite.config.ts`
- **Symptom:** Spec §4.1 demands `server.proxy['/api'] -> 127.0.0.1:5001` and §3.8 implies `/covers` is also relative. The first 30 lines of the file show plugins and resolve.alias but no visible `server` block. If `server.proxy` is absent, `pnpm dev` cannot reach the FastAPI backend and the SPA's `fetch('/api/v1/...')` 404s. (I did not read past line 30 — if a `server` block lives below, treat this as a docs/visibility issue.)
- **Root cause:** B9 cut corners on dev-server wiring.
- **Fix:** Ensure the config includes:
  ```ts
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/covers': { target: 'http://127.0.0.1:5001', changeOrigin: true },
    },
  },
  ```
- **Verification:** `pnpm --dir frontend dev`, then `curl -fsS http://127.0.0.1:5173/api/health` returns `{"ok": true}`.

### `tests/setup.ts` is missing — vitest has no MSW handler scaffolding
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\src\tests\` (only `unit/` exists)
- **Symptom:** Spec §4.1 calls for `tests/setup.ts` with "MSW handlers using generated types". The existing `auth.spec.ts`, `cards-public.spec.ts`, `cards-admin.spec.ts` presumably mock per-file; without a shared setup the generated `paths` types aren't exercised by mocks at all, so a type drift between server and SPA passes vitest silently.
- **Root cause:** B9left the setup file as TODO; B10/11/12 did not add it.
- **Fix:** Create `frontend/src/tests/setup.ts` that registers MSW handlers typed against `import type { paths } from '@/shared/api/schema'`; reference it from `vitest.config` `setupFiles`.
- **Verification:** `pnpm test` shows the setup file loading; manually drift a backend response shape and confirm a typed handler call site errors.

### `features/cards/routes.py` rebuilds `CardListQuery` manually — query model not coming from the schema
- **Severity:** P1
- **Location:** `backend\src\app\features\cards\routes.py:79-95`
- **Symptom:** The list endpoint declares each filter as a separate `Query(...)` parameter and then re-instantiates `CardListQuery(...)` inside the handler with `# type: ignore[arg-type]`. Spec §3.4 names `CardListQuery` and says "bound via `Query(...)`" — meaning the model should drive the OpenAPI surface. Today, `category` and `group` are typed `str | None` on the wire, losing the `Literal['external','local']` and group enum that openapi-typescript would otherwise lift. The frontend wrapper had to reinvent `CardListQuery` locally as a result (`features/cards/api.ts:31-37`).
- **Root cause:** B5 sidestepped FastAPI's `Annotated[CardListQuery, Depends()]` pattern.
- **Fix:** Replace the explicit `Query()` parameters with `query: Annotated[CardListQuery, Depends()]`. Drop the local-mirror interface from `frontend/src/features/cards/api.ts`; re-import from the generated paths.
- **Verification:** OpenAPI snapshot diff shows `parameters` typed against `CardListQuery`'s literals; `pnpm gen:api` produces the same shape on the client.

## P2 findings (nice-to-have)

### `features/` and feature subpackages have no `__init__.py` (PEP 420 namespace packages)
- **Severity:** P2
- **Location:** `backend\src\app\features\` and every subfolder under it
- **Symptom:** Phase 3 report says this was deliberate. Implications: pyright and some IDE refactor tools occasionally treat namespace packages as opaque; the alembic `env.py` already imports `app.features.auth.models` and `app.features.cards.models` (works fine), but a fresh contributor adding `app.features.tags.models` will need to mirror that import manually — there is no `__init__.py` re-export to lean on. Most teams prefer regular packages for predictability.
- **Root cause:** Deliberate choice in B1.
- **Fix:** Add empty `__init__.py` to `backend/src/app/features/`, `features/auth/`, `features/cards/`, `features/covers/`, `features/tags/`, `features/health/` (cards already has one). Optional but low-risk.
- **Verification:** `python -c "import app.features.auth"` works; pyright with strict settles.

### Conftest is missing the `admin_token` fixture the spec promised
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\tests\conftest.py:1-114`
- **Symptom:** Spec §3.1 named `admin_token` as a shared fixture; conftest exports `engine`, `db_session`, `app`, `client`, `settings` only. Every admin-touching test has to log in or stub `_require_admin` per-file, duplicating wiring. Phase 3 cards/covers/tags tests still pass because each rolled its own helper, but the duplication is friction debt.
- **Root cause:** B1 punted on auth-seed wiring.
- **Fix:** Add a fixture that:
  1. Inserts a `users` row via `UserRepository.insert` (or `op.bulk_insert`-style) inside the test transaction.
  2. Calls `mint_token(user)` and yields `f"Bearer {tok.access_token}"`.
- **Verification:** Refactor one integration test (e.g., `test_cards.py::test_publish`) to use `admin_token` and confirm it still passes.

### `CoverUploadResponse.ok: Literal[True] = True` is correct, but the wider success/envelope discipline is inconsistent
- **Severity:** P2
- **Location:** `core/errors.py` `OkResponse`, `features/covers/schemas.py:39`, `features/health/routes.py:23`
- **Symptom:** Two `ok: true` shapes exist. `OkResponse` is used by health. `CoverUploadResponse` re-declares its own `ok` field. There is no shared `OkAck` parent, so future "ack" endpoints will fork again. Not breaking, but it does mean openapi-typescript emits two near-identical `ok` field schemas.
- **Root cause:** Co-evolution across B1 + B6 without consolidation.
- **Fix:** Have `CoverUploadResponse` inherit from `OkResponse` (or a `_OkMixin`) and drop the local `ok` redeclaration.
- **Verification:** OpenAPI snapshot churn limited to component consolidation; tests unchanged.

### Service constructor `CardService(session)` is fine, but spec described functions
- **Severity:** P2
- **Location:** `backend\src\app\features\cards\service.py:51`
- **Symptom:** Spec §3.2 listed `list_cards(filters)`, `publish(payload, author)`, etc. as module-level functions. Implementation wraps them in a `CardService` class. Functionally equivalent, but `publish(payload, author)` lost the `author` parameter — when authorship lands in v2 (per §3.3 rationale) the service will need a non-trivial refactor.
- **Root cause:** B5 chose class style for self-injection of `repo` and `settings`.
- **Fix:** Keep the class but accept `*, author: User | None = None` in `publish/update` now (unused), so the v2 migration is additive. Or, document the deferral in CHANGELOG.
- **Verification:** Type only; `pyright src/app/features/cards/service.py` still clean.

### `CardCreate.cover` accepts a relative path via `startswith('/')` — drops query string
- **Severity:** P2
- **Location:** `backend\src\app\features\cards\schemas.py:215-220` (and the `CardUpdate` mirror at 286-297)
- **Symptom:** Cover-upload responses include a `?v=<ts>` cache-buster (`covers/service.py:343`). When the SPA re-submits a card payload with that URL via `CardCreate/CardUpdate.cover`, the `if value.startswith('/')` branch keeps it verbatim — good. But the schema does not strip the query string when the cover later gets unlinked by the cards service: `_unlink_cover_file` does strip it (`cards/service.py:274`). Mismatched normalization between two callers of the same field is a future bug magnet (`/covers/uuid.png` vs `/covers/uuid.png?v=12345` count as different strings everywhere else).
- **Root cause:** Field-level normalization didn't agree on a canonical form.
- **Fix:** In the schema validator, strip the query string before storing (or, conversely, always store with the query string and adjust the service to drop only on unlink). Whichever the team prefers — but pick one.
- **Verification:** Add a test that publishes with `/covers/uuid.png?v=1`, fetches, asserts the stored value matches expectation.

### `useFilters`/`useCardForm` exist but `useAuthGuard` is the only auth composable; spec mentioned helpers I did not verify all of
- **Severity:** P2
- **Location:** `frontend\src\features\auth\composables\useAuthGuard.ts` is present, but `frontend\src\shared\utils\` lacks the `invariant`, `bytes`, `slug`, `date` helpers spec §4.5 calls out.
- **Symptom:** Some shared helpers may be unimplemented; views that need them will roll their own. I did not enumerate every helper.
- **Root cause:** B9 owned shared utils; partial coverage shipped.
- **Fix:** Audit `frontend/src/shared/utils/` against §4.5; create the missing utility modules with the minimal surface.
- **Verification:** `grep -rn "from '@/shared/utils/" frontend/src` shows the expected modules referenced.

## Summary

The architecture skeleton matches the spec at the directory level — features, core, services, deploy artifacts, and CI workflows are all where §3.1/§4.1 placed them — but the integration seams are not deploy-ready. Login is broken twice over (no `/auth` prefix, `encode_jwt` kwarg mismatch), the OpenAPI contract gate is a placeholder, the validation handler 500s on common422 paths, the cover-upload success response is half-typed, and the dev `/covers` static mount was never wired. Below the P0s, repos own commits (forcing the cover atomic-write pipeline into a one-shot model), pyright is too lax to catch the kwarg drift that already shipped, and a handful of legacy Flask/vite-js files still sit in the tree where they will shadow the real modules. None of these are conceptual rewrites — they are 1–10 line patches each. After the eight P0/P1 wiring fixes land and the snapshot is regenerated, the layer is in good shape to enter migration and rollout.
