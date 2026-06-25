Now I have a comprehensive picture. Let me write the review.

# Review R1 — correctness & integration

The repo merges 14 builder units onto a Python 3.12+ FastAPI/SQLAlchemy2 backend and a Vite7 / Vue 3.5 frontend. Iran `pytest` against the merged tree, walked every backend route, every frontend api wrapper, every migration, the test conftest, the vite config, and the deployment artifacts. Below are the bugs I found,ranked by what blocks deploy.

Pytest result against the merged tree: **`10 failed, 186 passed, 5 errors`** (`uv run pytest` equivalent via `.venv/Scripts/py.test.exe`). The integration tree never gets to green.

## P0 findings (must fix before any deploy)

### Auth router has no `/auth` prefix — every `/api/v1/auth/*` URL 404s
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\routes.py:27` and `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\main.py:38-79`
- **Symptom:** `POST /api/v1/auth/login` and `GET /api/v1/auth/me` both return 404. Pytest log:
  `http_exception code=http_404 method=POST path=/api/v1/auth/login`. Endpoints currently land at `/api/v1/login` and `/api/v1/me`. Spec §3.5 mandates `/api/v1/auth/login` and `/api/v1/auth/me`. The frontend `features/auth/api.ts` calls `'/auth/login'` and `'/auth/me'` — every login attempt 404s.
- **Root cause:** `auth/routes.py` declares `router = APIRouter(tags=["auth"])` with no `prefix="/auth"`, and `main._build_v1_router()` mounts feature routers via `v1.include_router(feature_router)` without injecting a prefix.
- **Fix:** in `auth/routes.py`:
  ```python
  router = APIRouter(prefix="/auth", tags=["auth"])
  ```
  (Or alternatively register `_FEATURE_ROUTERS` as `(module, attr, prefix)` tuples and pass `prefix` to `include_router` — but the per-router prefix matches what every other feature already does: cards, covers, tags all carry their own prefix.)
- **Verification:** `pytest tests/integration/test_auth.py` — currently 5ERRORs + 7 FAILs all collapse to "404"; with the prefix in place they should resolve to the auth-specific assertions (subject to the other P0 fixes below).

### `mint_token` calls `encode_jwt(claims, ttl=...)` but the helper is `ttl_seconds=`
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\service.py:68`, against `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\security.py:46`
- **Symptom:** Any successful login throws `TypeError: encode_jwt() got an unexpected keyword argument 'ttl'` (reproduced by `tests/integration/test_auth.py::test_me_with_unknown_user_is_401`). Login is unreachable until fixed.
- **Root cause:** B4 was written against an earlier B1 signature that used `ttl=`; the B1 deliverable shipped `ttl_seconds=`.
- **Fix:** in `auth/service.py:68`:
  ```python
  token = encode_jwt(claims, ttl_seconds=ttl)
  ```
- **Verification:** rerun `pytest tests/integration/test_auth.py::test_login_succeeds_with_valid_credentials` — it must hit `200` and decode the token cleanly.

### `_validation_exception_handler` ships non-JSON `ctx` payloads in422 envelopes
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\errors.py:177-196`
- **Symptom:** When Pydantic v2 validators raise `ValueError`, `exc.errors()` returns rows like `{"type":"value_error", "ctx":{"error":ValueError(...)}}`. The handler does `detail=[dict(err) for err in errors]` and hands the result to `JSONResponse`, which calls `json.dumps` on a `ValueError` instance and raises `TypeError: Object of type ValueError is not JSON serializable`. The catch-all 500 handler then masks the real validation message. This breaks every4xx that surfaces a non-trivial validator (URL/body coupling, tag too long, slug shape, etc.).
- **Root cause:** `dict(err)` is a shallow copy that preserves the embedded exception object; `JSONResponse` does not invoke `jsonable_encoder` automatically.
- **Fix:**
  ```python
  from fastapi.encoders import jsonable_encoder
  ...
  detail=jsonable_encoder(errors),
  ```
  Or strip `ctx` before serialising: `detail=[{k: v for k, v in err.items() if k != "ctx"} for err in errors]`.
- **Verification:** add a test that posts a body that hits `_enforce_category_coupling` (e.g., `category='external'` without `url`) — current behaviour returns 500 once the response is rendered; after the fix it should return `422{code:'validation_failed'}` with a structured `detail` array.

### `conftest.py` exposes `db_session`, every test uses `session` — fixture not found
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\tests\conftest.py:79` vs `tests/integration/test_auth.py:63,80,...` and any other suite that declares `session: AsyncSession`
- **Symptom:** All five `ERROR at setup of …` rows in the auth suite are `fixture 'session' not found. available fixtures: …, db_session, …`. `tests/integration/test_tags.py` redefines its own local `session` fixture so it dodges the issue, but every other suite that wants the conftest session is broken on the first call.
- **Root cause:** Phase 3 rolled the conftest under the wrong fixture name. The auth suite literally documents "the conftest provides `session`" in its module docstring.
- **Fix:** rename the fixture in conftest to `session` (the spec also implies the canonical name — `tests/integration/test_auth.py` and `tests/integration/test_cards.py` both expect it). Either:```python
  @pytest_asyncio.fixture()
  async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
      ...
  ```
  Or add `db_session = session` alias and migrate. A second alias `admin_user` / `admin_token` is also missing per the docstring; either add them to conftest or update each test to seed locally.
- **Verification:** `pytest tests/integration/` should drop the 5 ERRORs and the 7 fixture-name FAILs.

### `tags/repo.py` orders by random UUID — first-occurrence dedup is non-deterministic
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\tags\repo.py:40`
- **Symptom:** `pytest tests/integration/test_tags.py::test_list_distinct_tags_distinct_and_sorted` fails:
  `assert tags == ['FastAPI', 'python', 'sql', 'Vue']` got `['FastAPI', 'python', 'sql', 'vue']`. The repo is documented to preserve "first-seen casing" but it orders by `Card.id`, which for the GUID type is a random `uuid4`. Two consecutive runs can return different casings, depending on which card hashes lower. End-user impact: a tag can flip from `Vue` to `vue` between deploys.
- **Root cause:** `stmt = select(Card.tags).order_by(Card.id)` — the spec wants insertion order (`created_at, id`) so tags from the chronologically-first card win.
- **Fix:**
  ```python
  stmt = select(Card.tags).order_by(Card.created_at.asc(), Card.id.asc())
  ```
- **Verification:** the failing test should pass; the second tags test (`test_list_distinct_tags_include_archived`) only fails as collateral when run after the first one (engine teardown), so this fix should unblock both.

### OpenAPI snapshot fixture is empty — every contract drift is a test failure
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\tests\fixtures\openapi_snapshot.json` (1 byte) and `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\openapi\schema.json` (placeholder)
- **Symptom:** `tests/integration/test_openapi_snapshot.py::test_openapi_snapshot_matches_committed_fixture` fails with `OpenAPI snapshot fixture is missing or empty. Regenerate with LG_UPDATE_OPENAPI_SNAPSHOT=1`. The contract gate is non-functional. Since the auth router is also wrong (P0 #1), regenerating now would bake in the broken contract.
- **Root cause:** B7 shipped the file empty by design but no integrator ran the regen step.
- **Fix:** after the auth-prefix and validation-handler fixes land, run `LG_UPDATE_OPENAPI_SNAPSHOT=1 .venv/Scripts/py.test.exe tests/integration/test_openapi_snapshot.py` and commit the resulting JSON. Then run `pnpm gen:api` in `frontend/` to refresh `frontend/openapi/schema.json` and `frontend/src/shared/api/schema.d.ts`.
- **Verification:** subsequent runs of the snapshot test pass; the contract test in `test_openapi_has_v1_prefix_and_health_mirror` already asserts `/api/health` and `/api/v1/*` exist.

### Legacy frontend files still on disk — will resolve at runtime and shadow the new SPA
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\vite.config.js`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\src\main.js`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\src\views\{HomeView,DetailView,AdminView,AdminPublishView}.vue`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\src\components\{HelloWorld,MilkdownEditor}.vue`
- **Symptom:** Both `vite.config.js` and `vite.config.ts` exist. Vite picks one deterministically, but a developer running `pnpm dev` on a clean clone may load the legacy config which has no proxy — `/api/v1/*` calls 404 against the SPA dev server. Likewise `src/main.js` and `src/main.ts` co-exist; Vite's resolver prefers `main.ts` because of `index.html` referencing `/src/main.ts`, but the legacy `main.js` still imports legacy `App.vue` paths and will compile if any tooling probes it. The legacy `views/` and `components/` directories still ship `MilkdownEditor.vue` (uses milkdown, not in deps) — `pnpm build` will pull these into the bundle if anything reaches them transitively.
- **Root cause:** B14 delivered "ignored in lint" but never `git rm`'d the files. Phase 3 report explicitly flagged this as the integrator's responsibility.
- **Fix:** delete:
  ```
  frontend/vite.config.js
  frontend/src/main.js
  frontend/src/style.css   (replaced by assets/styles/*)
  frontend/src/views/AdminPublishView.vue
  frontend/src/views/AdminView.vue
  frontend/src/views/DetailView.vue
  frontend/src/views/HomeView.vue
  frontend/src/components/HelloWorld.vue
  frontend/src/components/MilkdownEditor.vue
  ```
  Also delete the legacy backend `backend/app.py` (Flask app) and `backend/requirements.txt` to remove the Flask code path entirely — neither is referenced by `pyproject.toml` or any test.
- **Verification:** `pnpm build` from a clean tree should not pull in `milkdown`; `grep -rn "src/main.js\|src/views/HomeView" frontend/` returns no hits; `pnpm dev` boots through the proxy.

## P1 findings (must fix before declaring v1)

### `cards/service.publish` derives the slug twice when `payload.slug` is set
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\service.py:90-97`
- **Symptom:** Both branches run when `payload.slug` is present:
  ```python
  base = slugify(payload.slug or payload.title)
  if payload.slug:
      base = slugify(payload.slug)
  ```
  Idempotent but unsightly; more importantly it makes the slug-from-title path unreachable for static analysis. Behaviour is correct today but the next refactor will land a regression.
- **Root cause:** B5 left a stub branch in.
- **Fix:**
  ```python
  base = slugify(payload.slug) if payload.slug else slugify(payload.title)
  slug = await unique_slug(self.session, base)
  ```
- **Verification:** existing `test_cards.py` continues passing.

### `cards/service.update` toggles `body_html` only when category is `'local'` after switch — external rows can keep stale `body_html`
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\service.py:174-198`
- **Symptom:** When a card is updated from `local` to `external`, the code sets `card.body = None; card.body_html = None` (good). When the category stays `external` but `body` was somehow non-null on disk (legacy data), `body_html` is never cleared because the `external` branch only nulls when `category_changed or card.body is not None`. Edge case: a payload that keeps `external` but updates other fields will keep the old `body_html` if it ever existed. Risk surfaces post-migration if any imported row has stale html columns.
- **Root cause:** the conditional `if category_changed or card.body is not None` on line 184 reads `card.body` after `card.url = merged_url` but before assigning `card.body = None`. Logic is intentionally idempotent but never zeroes `body_html` when the local→external transition happens via `update` if `body` was already None (which is the migrated-correct state).
- **Fix:** unconditional `card.body = None; card.body_html = None` in the external branch.
- **Verification:** add a test that publishes external, then PUTs with `{title: 'x'}` and asserts `body_html` is `None`.

### `cards/repo.update` and `insert` issue `commit()` inside the request — collides with `get_session` rollback contract
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\repo.py:136-186`
- **Symptom:** Repository methods call `await self.session.commit()` directly. The FastAPI `get_session` dependency is responsible for transaction lifecycle (it rolls back on exception, closes in finally). Committing inside the repo means an `AppError` raised after the commit cannot be undone, and the cover atomic write in `covers/service.py` happens *before* the cards-row update — if the row update raises, the cover file on disk is nowahead of the DB. A SQLite WAL deploy with a single writer mostly hides this, but it ships the wrong concurrency model.
- **Root cause:** B5 chose repo-level commits to keep the call sites short. The spec (§3.2) puts transaction control at the service layer.
- **Fix:** drop `commit()` from `insert`, `update`, `set_cover`, `delete`. Either let `get_session` flush+commit on `__aexit__`, or have `CardService` call `await self.session.commit()` at the end of each write operation (matches "After every write, re-`SELECT` and return the fresh row" in §3.2).
- **Verification:** after the fix, posting two cards in the same request (e.g., a future bulk-import endpoint) becomes atomic; covers test should still pass.

### `covers/routes.post_cover` opens two AsyncSessions per request
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\covers\routes.py:60-108`
- **Symptom:** The router declares `dependencies=[Depends(_require_admin)]` AND a separate `session: AsyncSession = Depends(get_session)`. `_require_admin` recurses into `_get_current_user`, which itself depends on `Depends(get_session)`. FastAPI memoises by the dep callable, so the two `get_session` invocations resolve to the same session in this case — but only because the lazy `_require_admin` import landed; if the lazy stub branch fires (its `try/except Exception` swallows ImportError), the admin check silently no-ops and any unauthenticated client can upload covers. There is no test that exercises the production wiring through both deps.
- **Root cause:** the covers/routes.py defensive `try/import ... except Exception: async def _require_admin(): return None` is permanently shipped; if any future refactor breaks the import (circular, rename) the cover endpoint becomes anonymous.
- **Fix:** drop the soft import. Cards and auth are no longer "in flight" — make the import a hard one and let `pytest -k import` catch a regression:
  ```python
  from app.features.auth.deps import _require_admin
  from app.features.cards.repo import CardRepository```
  Same for the lazy `get_session` import.
- **Verification:** `pytest tests/integration/test_covers.py` runs unchanged; rename `_require_admin` temporarily and assert ImportError instead of silently authorizing.

### `_require_admin` and `_get_current_user` use private (underscore-prefixed) names exposed via re-import
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\deps.py:33,84` and `app/features/covers/routes.py:43-45`
- **Symptom:** Covers route imports `_require_admin` (leading underscore = "private"). Pyright in strict mode will flag this; the spec exposes `AdminUser = Annotated[User, Depends(_require_admin)]` precisely so callers go through the typed alias.
- **Root cause:** B6 wired its lazy import against the implementation detail.
- **Fix:** export `require_admin` (public) or have covers/routes.py use `AdminUser`:
  ```python
  from app.features.auth.deps import AdminUser
  ...
  async def post_cover(..., _admin: AdminUser, ...) -> CoverUploadResponse: ...
  ```
  (The auth feature also needs `require_admin = _require_admin` in the public surface, or rename outright.)
- **Verification:** `grep -nr "_require_admin\|_get_current_user" backend/src` returns only the dep file itself.

### `auth/deps._get_current_user` swallows the prefix check case-insensitively but never trims the header — `Authorization: bearer <token>\n` with stray newline raises 401 with no log
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\deps.py:50-55`
- **Symptom:** Minor; the code works for happy paths. But `decode_jwt` raises `Unauthorized("unauthenticated", "invalid token")` — the deps then re-raise. Any non-`Unauthorized` exception path is wrapped via `except Exception as exc` (line 64), which is a `noqa: BLE001` blanket — internal SQLAlchemy errors during `repo.get_by_id` will be reported as 401 instead of 500. That obscures real DB failures.
- **Root cause:** the broad except was scoped to `decode_jwt` but covers the repo call too.
- **Fix:** narrow the `try` to `decode_jwt` only:
  ```python
  try:
      claims = decode_jwt(token)
  except Unauthorized:
      raise

  sub = claims.get("sub")
  ...
  user = await repo.get_by_id(user_id)  # outside the try
  ```
- **Verification:** add a test that mocks `repo.get_by_id` to raise `OperationalError` — should bubble up as 500, not 401.

### `LoginRequest` has no `min_length` on password — empty `password` body returns 401, not 422
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\schemas.py` (not shown but referenced) — schema spec at phase2 §3.4 says `password: str min_length=1max_length=256`
- **Symptom:** `tests/integration/test_auth.py::test_login_rejects_empty_username` asserts 422 on empty `username` — currently fails because the test doesn't reach the handler (also blocked by the auth-prefix P0). After P0 #1 lands, validate the schema actually pins `min_length=1`.
- **Root cause:** unknown until Read confirms; should be inspected.
- **Fix:**ensure the schema enforces `min_length=1`. If already present this is a no-op.
- **Verification:** the empty-username and oversized-payload tests should pass after the prefix fix.

### Slug repo `unique_slug` query overruns on prefix collision
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\slug.py:103-111`
- **Symptom:** `Card.slug.like(f"{base}%")` matches `base`, `base-2`, butALSO `basecamp`, `baseline`. Walking `-2/-3/...` is still correct, but the `taken` set bloats. With a malicious blob of similarly-named slugs an attacker could force the loop to walk a long way. More importantly, if a future feature pushes slugs into the millions this becomes O(N).
- **Root cause:** prefix LIKE matches sub-words.
- **Fix:** anchor the match at a hyphen or exact equality:
  ```pythonCard.slug.like(f"{base}%"), or_(Card.slug == base, Card.slug.like(f"{base}-%"))
  ```
- **Verification:** `pytest tests/unit/test_slug.py` plus a new test for `slugify("base") -> base; slugify("baseline") -> baseline; unique_slug returns base when only baseline is taken`.

### `Settings._refuse_placeholder_secret` only blocks 3 placeholders — `JWT_SECRET=00000000000000000000000000000000` passes
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\config.py:81-89`
- **Symptom:** Validator rejects `change-me`, `changeme`, `secret`. Any other 32-char placeholder (all-zeros, all-`a`, `password-must-be-at-least-32!`) is accepted. The risk model in §1wants "missing/short JWT_SECRET crashes loudly" — entropy is not checked.
- **Root cause:** validator is a denylist, not an entropy floor.
- **Fix:** require the secret to have at least, say, 16 distinct characters (or run through a Shannon-entropy floor):
  ```python
  if len(set(value)) < 16:
      raise ValueError("JWT_SECRET appears to be a placeholder; rotate to a high-entropy secret.")
  ```
- **Verification:** unit test asserts the validator fires on `'a' * 32`.

### Bcrypt password truncation happens silently — passwords longer than 72 bytes are accepted but only first 72 verified
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\security.py:23-44`
- **Symptom:** `_truncate_for_bcrypt` truncates to 72 bytes both at hash and at verify. A password of 73 chars verifies successfully against a hash of the first 72 chars — fine. But a UTF-8 password whose 73rd byte falls inside a multi-byte codepoint will silently slice the codepoint, producing a different verify result on systems that normalize differently. Edge case is small.
- **Root cause:** byte-level truncation across UTF-8 boundaries.
- **Fix:** truncate by codepoints rather than bytes (or document the limit), or use `bcrypt`'s built-in 72-byte handling and cap the schema at 72 chars upstream.
- **Verification:** unit test with a password whose 72nd byte is mid-codepoint asserts verify is consistent.

### Frontend `auth/api.ts` and `cards/api.ts` use relative imports while every other file uses `@/`
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\src\features\auth\api.ts:12-17`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\src\features\cards\api.ts:12-22`
- **Symptom:** Both files use `'../../shared/api/client'` while the rest of the codebase (covers, App.vue, useCoverUpload) uses `'@/shared/...'`. Inconsistent imports break refactors that move feature dirs.
- **Root cause:** B10/B11 didn't pick up the alias. `tsconfig.app.json` and `vite.config.ts` both define `'@'`.
- **Fix:** rewrite imports to `'@/shared/api/client'` and `'@/shared/types/domain'`.
- **Verification:** `pnpm typecheck && pnpm lint` should pass.

### `useCoverUpload` lives at `shared/composables/` but spec §4.1 + components import contract expects `features/covers/composables/`
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\src\shared\composables\useCoverUpload.ts` vs empty `frontend/src/features/covers/composables/`
- **Symptom:** The spec's directory tree (§4.1) places `useCoverUpload` at `features/covers/composables/`. Phase 3 report flagged this and chose §9's `shared/composables/` (Phase 3 calls §9 "law"). Either choice is fine, but the empty `features/covers/composables/` directory is a confusion artifact that will trip a future contributor.
- **Fix:** either move the file to `features/covers/composables/useCoverUpload.ts` (and update its only caller `features/cards/components/PublishForm.vue` or wherever it is imported from), or `git rm -rf features/covers/composables/`. Adopt one location and document it.
- **Verification:** `grep -rn "useCoverUpload" frontend/src/` shows a single source-of-truth path.

### `frontend/openapi/schema.json` is 529 lines but does not include the auth router (because of P0 #1)
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\openapi\schema.json`
- **Symptom:** A regen happened against an earlier (broken) backend; `paths` likely lists `/login` and `/me` (no `/auth` prefix) but `frontend/src/features/auth/api.ts` uses `'/auth/login'`. The TypeScript types could already disagree with the wire shape. After P0 #1 lands, the schema must be regenerated.
- **Root cause:** snapshot generated before B4 prefix was even discussed.
- **Fix:** after fixing the auth prefix and validation handler, run `LG_UPDATE_OPENAPI_SNAPSHOT=1 pytest backend/tests/integration/test_openapi_snapshot.py` then `pnpm gen:api` in `frontend/`.
- **Verification:** `cat frontend/openapi/schema.json | jq '.paths | keys'` includes `/auth/login` and `/auth/me`.

### `pyproject.toml` filterwarnings = ["error::DeprecationWarning"] — Starlette's `HTTP_422_UNPROCESSABLE_ENTITY` deprecation will start failing tests on the next dependency bump
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\pyproject.toml` last section
- **Symptom:** Pytest already prints `StarletteDeprecationWarning:'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead.`4 times. The filter is set to `error::DeprecationWarning` which would normally turn warnings into errors. Currently `StarletteDeprecationWarning` is not a DeprecationWarning subclass so it's exempt — but at the next Starlette release it will be, and the suite breaks.
- **Root cause:** `core/errors.py:190` and other call sites use `status.HTTP_422_UNPROCESSABLE_ENTITY` from FastAPI, which Starlette has renamed.
- **Fix:** swap to literal `422`, or use `status.HTTP_422_UNPROCESSABLE_CONTENT` once the project's FastAPI/Starlette versions support it.
- **Verification:** warning disappears from `pytest -W error` output.

## P2 findings (nice-to-have)

### Legacy `backend/app.py` (Flask app) still in repo
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\app.py`
- **Symptom:** The old Flask backend file is still on disk alongside `pyproject.toml`. It does not import from the new `app/` package, but a `python -m flask --app app run` would still launch the old code path. A confused operator could point production at it. `requirements.txt` (4lines, `flask flask-cors markdown`) still ships next to `pyproject.toml` and `uv.lock`.
- **Fix:** `git rm backend/app.py backend/requirements.txt`.

### Legacy data tree at `backend/data/cards.json` and `backend/content/notes/*.md` not chmod'd to read-only
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\data\cards.json`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\content\notes\*.md`
- **Symptom:** Spec §1 and §5 require these to be read-only after migration. Current new code path does not read them (verified via `grep -r'cards.json' backend/src` — no hits), so this is preventative. The chmod step is the deploy script's job (§5 "Post-migration step") — flag it for the integrator to verify on the host.

### `cards/repo.py` `func.cast(Card.tags, String)` makes the `q` filter scan the JSON column twice
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\repo.py:55-77`
- **Symptom:** Both the `tag` filter and the `q` filter cast `Card.tags` to `String` and apply LIKE. SQLite recomputes the cast per row. With dozens of cards this is fine; if the workload grows past a few hundred rows, the LIKE-scan dominates. The second-stage Python filter on `tag` already corrects the false-positive rate, so the SQL cast is essentially a hint, not a guarantee.
- **Fix:** drop the SQL cast for `tag` (let the Python filter own correctness) and keep only the `q` cast.

### `auth/service.py` _DUMMY_HASH is hardcoded and 53 chars — bcrypt expects 60-char hashes; verify_password silently returns False
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\service.py:80`
- **Symptom:** The53-char string is not a valid bcrypt hash. `verify_password` catches the `ValueError` and returns False (line 41-43 in security.py). Net effect: the timing-equalization branch runs ~zero work, defeating the purpose of the dummy verify.
- **Fix:** Generate a real bcrypt hash at import time:
  ```python
  _DUMMY_HASH = hash_password("dummy")  # one-time cost at import
  ```
  Or precompute a real60-char hash and ship it as a constant.

### `cards/service.delete` re-resolves the card via `get_by_id` then issues `repo.delete(card)` which itself runs `sa_delete(...).where(Card.id == card.id)` — could be `repo.delete_by_id(card_id)` to halve the round-trips
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\repo.py:177-185`
- **Symptom:** Two queries per delete. Cover-cleanup needs the cover URL so the get is justified, but the delete path takes the loaded `Card` only to grab `card.id` again.
- **Fix:** keep `get_by_id` (need cover URL), but skip the second SELECT inside `repo.delete`:
  ```python
  async def delete(self, card_id: UUID) -> None:
      await self.session.execute(sa_delete(Card).where(Card.id == card_id))
  ```

### `covers/service._write_atomically` does not call `os.fsync` on the directory — POSIX rename durability gap
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\covers\service.py:243-251`
- **Symptom:** Atomic file rename is durable only if the directory is fsync'd after rename. On a host crash mid-deploy, the rename may not be visible.
- **Fix:** open the parent dir read-only, fsync, close. Skip on Windows (CWE not applicable).

### `cards/service._unlink_cover_file` strips the cache-buster but doesn't validate the rest of the path is within `covers_dir` before resolving
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\service.py:264-299`
- **Symptom:** Defensive `resolve()` check after the join, but if a card row's `cover` field was tampered with directly in the DB to contain `/covers/../../../etc/passwd`, the join would resolve outside the covers dir; the check catches it. Still, allowlist the filename pattern (`<uuid>.{png,jpg,webp}`) for clarity.
- **Fix:** validate via regex before the unlink.

### `_get_current_user` does not verify the `role` claim matches the DB row's role on every request
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\deps.py:67-81`
- **Symptom:** JWT contains `role` but the depignores it and checks `user.role` from the DB — that's fine for security, but means a freshly-demoted user is locked out as soon as the token's signature is re-verified. Not a bug; document.

### Frontend `tags/api.ts` does not call `mapResponseError` like covers/api.ts does
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\src\features\tags\api.ts:16-19`
- **Symptom:** `tags/api.ts` re-throws the raw `error` object. Other feature wrappers throw `AppError` via `mapResponseError`. Inconsistent error handling at the call site.
- **Fix:** route through `mapResponseError(error, response)` like `covers/api.ts`.

### `vite.config.ts` ships the dev `checker` plugin with `eslint.lintCommand = 'eslint .'` — runs ESLint over `node_modules` symlinks on every save
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\frontend\vite.config.ts:18-24`
- **Symptom:** `eslint .` plus defaultignore rules — fine — but the error overlay in dev fires on every linted file change. With the legacy `vite.config.js` and `src/main.js` still on disk, the checker hits both file trees.

## Summary

The merged backend imports cleanly and most feature suites pass in isolation, but **end-to-end the app does not work**: any `/api/v1/auth/*` request 404s (P0 #1), any successful login crashes on `encode_jwt` (P0 #2), the conftest fixture is misnamed so the auth suite never even runs (P0 #4), and the 422 envelope crashes when validators raise (P0 #3). The OpenAPI contract gate is empty so the frontend types could be lying right now (P0 #6). On the frontend side, the legacy js/views/components files stillship and will land in the production bundle (P0 #7).

Confidence in this layer is low until the seven P0s are cleared. Once they are, the test suite should drop from 10 fail/5 error to (close to) zero. The P1s are real bugs but don't block the smoke test; the P2s are hygiene.

Recommended sequence: fix P0 #1 (auth prefix), #2 (kwarg), #3 (validation handler), #4 (fixture name), #5 (tagsordering) in one commit; regenerate the OpenAPI snapshot + frontend schema (P0 #6) in a second commit; nuke legacy files (P0 #7) in a third. Then re-run `pytest` and `pnpm build` and reassess.
