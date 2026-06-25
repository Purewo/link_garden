# Phase 4 fix plan

## Headline

The merged Phase 4 tree cannot accept a single login and ships an anonymous cover-upload endpoint as the dependency-import fails open; all three reviewers converge on the same seven blocking defects (auth prefix, `encode_jwt` kwarg, validation handler 500s, conftest fixture name, covers admin gate, empty OpenAPI snapshot, legacy file shadowing) plus a static `/covers` mount that was never wired. Land F1through F8 in one commit chain, regenerate the contract, then move on to P1 hardening.

## P0 fixes (block deploy) — ordered

### F1 — Add `/auth` prefix to the auth router
- **Files:** `backend/src/app/features/auth/routes.py`
- **Symptom:** `POST /api/v1/auth/login` and `GET /api/v1/auth/me` 404; nginx `lg_login` rate-limit zone keyed on `location = /api/v1/auth/login` is bypassed; frontend `features/auth/api.ts` and OpenAPI snapshot test both disagree with the live paths.
- **Fix:** Change line 27 from `router = APIRouter(tags=["auth"])` to `router = APIRouter(prefix="/auth", tags=["auth"])`. Do not paper over this at `main._build_v1_router` — every other feature router carries its own prefix; keep the convention.
- **Verification:** `uv run pytest backend/tests/integration/test_auth.py -k login` passes; `curl -fsS -X POST http://127.0.0.1:5001/api/v1/auth/login -H 'content-type: application/json' -d '{"username":"admin","password":"…"}'` returns 200; `curl http://127.0.0.1:5001/api/v1/login` returns 404.
- **Source:** R1, R2, R3

### F2 — Fix `encode_jwt` keyword argument in `mint_token`
- **Files:** `backend/src/app/features/auth/service.py`
- **Symptom:** Every successful credential check throws `TypeError: encode_jwt() got an unexpected keyword argument 'ttl'`; the catch-all 500 handler hides it, login is unreachable.
- **Fix:** Line 68: `token = encode_jwt(claims, ttl=ttl)` → `token = encode_jwt(claims, ttl_seconds=ttl)` to match the canonical signature in `core/security.py:46`.
- **Verification:** `uv run pytest backend/tests/integration/test_auth.py::test_login_returns_jwt`; manual `curl` returns an HS256 JWT with `exp = iat + 43200`.
- **Source:** R1, R2, R3

### F3 — Serialize `RequestValidationError.errors()` through `jsonable_encoder`
- **Files:** `backend/src/app/core/errors.py`
- **Symptom:** Pydantic v2 surfaces `ctx: {error: ValueError(...)}` rows; `[dict(err) for err in errors]` keeps the live exception; `JSONResponse` calls `json.dumps`, raises `TypeError: Object of type ValueError is not JSON serializable`; the catch-all returns 500 `internal_error` instead of 422 `validation_failed`, breaking every meaningful validator (URL/body coupling, slug shape, etc.).
- **Fix:** In `_validation_exception_handler` (lines 177–196):
  ```python
  from fastapi.encoders import jsonable_encoder
  ...
  detail=jsonable_encoder(errors),
  ```
  Drop the `dict(err)` comprehension.
- **Verification:** Add `tests/integration/test_errors.py::test_validation_returns_422` POSTing `{"username":""}` to `/api/v1/auth/login`; assert `status_code == 422`, `json()["code"] == "validation_failed"`, `detail` is a list of plain dicts (no embedded exceptions).
- **Source:** R1, R2, R3

### F4 — Rename conftest fixture `db_session` → `session` (and add `admin_user` / `admin_token`)
- **Files:** `backend/tests/conftest.py`
- **Symptom:** Auth suite fails with `fixture 'session' not found. available fixtures: …, db_session, …` — 5 ERRORs + several FAILs collapse before assertions run.
- **Fix:** Rename the fixture function from `db_session` to `session` (the name the auth suite documents and the cards suite expects). Add two new fixtures:
  ```python
  @pytest_asyncio.fixture()
  async def admin_user(session: AsyncSession) -> User: ...
  @pytest_asyncio.fixture()
  async def admin_token(admin_user: User) -> str:  # returns "Bearer <jwt>"
      return f"Bearer {mint_token(admin_user).access_token}"
  ```
  Keep a one-line alias `db_session = session` if a downstream test still references the old name; remove once callers are migrated.
- **Verification:** `uv run pytest backend/tests/integration/` drops the 5 ERRORs and the 7 fixture-name FAILs.
- **Source:** R1, R3

### F5 — Sort `list_distinct_tags` by `(created_at, id)` for deterministic dedup
- **Files:** `backend/src/app/features/tags/repo.py`
- **Symptom:** `select(Card.tags).order_by(Card.id)` orders by random UUID; `Vue` vs `vue` first-seen casing flips between runs; `test_list_distinct_tags_distinct_and_sorted` fails non-deterministically.
- **Fix:** Line 40: `stmt = select(Card.tags).order_by(Card.created_at.asc(), Card.id.asc())`.
- **Verification:** `uv run pytest backend/tests/integration/test_tags.py` passes; rerun three times to confirm stable ordering.
- **Source:** R1

### F6 — Make covers admin gate hard-fail at import time and type `CoverUploadResponse.card`
- **Files:** `backend/src/app/features/covers/routes.py`, `backend/src/app/features/covers/schemas.py`, `backend/src/app/features/covers/service.py`, `backend/src/app/features/cards/service.py`
- **Symptom:** (a) `routes.py` wraps `from app.features.auth.deps import _require_admin` and the `CardRepository` import in `try/except Exception` that installs an `async def _require_admin(): return None` stub on any import error — auth gate fails OPEN; an unauthenticated client can POST multipart uploads. (b) `CoverUploadResponse.card: Any = None` — the ORM `Card` is returned raw, `openapi-typescript` lifts `card` as `Record<string, never>`, and the frontend already needed a `// @ts-expect-error`.
- **Fix:**
  1. Delete both `try/except Exception` blocks. Replace with:
     ```python
     from app.core.db import get_session
     from app.features.auth.deps import AdminUser
     ```
     and use `AdminUser` as a typed dep in the route signature instead of `dependencies=[Depends(_require_admin)]`. Drop the leading underscore via a public re-export `require_admin = _require_admin` in `auth/deps.py`.
  2. Remove the direct `CardRepository` import from `covers/routes.py`. Add `CardService.attach_cover(card_id: UUID, cover_url: str) -> Card` to `features/cards/service.py` (delegates to `CardRepository.set_cover`); the covers service consumes a `CardService` instead.
  3. In `covers/schemas.py` replace `card: Any = None` with `card: CardRead` (import from `app.features.cards.schemas`). In `covers/service.py`, project theORM row through `CardRead.model_validate(updated_card)` before constructing `CoverUploadResponse`.
- **Verification:** `uv run pytest backend/tests/integration/test_covers.py`. Add `test_post_covers_requires_auth` asserting 401 with no `Authorization`. Temporarily rename `auth/deps.AdminUser` and confirm the app fails to import (instead of silently authorizing). Run `pnpm gen:api` and verify the generated `card` field is typed `components.schemas.CardRead`. `grep -r "from app.features.cards" backend/src/app/features/covers` returns no hits.
- **Source:** R1, R2, R3

### F7 — Mount `/covers` static files and add the dev proxy entry
- **Files:** `backend/src/app/main.py`, `frontend/vite.config.ts`
- **Symptom:** Spec §3.8 requires `app.mount('/covers', StaticFiles(...))`; not wired. `GET /covers/<uuid>.png` 404s against the dev server; production nginx hides the gap. Vite dev proxy only forwards `/api`.
- **Fix:**
  1. In `main.create_app`, after `register_handlers(app)`:
     ```python
     from fastapi.staticfiles import StaticFiles
     covers_dir = settings.covers_dir
     covers_dir.mkdir(parents=True, exist_ok=True)
     app.mount(settings.COVERS_PUBLIC_PREFIX, StaticFiles(directory=covers_dir), name="covers")
     ```
  2. Add to `vite.config.ts` `server.proxy`:
     ```ts
     '/covers': { target: 'http://127.0.0.1:5001', changeOrigin: true },
     ```
- **Verification:** `curl -fsS http://127.0.0.1:5001/covers/<known-uuid>.png -o /tmp/x.png`; `curl http://127.0.0.1:5173/covers/<uuid>.png` proxied identically.
- **Source:** R3

### F8 — Remove legacy files; regenerate OpenAPI snapshot and TS schema
- **Files:** delete: `backend/app.py`, `backend/requirements.txt`, `backend/data/cards.json`, `backend/content/notes/`, `frontend/vite.config.js`, `frontend/src/main.js`, `frontend/src/style.css`, `frontend/src/views/{HomeView,DetailView,AdminView,AdminPublishView}.vue`, `frontend/src/components/{HelloWorld,MilkdownEditor}.vue`, `frontend/src/features/covers/composables/` (empty); regenerate: `backend/tests/fixtures/openapi_snapshot.json`, `frontend/openapi/schema.json`, `frontend/src/shared/api/schema.d.ts`.
- **Symptom:** Legacy Flask `app.py` shadows `app/` package on `sys.path`. Legacy `vite.config.js` and `main.js` race the new `*.ts` ones; `MilkdownEditor.vue` references a `milkdown` package not in deps so any transitive resolution breaks `pnpm build`. Empty 1-byte `openapi_snapshot.json` makes the contract test fail-fast; the hand-rolled `frontend/openapi/schema.json` predates F1/F2 so its `paths` still claim `/login`/`/me`.
- **Fix:** `git rm` every file above (run this AFTER F1–F7 land so the regenerated artifacts capture the real shape). Then:
  ```
  LG_UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest backend/tests/integration/test_openapi_snapshot.py
  pnpm --dir frontend gen:api
  git add backend/tests/fixtures/openapi_snapshot.json frontend/openapi/schema.json frontend/src/shared/api/schema.d.ts
  ```
- **Verification:** `pnpm --dir frontend build` succeeds without `milkdown`; `grep -rn "src/main.js\|HomeView" frontend/` empty; `jq '.paths | keys' frontend/openapi/schema.json` includes `/auth/login` and `/auth/me`; the snapshot test passes a second time without the env var.
- **Source:** R1, R2, R3

## P1 fixes (block v1) — ordered

### F9 — Move transaction commits out of repositories into `get_session`
- **Files:** `backend/src/app/features/cards/repo.py`, `backend/src/app/core/db.py`, `backend/src/app/features/covers/service.py`
- **Symptom:** `CardRepository.insert/update/delete/set_cover` each call `await self.session.commit()`; cover-upload writes the file with `os.replace` and then commits the row update — if the row update fails the file is already on disk, and the service-layer `rollback()` is a no-op after a commit. Multi-step service operations cannot be atomic.
- **Fix:** Strip `await self.session.commit()` from all four repo methods (keep `flush` + `refresh`). Update `get_session` to `await session.commit()` on successful generator return and `await session.rollback()` on exception (it already does the rollback half).
- **Verification:** Inject a session whose `commit` raises mid-cover-upload; assert `cards.cover` retains its previous value and the new file is unlinked. `uv run pytest backend/tests/integration/` green.
- **Source:** R1, R2, R3

### F10 — Tighten placeholder-secret validators (`JWT_SECRET`, `LG_ADMIN_PASSWORD`)
- **Files:** `backend/src/app/core/config.py`, `deploy/env/linkgarden.env.example`
- **Symptom:** `_refuse_placeholder_secret` blocks only `change-me|changeme|secret`; the example fileships `JWT_SECRET=REPLACE_ME_WITH_openssl_rand_hex_32_OUTPUT` (41 chars, passes `min_length`). `LG_ADMIN_PASSWORD=REPLACE_ME_AT_LEAST_8_CHARS` likewise passes and seeds the admin row.
- **Fix:** In the validator, reject any value matching `replace_me` (case-insensitive), any value matching `^[A-Z_]+$`, or where `len(set(value)) < 16`. Apply to both fields. Optionally standardise the example file on a single literal sentinel (`__UNSET__`) and reject it everywhere.
- **Verification:** Unit test `tests/unit/test_config.py::test_placeholder_secret_rejected` constructs `Settings(JWT_SECRET="REPLACE_ME_WITH_openssl_rand_hex_32_OUTPUT", ...)` and asserts `ValidationError`.
- **Source:** R2

### F11 — Generate a real `_DUMMY_HASH` at module load (close timing oracle)
- **Files:** `backend/src/app/features/auth/service.py`
- **Symptom:** The hard-coded `_DUMMY_HASH` is 53 chars (bcrypt hashes are 60); `bcrypt.checkpw` raises `ValueError`, `verify_password` swallows and returns `False` immediately. The "user-not-found" branch runs zero bcrypt work, opening exactly the timing oracle the dummy was meant to close.
- **Fix:** Replace the constant with `_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))` computed at import time.
- **Verification:** `tests/unit/test_security.py::test_dummy_hash_is_valid_bcrypt` asserts `verify_password("anything", _DUMMY_HASH) is False` AND elapsed time ≥ 50 ms; timing of user-found-but-wrong-password and user-not-found agree within 10%.
- **Source:** R1, R2

### F12 — Run pyright in `strict` mode under `src/app`
- **Files:** `backend/pyrightconfig.json`
- **Symptom:** Whole project pinned to `typeCheckingMode: basic` with `reportUnknown*` disabled; the `encode_jwt(ttl=...)` kwarg drift (F2) shipped silently because nothing typechecked the call site.
- **Fix:**
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
  ```Resolve the surfaced errors feature-by-feature.
- **Verification:** `uv run pyright` reports `0 errors` against `src/app`.
- **Source:** R3

### F13 — Add server-side login throttle, gate prod docs, tighten CSP and per-route body limits
- **Files:** `backend/src/app/features/auth/service.py` (+ new `login_attempts` table via Alembic), `backend/src/app/main.py`, `backend/src/app/features/cards/schemas.py`, `deploy/nginx/linkgarden.conf`
- **Symptom:** (a) Credential-stuffing brake lives only in nginx; expose 5001 once and it is gone. (b) `/api/v1/docs`, `/redoc`, `/openapi.json` are public in prod — full attack-surface map at one URL. (c) CSP `img-src 'self' data: https:` permits arbitrary third-party trackers in admin-published markdown. (d) `client_max_body_size 6m` applies to JSON endpoints; a 6 MiB markdown body is parsed by Pydantic + markdown-it + nh3 and can OOM a 2-worker gunicorn.
- **Fix:** (a) Add `login_attempts(username, ip, attempted_at)` with a 5-failures-in-5-min lock returning 429 `too_many_attempts`; reset on success. (b) In `create_app`, when `settings.APP_ENV == "prod"` pass `docs_url=None, redoc_url=None` (keep `openapi_url` behind an admin dep or nginx allowlist). (c) Drop `https:` from `img-src`; keep `'self' data:` only, proxy required third-party images through `/covers/`. (d) Set `client_max_body_size 1m` on `location /api/v1/cards*` and keep `6m` on `/api/v1/covers`. Cap `CardCreate.body`/`CardUpdate.body` at 256 KiB via Pydantic `max_length`.
- **Verification:** Six wrong-password attempts → 6th is 429; `curl https://.../api/v1/docs` returns 404 with `APP_ENV=prod`; browser DevTools shows blocked third-party image; `curl -X POST -d "$(python -c 'print("a"*2_000_000)')" .../api/v1/cards` returns 413.
- **Source:** R2

### F14 — Pin markdown `<input>` to `type=checkbox`
- **Files:** `backend/src/app/services/markdown.py`
- **Symptom:** `ALLOWED_ATTRS["input"] = {"type", "checked", "disabled"}` permits any value of `type=` (including `hidden`); only current renderer output is safe, but the allowlist is broader than the actual GFM tasklist surface.
- **Fix:** Either pass `set_tag_attribute_values={"input": {"type": "checkbox"}}` to `nh3.clean`, or drop `<input>` entirely and post-process the rendered token stream into `<span class="task-checkbox">`. Shrink `ALLOWED_ATTRS["input"]` to `{"checked", "disabled"}`.
- **Verification:** New corpus rows in `tests/unit/test_markdown.py`: `render_markdown('<input type="hidden" name="x">')` strips the tag; `render_markdown('- [x] item')` keeps exactly one `<input type="checkbox" checked disabled>`.
- **Source:** R2

### F15 — Add gitleaks to CI (server-side enforcement)
- **Files:** `.github/workflows/backend.yml` (or a new `security.yml`)
- **Symptom:** gitleaks runs only as a pre-commit hook; `--no-verify` bypasses it; contributors without pre-commit installed have no protection.
- **Fix:** New CI job pinned to gitleaks `v8.21.2` running `gitleaks detect --redact --no-banner --exit-code1` against the PR diff and full history on `main` pushes.
- **Verification:** Open a draft PR injecting a 64-hex `JWT_SECRET=…` into `deploy/env/linkgarden.env.example`; CI turns red.
- **Source:** R2

### F16 — Bind `CardListQuery` via `Annotated[..., Depends()]`; align frontend type
- **Files:** `backend/src/app/features/cards/routes.py`, `frontend/src/features/cards/api.ts`
- **Symptom:** The list endpoint declares each filter as `Query(...)` and re-instantiates `CardListQuery(...)` with `# type: ignore[arg-type]`. `category` and `group` lose their `Literal[...]` types on the wire; the frontend had to mirror `CardListQuery` locally.
- **Fix:** Replace explicit `Query()` params with `query: Annotated[CardListQuery, Depends()]`. Drop the local `CardListQuery` interface from `features/cards/api.ts` and re-import from the generated `paths`.
- **Verification:** OpenAPI snapshot diff shows `parameters` typed against the literals; `pnpm typecheck` clean; `pnpm test` green.
- **Source:** R3

### F17 — Move `useCoverUpload` under `features/covers/composables/`; align frontend imports to `@/`
- **Files:** `frontend/src/shared/composables/useCoverUpload.ts` → `frontend/src/features/covers/composables/useCoverUpload.ts`, `frontend/src/features/auth/api.ts`, `frontend/src/features/cards/api.ts`, callers of `useCoverUpload`
- **Symptom:** (a) Spec §4.1 places `useCoverUpload` under `features/covers/composables/`; the implementation lives in `shared/composables/`, the documented location empty — `shared/` is also now importing from `features/`, inverting the dependency rule. (b) `auth/api.ts` and `cards/api.ts` use relative `'../../shared/api/client'` while every other file uses `'@/shared/...'`.
- **Fix:** Move the composable, update its imports, update its single caller (`PublishForm.vue`), delete the now-empty `features/covers/composables/` placeholder if it's separate. Rewrite the two relative imports to `'@/shared/api/client'` and `'@/shared/types/domain'`.
- **Verification:** `grep -rn "shared/composables/useCoverUpload" frontend/src` empty; `pnpm typecheck && pnpm lint && pnpm test` green.
- **Source:** R1, R3

### F18 — Add `frontend/src/tests/setup.ts` with typed MSW handlers
- **Files:** `frontend/src/tests/setup.ts` (new), `frontend/vitest.config.ts` (add to `setupFiles`)
- **Symptom:** Spec §4.1 expected a shared MSW setup typed against `import type { paths } from '@/shared/api/schema'`; missing means per-file mocks and silent server/SPA drift.
- **Fix:** Create `tests/setup.ts` registering MSW handlers with the generated `paths` types; reference it from vitest `setupFiles`.
- **Verification:** `pnpm test` loads the setup file; introduce a deliberate response-shape drift and confirm a typed handler call site errors.
- **Source:** R3

### F19 — Fix `unique_slug` LIKE anchor; deduplicate `service.publish` slug branch
- **Files:** `backend/src/app/features/cards/slug.py`, `backend/src/app/features/cards/service.py`
- **Symptom:** `Card.slug.like(f"{base}%")` matches `base`, `base-2`, `basecamp`, `baseline` — bloats the `taken` set and is O(N) at scale. `publish` derives `base` twice when `payload.slug` is set.
- **Fix:**
  ```python
  or_(Card.slug == base, Card.slug.like(f"{base}-%"))
  ```
  and in `service.publish`:
  ```python
  base = slugify(payload.slug) if payload.slug else slugify(payload.title)
  ```
- **Verification:** `tests/unit/test_slug.py` adds `slugify("baseline")` exists, `unique_slug("base")` returns `base` (not `base-2`); cards integration suite still green.
- **Source:** R1

### F20 — Recreate `ix_cards_archived_created_at` with `created_at DESC`
- **Files:** `backend/src/app/features/cards/models.py`, new `backend/alembic/versions/0002_index_desc.py`
- **Symptom:** Hot list path orders by `created_at DESC, id DESC`; current index orders ascending; SQLite has to reverse-walk. Not a runtime bug yet, but matters once cards reach thousands.
- **Fix:** In the model:
  ```python
  Index("ix_cards_archived_created_at", "archived", sa.text("created_at DESC"))
  ```
  Alembic migration drops and recreates the index with the matching DDL.
- **Verification:** `EXPLAIN QUERY PLAN SELECT * FROM cards WHERE archived=0 ORDER BY created_at DESC, id DESC LIMIT 50` shows `USING INDEX ix_cards_archived_created_at` without `TEMP B-TREE FOR ORDER BY`.
- **Source:** R3

### F21 — Narrow `_get_current_user` exception scope; promote `_require_admin` to public name
- **Files:** `backend/src/app/features/auth/deps.py`, `backend/src/app/features/covers/routes.py`
- **Symptom:** The `try/except Exception` in `_get_current_user` wraps both `decode_jwt` AND `repo.get_by_id`; a SQLAlchemy `OperationalError` becomes a 401 instead of 500. Covers route imports the private `_require_admin`.
- **Fix:** Restructure so only `decode_jwt` is inside the broad-except; let DB errors propagate. Export `AdminUser = Annotated[User, Depends(_require_admin)]` (or `require_admin` public) and have all callers use it.
- **Verification:** Mock `repo.get_by_id` to raise `OperationalError` → request returns 500, not 401. `grep -nr "_require_admin\|_get_current_user" backend/src` returns only `auth/deps.py`.
- **Source:** R1

## P2 fixes (nice-to-have) — bullet list

- Normalize `CardCreate.cover` / `CardUpdate.cover` query-string handling: pick one canonical form (strip `?v=` on store, OR keep it and adjust `_unlink_cover_file`) — currently mismatched. (R3)
- Switch cover cache-buster from `int(time.time())` to `time.time_ns()` or content hash to avoid same-second collisions under nginx `Cache-Control: public, immutable`. (R2)
- Consolidate `ok: Literal[True]` envelopes (`OkResponse` vs `CoverUploadResponse`) via a shared mixin. (R3)
- Add `__init__.py` to `features/` and each feature subpackage for tooling consistency. (R3)
- Add `CHECK (role IN ('admin'))` or a `Role(StrEnum)` to prevent silent demotion. (R2)
- Drop `OPTIONS` from the legacy `_legacy_redirect` shim so CORS preflight is handled by middleware. (R2)
- Pin `bcrypt.gensalt(rounds=12)` (via `Settings.BCRYPT_ROUNDS`) instead of relying on bcrypt default. (R2)
- Truncate passwords by codepoint, not byte, in `_truncate_for_bcrypt`. (R1)
- Replace `logging.getLogger` in `cards/service.py` with `structlog.get_logger` for consistent JSON logs. (R2)
- Drop the redundant SQL `func.cast(Card.tags, String)` LIKE filter for `tag` (Python second-stage already owns correctness). (R1)
- Replace `repo.delete(card)` with `repo.delete_by_id(card_id)` to halve query count. (R1)
- `os.fsync` the covers directory after `os.replace` for POSIX rename durability. (R1)
- Validate cover filename against `^[0-9a-f-]{36}\.(png|jpg|webp)$` after `_safe_join` as defense-in-depth. (R1, R2)
- Audit `frontend/src/shared/utils/` against spec §4.5 (`invariant`, `bytes`, `slug`, `date`) and fill missing modules. (R3)
- Route `frontend/src/features/tags/api.ts` through `mapResponseError` for consistent error envelopes. (R1)
- Switch `status.HTTP_422_UNPROCESSABLE_ENTITY` references to `_CONTENT` (or literal `422`) ahead of Starlette deprecation flipping to a `DeprecationWarning` subclass. (R1)
- Document JWT `role` claim semantics (DB row wins, freshly demoted users locked out on next request). (R1)

## Deduplication notes

- F1 (auth prefix), F2 (`encode_jwt` kwarg), F3 (validation handler), F8 (legacy files + empty OpenAPI snapshot) were raised by all three reviewers with identical diagnoses; took the minimal-edit form each proposed.
- F6 merges three overlapping findings: R1 "covers opens two `AsyncSessions`/uses private name" and "fail-open import", R2 "P0 admin gate fails OPEN", R3 "CoverUploadResponse.card typed `Any`". Single fix block removes the soft import, switches to typed `AdminUser`, replaces the cross-feature `CardRepository` import with a `CardService.attach_cover` seam, and types the response — addresses all three reviewers in one pass.
- F9 (transaction lifecycle) merges R1 "repo commits collide with `get_session`" and R2 "service-layer rollback not transactional"; took R2's framing (commit in `get_session`).
- F17 merges R1 "relative imports inconsistency" and R3 "useCoverUpload location" because both touch the same files.
- R1's `LoginRequest.password min_length` concern resolves once F1/F4 unblock the auth tests; if those still fail after F1–F4 land, add `min_length=1` to the schema then.

## What was deliberately deferred

- Cover cache-buster collision, `__init__.py` additions, `OkResponse` consolidation, `Role` enum, `bcrypt.gensalt(rounds=12)`, UTF-8 codepoint truncation, fsync on directory rename, filename regex hardening — none are exploitable post-F6/F10/F11, and each is a single-file cleanup that can ride a later quality-of-life PR.
- Mixed `logging`/`structlog` and the `func.cast` LIKE redundancy are cosmetic at current data sizes.
- Spec §3.2 "functions vs class" service style (R3 P2) is a preference call; class-based services with a one-line `*, author: User | None = None` parameter added later is sufficient for the v2 authorship feature.
- WCAG / accessibility validation, INP performance budgets, and any post-deploy Lighthouse work are explicitly out of scope for Phase 4 wiring fixes — handled in the v1 hardening pass that follows once the seven P0s and the priority P1s land.
