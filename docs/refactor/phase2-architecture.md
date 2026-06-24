# LinkGarden Architecture (Phase 2 — Final Spec)

> Status: ratified, ready for implementation in Phase 3.

The base architecture is Design C (feature-modular vertical slices), tightened with Design B's router→service→repository discipline and a few pragmatic concessions from Design A (notably: dedicated `/api/health` mount, `pinia-plugin-persistedstate`, an explicit legacy 308 shim with one-release sunset). Cross-cutting plumbing (config, db, security, markdown, errors) lives in `core/` and `services/`; each domain (cards, auth, covers, tags, health) is a self-contained module on both sides of the stack.

## 1. Locked decisions (recap, verbatim)

The following are locked across all three proposals and carry into the final spec without further debate:

- **Backend stack**: FastAPI ~0.118 + SQLAlchemy 2.0.36 async + Pydantic v2.11 + pydantic-settings + Alembic 1.14 + PyJWT 2.10 + bcrypt 4.x + markdown-it-py 3.x + mdit-py-plugins + linkify-it-py + nh3 0.2 + Pillow 11+ structlog + uvicorn[standard] + gunicorn. SQLite (aiosqlite) for dev; PostgreSQL (asyncpg) is a DSN swap away. uv for dependency + venv management.
- **Frontend stack**: Vue 3.5 + Vite 7 + TypeScript strict + Pinia 3 setup stores + Vue Router 4 + openapi-typescript + openapi-fetch + md-editor-v3 + highlight.js + @vueuse/core + pinia-plugin-persistedstate. pnpm for dependency management. No axios. No DOMPurify on the client (server pre-sanitizes).
- **API surface**: All endpoints under `/api/v1`. `GET /api/health` is also mounted directly (outside `/v1`) so external monitors are version-stable. Legacy `/api/*` (non-`v1`) paths return `308 Permanent Redirect` to the v1 equivalent for exactly one release; the legacy shim logs every hit with path + UA so operators can verify it is unused before removal.
- **Identity model**: `cards.id` is an immutable `uuid4` primary key. `cards.slug` is a regenerable, URL-facing handle that is unique only among non-archived rows (partial unique index). Update/archive/delete address cards by `id`; reads address cards by `slug`. Legacy `cards.json` ids become the initial `slug` values verbatim so existing public URLs keep resolving.
- **Auth**: JWT HS256 only, secret loaded from env, decoder pinned to `algorithms=["HS256"]`, 12-hour TTL (`LG_JWT_TTL_SECONDS=43200`), Bearer in `Authorization` header, no refresh tokens in v1 (re-login on 401), no cookies. `User` table backs auth; admin row seeded by Alembic data migration from `LG_ADMIN_USERNAME`/`LG_ADMIN_PASSWORD` when no users exist (idempotent).
- **Markdown**: Server-side render via markdown-it-py (GFM-like config, `html: false`, linkify, footnotes, tables, task-lists), code fences annotated with `data-language="<lang>"`, sanitized through nh3 with an explicit allowlist, then trusted on the client via `v-html`. Leading `# H1` is stripped before render. Result is persisted as `cards.body_html` and refreshed on every write.
- **Covers**: `POST /api/v1/covers` is multipart, admin-only, accepts `image/png|jpeg|webp` only, max 5 MiB, max 4096×4096 px, MIME confirmed via magic-byte sniff + `Pillow.verify()` then re-open, atomic write (`.tmp` + `os.replace`) to `<static_dir>/covers/<card_id>.<ext>`, old-extension siblings unlinked. nginx `alias /covers/` serves the directory directly in prod.
- **Errors**: Failures use envelope `{ok: false, error: <human>, code: <machine>}`; successes are bare resources (no `{ok: true, data}` wrapping) so OpenAPI types stay clean. `/api/health` and explicit ack endpoints return `{ok: true}`. Stable machine codes are enumerated and never localized.
- **Deployment**: Single host, single systemd unit running `gunicorn -k uvicorn.workers.UvicornWorker -w 2`, `alembic upgrade head` as `ExecStartPre`. nginx terminates TLS, serves SPA from `dist/`, proxies `/api/` to `127.0.0.1:5001`, serves `/covers/` via `alias`. SQLite runs in WAL mode with `foreign_keys=ON` and `busy_timeout=5000` set by a SQLAlchemy `connect` listener.
- **Legacy data preservation**: `data/cards.json` and `content/notes/*.md` are kept as a read-only snapshot (`chmod -R a-w`) after migration. The new backend never writes to either tree.

## 2. Repository layout (top-level)

```
LinkGarden/
├── backend/                # FastAPI app (src layout, uv-managed)
├── frontend/                      # Vue 3 SPA (pnpm-managed)
├── deploy/
│   ├── systemd/linkgarden.service
│   ├── nginx/linkgarden.conf
│   └── env/linkgarden.env.example
├── scripts/
│   ├── deploy.sh                  # build + rsync + restart on the host
│   └── gen-api.sh                 # convenience wrapper around frontend codegen
├── docs/
│   ├── refactor/                  # PROJECT_NOTES, ADRs, migration runbook
│   └── architecture/              # this document + diagrams
├── data/                          # FROZEN legacy snapshot (read-only after migration)
├── content/notes/                 # FROZEN legacy snapshot (read-only after migration)
├── README.md
└── CLAUDE.md
```

The repo is a logical monorepo, not a pnpm workspace — backend and frontend have independent toolchains and CI matrices, so workspace plumbing is not pulling its weight.

## 3. Backend

### 3.1 Directory tree (backend/)

```
backend/
├── pyproject.toml                 # PEP 621; deps pinned per §1; optional [postgres] extra = [asyncpg]
├── uv.lock
├── alembic.ini                # script_location = alembic; URL injected from settings in env.py
├── ruff.toml
├── pyrightconfig.json# strict on src/app, basic on tests
├── .env.example                   # see §3.6 for full key list
├── README.md
├── src/
│   └── app/
│       ├── __init__.py
│       ├── main.py                # create_app() factory, lifespan, exception handlers,
│       │                # mounts /api/health (stable monitor path) + /api/v1
│       │                          # + legacy /api/{path:path} 308 shim
│       ├── asgi.py                # app = create_app(); gunicorn entrypoint
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py          # Settings(BaseSettings); module-level get_settings()
│       │   ├── db.py              # async engine, async_sessionmaker, get_session dep,
│       │   │# MetaData(naming_convention=...), Base(DeclarativeBase)
│       │   ├── pragmas.py         # SQLAlchemy "connect" listener: WAL, FK=ON, busy_timeout
│       │   ├── security.py        # hash_password / verify_password / encode_jwt / decode_jwt
│       │   ├── errors.py          # AppError + subclasses,ErrorEnvelope, register_handlers()
│       │   ├── logging.py         # structlog config with request_id contextvar
│       │   └── types.py           # GUID type for cross-dialect UUID
│       ├── services/
│       │   ├── __init__.py
│       │   └── markdown.py        # render_markdown(md) -> sanitized HTML; pure, no DB
│       ├── features/
│       │   ├── health/
│       │   │   └── routes.py      # GET /health
│       │   ├── auth/
│       │   │   ├── models.py      # User ORM
│       │   │   ├── schemas.py     # LoginRequest, TokenResponse, UserRead
│       │   │   ├── repo.py        # UserRepository
│       │   │   ├── service.py     # authenticate(), mint_token()
│       │   │   ├── deps.py        # current_user, require_admin (DI types)
│       │   │   └── routes.py      # POST /auth/login, GET /auth/me
│       │   ├── cards/
│       │   │   ├── models.py      # Card ORM
│       │   │   ├── schemas.py     # CardCreate, CardUpdate, CardArchive,
│       │   │   │                  # CardListItem, CardRead, CardDetail, CardListQuery
│       │   │   ├── repo.py        # CardRepository
│       │   │   ├── slug.py# slugify(text) + unique_slug(session, base, exclude_id)
│       │   │   ├── service.py     # publish/update/archive/delete orchestration
│       │   │   └── routes.py      # GET /cards, GET /cards/{slug}, POST /cards,
│       │   │                      # PUT /cards/{id}, PATCH /cards/{id}/archive,
│       │   │                      # DELETE /cards/{id}
│       │   ├── covers/
│       │   │   ├── service.py     # validate + atomic write + cards.cover update
│       │   │   ├── schemas.py     # CoverUploadResponse
│       │   │   └── routes.py      # POST /covers
│       │   └── tags/
│       │       ├── repo.py        # distinct sorted tag union
│       │       └── routes.py      # GET /tags
│       └── static/
│           └── covers/            # uploaded files (nginx alias /covers/ in prod)
├── alembic/
│   ├── env.py                # async migrate via connection.run_sync; render_as_batch
│   │# for SQLite; imports app.features.*.models so autogenerate
│   │                              # sees every table
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial.py# users + cards + all indexes
│       └── 0002_seed_admin.py     # data migration: insert admin from LG_ADMIN_* if 0 users
├── scripts/
│   ├── migrate_from_json.py       # one-shot legacy importer (idempotent on slug)
│   └── seed_admin.py# interactive admin creator / rotator
└── tests/
    ├── conftest.py                # in-memory aiosqlite engine, AsyncSession,
    │                              # httpx.AsyncClient(ASGITransport), admin_token fixture
    ├── factories.py
    ├── unit/
    │   ├── test_slug.py
    │   ├── test_markdown.py
    │   └── test_security.py
    ├── integration/
    │   ├── test_health.py
    │   ├── test_auth.py
    │   ├── test_cards.py
    │   ├── test_covers.py
    │   ├── test_tags.py
    │   ├── test_legacy_redirect.py
    │   └── test_openapi_snapshot.py  # snapshots /openapi.json; CI fails on drift
    └── scripts/
        └── test_migrate_from_json.py
```

### 3.2 Module responsibilities (table)

| Module path | Responsibility | depends_on |
|---|---|---|
| `app/main.py` | `create_app()` factory; lifespan (engine dispose on shutdown); `CORSMiddleware` only when `APP_ENV='dev'`; registers exception handlers from `core.errors`; mounts `GET /api/health` directly; mounts `api_v1_router` at `/api/v1`; registers low-priority catch-all `/api/{path:path}` legacy 308 shim that excludes `v1/` and `health`. | `core.config`, `core.db`, `core.errors`, every `features.*.routes` |
| `app/asgi.py` | `app = create_app()` — gunicorn target. | `app.main` |
| `core/config.py` | `Settings(BaseSettings)` singleton: `DATABASE_URL`, `JWT_SECRET`, `JWT_ALG='HS256'` (constant), `JWT_TTL_SECONDS=43200`, `LG_ADMIN_USERNAME`, `LG_ADMIN_PASSWORD`, `STATIC_DIR`, `COVERS_PUBLIC_PREFIX='/covers'`, `ALLOWED_ORIGINS`, `APP_ENV`, `MAX_COVER_BYTES=5_242_880`, `MAX_COVER_DIM=4096`. Read once at import; missing/short `JWT_SECRET` crashes loudly. | pydantic-settings |
| `core/db.py` | `create_async_engine(settings.DATABASE_URL)`, `async_sessionmaker(expire_on_commit=False)`, `get_session()` dep that yields, rollbacks on exception, closes in finally; `Base(DeclarativeBase)` with `MetaData(naming_convention={...})`; `TimestampMixin`. | `core.config`, `core.pragmas` |
| `core/pragmas.py` | SQLAlchemy `'connect'` event listener that runs `PRAGMA journal_mode=WAL; synchronous=NORMAL; foreign_keys=ON; busy_timeout=5000;` when dialect is sqlite. | sqlalchemy |
| `core/security.py` | `hash_password(pw)` / `verify_password(pw, hashed)` wrapping bcrypt directly (truncates to 72 bytes, rejects passwords <8 chars at policy layer not here); `encode_jwt(claims, ttl)` returns HS256 JWT; `decode_jwt(token)` pinned to `algorithms=["HS256"]`, returns claims or raises `Unauthorized`. | bcrypt, pyjwt, `core.config`, `core.errors` |
| `core/errors.py` | `AppError(code, message, http_status)` + subclasses `NotFound`, `Conflict`, `BadRequest`, `Unauthorized`, `Forbidden`, `Unprocessable`, `PayloadTooLarge`, `UnsupportedMediaType`. `ErrorEnvelope` Pydantic model. `register_handlers(app)` installs three handlers: `AppError`→envelope; `HTTPException`→envelope with code derived from status; `RequestValidationError`→`{code:'validation_failed', error:<first>, detail:<errors>}, 422`. All log via structlog with `request_id`, `path`, `method`, `code`. | structlog, fastapi |
| `core/logging.py` | structlog setup with `contextvars.bind_contextvars` middleware; JSON output in prod, console in dev. | structlog |
| `core/types.py` | `GUID` TypeDecorator: stores as `CHAR(36)` on SQLite, `UUID` on PostgreSQL;ensures `Mapped[uuid.UUID]` works on both. | sqlalchemy |
| `services/markdown.py` | Pure `render_markdown(md: str) -> str`. See §3.7. No DB, no I/O. | markdown-it-py, mdit-py-plugins, linkify-it-py, nh3 |
| `features/health/routes.py` | `GET /health` → `{"ok": True}`. Never touches DB. | — |
| `features/auth/models.py` | `User` ORM (see §3.3). | `core.db` |
| `features/auth/schemas.py` | `LoginRequest`, `TokenResponse`, `UserRead`. | pydantic |
| `features/auth/repo.py` | `UserRepository`: `get_by_username`, `get_by_id`, `insert` (seeder use), `count`. | `features.auth.models`, sqlalchemy |
| `features/auth/service.py` | `authenticate(session, username, password) -> User` (raises `Unauthorized('invalid_credentials', 401)` with constant-time message); `mint_token(user) -> TokenResponse`. | `features.auth.repo`, `core.security`, `core.config` |
| `features/auth/deps.py` | `CurrentUser = Annotated[User, Depends(_get_current_user)]`; `AdminUser = Annotated[User, Depends(_require_admin)]`; decodes header, loads user, asserts role. | `core.security`, `features.auth.repo`, `core.db` |
| `features/auth/routes.py` | `POST /auth/login` (body `LoginRequest`); `GET /auth/me` (`CurrentUser`). | `features.auth.service`, `features.auth.deps`, `features.auth.schemas` |
| `features/cards/models.py` | `Card` ORM (see §3.3). | `core.db`, `core.types` |
| `features/cards/schemas.py` | All Card schemas (see §3.4). | pydantic |
| `features/cards/slug.py` | `slugify(text) -> str` (CJK-safe; lowercase ASCII; whitespace→`-`; keep `[a-z0-9\-一-鿿]`; fallback `article-<short_uuid>`); `unique_slug(session, base, exclude_id=None) -> str` that walks `-2/-3/...` against non-archived rows. | sqlalchemy, `features.cards.models` |
| `features/cards/repo.py` | `CardRepository`: `list(filters)`, `get_by_slug(slug)`, `get_by_id(id)`, `slug_exists(base, exclude_id)`, `insert(card)`, `update(card)`, `delete(card)`. All SQL lives here; no SQL anywhere else. | `features.cards.models`, sqlalchemy |
| `features/cards/service.py` | Business logic only — no SQL. `list_cards(filters)`, `get_card_detail(slug)`, `publish(payload, author)`, `update(card_id, payload)`, `set_archive(card_id, archived)`, `delete(card_id)`. Mints UUID, derives slug, enforces `category↔(url\|body)` coupling on the resulting state, calls `services.markdown.render_markdown`, writes `body_html` on every mutation, unlinks cover file on delete when cover URL starts with `COVERS_PUBLIC_PREFIX`. After every write, re-`SELECT` and return the fresh row (avoids `expire_on_commit=False` staleness). | `features.cards.repo`, `features.cards.slug`, `services.markdown`, `core.errors`, `core.config` |
| `features/cards/routes.py` | Six card endpoints (see §3.5). Routers stay ≤30 LOC each; no SQL, no business logic. Mutating endpoints take `AdminUser` dep. | `features.cards.service`, `features.auth.deps`, `features.cards.schemas` |
| `features/covers/service.py` | `upload_cover(file, card_id, session) -> CoverUploadResponse`. Validates MIME, size, magic bytes, Pillow `verify()` + re-open for dims, computes ext from sniffed type (not filename), atomic write tmp+`os.replace`, unlinks old-ext siblings, updates `cards.cover` in same transaction. | Pillow, `core.config`, `core.errors`, `features.cards.repo` |
| `features/covers/schemas.py` | `CoverUploadResponse(ok, url, width, height, bytes, card: CardRead)`. | pydantic |
| `features/covers/routes.py` | `POST /covers` (multipart `file: UploadFile`, `card_id: UUID = Form(...)`). | `features.covers.service`, `features.auth.deps` |
| `features/tags/repo.py` | `list_distinct_tags(session, include_archived=False) -> list[str]` (case-insensitive dedupe, sorted). | `features.cards.models`, sqlalchemy |
| `features/tags/routes.py` | `GET /tags?include_archived=`. | `features.tags.repo` |
| `scripts/migrate_from_json.py` | One-shot importer (see §5). | `features.cards.repo`, `features.auth.repo`, `services.markdown` |
| `scripts/seed_admin.py` | Interactive admin creator/rotator using `getpass`. | `core.security`, `features.auth.repo` |

### 3.3 SQLAlchemy schema

#### Table `users`

| Column | Type | Constraints |
|---|---|---|
| `id` | `Mapped[uuid.UUID]` via `GUID` | PK, default `uuid4` |
| `username` | `Mapped[str]` `String(64)` | not null |
| `password_hash` | `Mapped[str]` `String(255)` | not null |
| `role` | `Mapped[str]` `String(16)` | not null, default `'admin'` |
| `created_at` | `Mapped[datetime]` `DateTime(timezone=True)` | not null, `server_default=func.now()` |
| `updated_at` | `Mapped[datetime]` `DateTime(timezone=True)` | not null, `server_default=func.now()`, `onupdate=func.now()` |

Indexes:
- `uq_users_username` UNIQUE (`username`).

Relationships: none in v1 (cards are tenant-global; a `User.cards` back-populated relation can be added without migration if/when authorship becomes meaningful).

#### Table `cards`

| Column | Type | Constraints |
|---|---|---|
| `id` | `Mapped[uuid.UUID]` via `GUID` | PK, default `uuid4` |
| `slug` | `Mapped[str]` `String(200)` | not null |
| `title` | `Mapped[str]` `String(255)` | not null |
| `category` | `Mapped[str]` `String(16)` | not null; `CHECK (category IN ('external','local'))` |
| `group` | `Mapped[str \| None]` `String(32)` | nullable; validated at schema (`'技术类'\|'随笔类'\|'生活类'`); no DB enum to keep extension cheap |
| `summary` | `Mapped[str]` `Text` | not null, default `''` |
| `cover` | `Mapped[str \| None]` `String(512)` | nullable |
| `url` | `Mapped[str \| None]` `String(2048)` | nullable; required when `category='external'` (service-enforced) |
| `body` | `Mapped[str \| None]` `Text` | nullable; required when `category='local'` (service-enforced) |
| `body_html` | `Mapped[str \| None]` `Text` | server-rendered cache; written on every mutation that touches `body` or `category` |
| `tags` | `Mapped[list[str]]` `JSON` | not null, default `list`; validated/normalized at schema |
| `archived` | `Mapped[bool]` | not null, default `False` |
| `created_at` | `Mapped[datetime]` `DateTime(timezone=True)` | not null, `server_default=func.now()` |
| `updated_at` | `Mapped[datetime]` `DateTime(timezone=True)` | not null, `server_default=func.now()`, `onupdate=func.now()` |

Indexes:
- `ix_cards_slug_active` UNIQUE (`slug`) WHERE `archived = false` (partial unique; supported by SQLite ≥3.8 via `sqlite_where=` and by PostgreSQL natively).
- `ix_cards_archived_created_at` (`archived`, `created_at DESC`) — default list query path.
- `ix_cards_category` (`category`).
- `ix_cards_group` (`group`).
- `ck_cards_category` CHECK constraint above.

Relationships: none in v1.

Rationale for keeping `tags` as JSON instead of a `card_tags` join table (C's proposal): the entire workload is a single-admin blog, tag cardinality is in the dozens, and the only tag query (`SELECT DISTINCT`) is trivial over JSON via dialect-specific helpers wrapped in `tags/repo.py`. Adding a relational tags table would force a join on every card read for no observed benefit.

### 3.4 Pydantic schemas

All schemas use `ConfigDict(from_attributes=True, str_strip_whitespace=True, extra='forbid')`. Tag validation is centralized in a `tag_list_validator`: trim each entry, drop empty, case-insensitive dedupe, max 16, each ≤32 chars.

| Resource | Read | Write | Admin | Notes |
|---|---|---|---|---|
| Card | `CardListItem` (`id, slug, title, category, group, summary, tags, cover, archived, created_at`), `CardRead` (`CardListItem` + `url, updated_at`), `CardDetail` (`CardRead` + `body, body_html` populated only when `category='local'`) | `CardCreate` (`title, category, group?, summary='', tags=[], cover?, url?, body?, slug?` with `@model_validator(mode='after')` enforcing the `external⇒url` / `local⇒body` coupling), `CardUpdate` (every field `Optional`; uses `model_dump(exclude_unset=True)` semantics so omitted fields are preserved — fixes the legacy "PUT silently wipes summary/cover" bug; cross-field coupling re-checked against the merged result), `CardArchive` (`archived: bool` — required, no default) | `CardAdminRead` reserved for v2 (would add `author_id`, `updated_by` when authorship matters); not implemented in v1 | `CardListQuery` (`category?, group?, tag?, q?, include_archived: bool=False`) bound via `Query(...)` |
| User | `UserRead` (`id, username, role, created_at`) | none (no self-registration in v1; `UserCreate` is internal to the seeder script and not exposed) | — | |
| Auth | `TokenResponse` (`access_token, token_type='bearer', expires_in, user: UserRead`) | `LoginRequest` (`username: str min_length=1 max_length=64`, `password: str min_length=1 max_length=256`) | — | |
| Tag | `list[str]` (no envelope) | — | — | |
| Cover | `CoverUploadResponse` (`ok: Literal[True]=True, url, width, height, bytes, card: CardRead`) | multipart, validated at the endpoint | — | |
| Common | `ErrorEnvelope` (`ok: Literal[False]=False, error: str, code: str, detail: list[dict] \| None = None`), `OkResponse` (`ok: Literal[True]=True`) | — | — | |

`CardCategory = Literal['external','local']` and `CardGroup = Literal['技术类','随笔类','生活类']` are exported as type aliases from `features/cards/schemas.py`; switching to an enum table is deferred until a real need surfaces.

### 3.5 API v1 contract

All paths under `/api/v1`. Auth column: `none` = public, `bearer` = any authenticated user, `admin` = role check. `GET /api/health` is a stable mirror of `GET /api/v1/health` mounted directly on the app root.

| Method | Path | Auth | Request | 2xx | 4xx | Notes |
|---|---|---|---|---|---|---|
| GET | `/api/health` | none | — | `200 {"ok": true}` | — | Stable monitor path; never bumps with v1→v2. |
| GET | `/api/v1/health` | none | — | `200 {"ok": true}` | — | Mirror under `/v1`. Never touches DB. |
| POST | `/api/v1/auth/login` | none | `LoginRequest` | `200 TokenResponse` (`expires_in=43200`) | `401 {code:'invalid_credentials'}`, `422 {code:'validation_failed'}` | Constant-time bcrypt compare; identical 401 message for missing-user vs bad-password. Rate-limited at nginx (`limit_req_zone` 10r/min/IP on this path). |
| GET | `/api/v1/auth/me` | bearer | — | `200 UserRead` | `401 {code:'unauthenticated'}` | Used on app boot to validate the persisted token. |
| GET | `/api/v1/cards` | none | query `CardListQuery` | `200 list[CardListItem]` | `422 {code:'validation_failed'}` | Default excludes archived. Sort `created_at DESC, id DESC`. `q` is case-insensitive substring across `title \|\| summary \|\| tags`. `tag` is case-insensitive exact match against any tags element. |
| GET | `/api/v1/cards/{slug}` | none | path `slug: str` | `200 CardDetail` (`body`+`body_html` only when `category='local'`) | `404 {code:'card_not_found'}` | Lookup by `slug`. Archived cards return 404 to anonymous callers; admin token returns the row with `archived: true`. |
| POST | `/api/v1/cards` | admin | `CardCreate` | `201 CardDetail` | `400 {code:'missing_url'\|'missing_body'\|'invalid_category'}`, `409 {code:'slug_conflict'}`, `422`, `401`, `403` | Server mints UUID, derives slug from `slug` field or `title`, auto-suffix `-2/-3/...` on collision among non-archived. Renders `body_html` for local cards. |
| PUT | `/api/v1/cards/{id}` | admin | path `id: UUID`, body `CardUpdate` | `200 CardDetail` | `404 {code:'card_not_found'}`, `400 {code:'invalid_category'}`, `409 {code:'slug_conflict'}`, `422`, `401`, `403` | Only present fields applied. Category switch wipes the stale field (`url` ↔ `body`) and re-renders `body_html`. Slug is **regenerable**: if `slug` is present in the payload, validate uniqueness; otherwise the existing slug is preserved. |
| PATCH | `/api/v1/cards/{id}/archive` | admin | path `id: UUID`, body `CardArchive` | `200 CardRead` | `404`, `422`, `401`, `403` | Setter; body required (fixes legacy "empty body archives" surprise). Partial unique index permits a re-published slug to coexist with an archived twin. |
| DELETE | `/api/v1/cards/{id}` | admin | path `id: UUID` | `204 No Content` | `404`, `401`, `403` | Hard delete; unlinks cover file when cover URL starts with `COVERS_PUBLIC_PREFIX`. UI keeps the button hidden by default. |
| GET | `/api/v1/tags` | none | query `include_archived?: bool` | `200 list[str]` | — | Distinct, sorted, case-insensitive dedupe. Default excludes archived (fixes the legacy bug where tags leaked from archived cards). |
| POST | `/api/v1/covers` | admin | multipart `file: UploadFile`, `card_id: UUID = Form(...)` | `201 CoverUploadResponse` | `400 {code:'invalid_image'}`, `404 {code:'card_not_found'}`, `413 {code:'cover_too_large'}`, `415 {code:'cover_bad_type'}`, `401`, `403` | See §3.8. Updates `cards.cover` atomically and returns the updated `CardRead`. |
| ANY | `/api/{path:path}` (legacy) | passthrough | any | `308 Permanent Redirect` to `/api/v1/{path}` | — | Catch-all registered last in `main.py`; excludes paths starting with `v1/` or equal to `health`. Logs `legacy_api_hit` at WARN with original path + UA. Removal date documented in CHANGELOG (one release after frontend cutover). |

### 3.6 Auth flow

**Login.** Client POSTs `{username, password}` to `/api/v1/auth/login`. `features/auth/service.authenticate(session, u, p)` calls `UserRepository.get_by_username`, then `verify_password(p, user.password_hash)` (`bcrypt.checkpw(p.encode()[:72], user.password_hash.encode())`). On mismatch (or missing user), raises `Unauthorized('invalid_credentials', 401)` with an identical message in both branches. On success, `mint_token(user)` calls `encode_jwt({'sub': str(user.id), 'username': user.username, 'role': user.role, 'iat': <now>, 'exp': <now + 43200>},ttl=43200)` and returns `TokenResponse{access_token, token_type:'bearer', expires_in:43200, user: UserRead.model_validate(user)}`.

**Storage.** Client stores `access_token` + `user` in the Pinia `auth` store, which uses `pinia-plugin-persistedstate` to mirror those two fields to `localStorage` under the key `lg_auth`. Every subsequent API call adds `Authorization: Bearer <token>` via the `openapi-fetch` middleware.

**Guards.** `features/auth/deps.py` exposes two type aliases used directly in router signatures:

```python
CurrentUser = Annotated[User, Depends(_get_current_user)]
AdminUser= Annotated[User, Depends(_require_admin)]
```

`_get_current_user` reads the `Authorization` header, validates the `Bearer` prefix, calls `decode_jwt(token)` (pinned to `algorithms=['HS256']`; the `none` algorithm is never accepted), loads the user via `UserRepository.get_by_id(claims['sub'])`, and raises `Unauthorized('unauthenticated', 401)` on any failure (missing header, bad prefix, signature mismatch, expired token, missing user). `_require_admin` composes `_get_current_user` and asserts `user.role == 'admin'`, raising `Forbidden('forbidden', 403)` otherwise.

**Refresh.** No refresh token in v1. On any `401` response, the openapi-fetch middleware clears the auth store and — only if the current route's `meta.requiresAdmin === true` — pushes to `/admin/login?next=<current>`.

**Seeding.** Alembic revision `0002_seed_admin.py` (data migration) imports `core.config.get_settings` and `core.security.hash_password` inside `upgrade()` (never at module scope), and runs `op.bulk_insert` with a single row when `op.get_bind().execute(text('SELECT COUNT(*) FROM users')).scalar_one() == 0`. `LG_ADMIN_PASSWORD` is required to be ≥8 chars; the migration aborts loudly otherwise. `scripts/seed_admin.py` is the rotation tool: reads username + new password via `getpass()` (TTY only), updates `password_hash` in place.

**`.env` keys** (see `backend/.env.example`):

```
DATABASE_URL=sqlite+aiosqlite:///./linkgarden.db
JWT_SECRET=<openssl rand -hex 32>
JWT_TTL_SECONDS=43200
LG_ADMIN_USERNAME=admin
LG_ADMIN_PASSWORD=<≥8 chars>
STATIC_DIR=./src/app/static
COVERS_PUBLIC_PREFIX=/covers
ALLOWED_ORIGINS=http://localhost:5173
APP_ENV=dev
MAX_COVER_BYTES=5242880
MAX_COVER_DIM=4096
```

### 3.7 Markdown render+sanitize pipeline

`services/markdown.py` exposes one pure function:

```python
def render_markdown(md: str) -> str: ...
```

Pipeline steps, in order:

1. **H1 strip.** Remove a single leading `# H1` line via regex `^# .*\n+` (preserves PROJECT_NOTES rule that the title is owned by the card row, not the body).
2. **Parse.** `MarkdownIt('gfm-like', {'linkify': True, 'html': False, 'breaks': False, 'typographer': False})`. `html=False` ensures inline HTML in source is escaped (defense in depth — nh3 is the second wall). Plugins enabled: `mdit_py_plugins.footnote`, `mdit_py_plugins.deflist`, `mdit_py_plugins.tasklists`. Tables and fenced code are built-in.
3. **Code-fence annotation.** Walk the token stream; for every `fence` token, set `attrSet('data-language', info.split()[0].lower() or 'plaintext')` and add the class `hljs language-<lang>` to the inner `<code>` so the frontend can hand it directly to highlight.js without re-parsing.
4. **Render** to HTML via `md.render()`.
5. **Sanitize.** `nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, url_schemes={'http','https','mailto'}, link_rel='noopener noreferrer nofollow')`. The allowlist is enumerated in module scope:
   - `ALLOWED_TAGS = {'p','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote','pre','code','a','img','table','thead','tbody','tr','th','td','hr','em','strong','del','br','span','sup','sub','div','input'}`
   - `ALLOWED_ATTRS = {'a': {'href','title','rel','target'}, 'img': {'src','alt','title','loading'}, 'code': {'class','data-language'}, 'pre': {'class','data-language'}, 'span': {'class'}, 'div': {'class'}, 'th': {'align','scope'}, 'td': {'align'}, 'input': {'type','checked','disabled'}}`
   - `a` gets `target="_blank"` rewritten via an `AttributeFilter`; the explicit `link_rel` ensures `noopener noreferrer nofollow` is appended.
6. **Return** the sanitized HTML.

**Caching.** The result is stored in `cards.body_html` on every `publish` and on every `update` that touches `body` or `category` (the service layer re-renders unconditionally on those paths to keep the cache trivially correct). Reads serve the cached HTML directly — no `lru_cache` in the read path, no rendering on hot GETs. A naive runtime cache (A's `lru_cache` proposal) is rejected because column-level persistence is debuggable from `sqlite3`, re-renderable via an Alembic data migration when the allowlist changes, and removes a coordination gotcha around `updated_at`.

**Tests** (`tests/unit/test_markdown.py`) pin: headings, inline code, fenced code with language tag, tables, blockquote, links (http/https/mailto only — `javascript:` href dropped), images, footnotes, task-lists, and a hostile XSS corpus (`<script>`, `on*=` handlers, `javascript:` URLs, `<iframe>`, `<object>`, SVG with embedded script).

### 3.8 Cover upload pipeline

Endpoint: `POST /api/v1/covers`, `multipart/form-data` parts `file: UploadFile`, `card_id: UUID = Form(...)`.

`features/covers/service.upload_cover(file, card_id, session)`:

1. **Resolve card.** `CardRepository.get_by_id(card_id)` → `404 card_not_found` if absent.
2. **MIME by header.** Reject `file.content_type ∉ {'image/png','image/jpeg','image/webp'}` → `415 cover_bad_type`.
3. **Stream + size.** Read the upload into a `SpooledTemporaryFile`, aborting early at `MAX_COVER_BYTES = 5 MiB` → `413 cover_too_large`.
4. **Magic bytes + Pillow verify.** Sniff first 12 bytes against PNG/JPEG/WebP signatures; reject mismatch → `400 invalid_image`. `Pillow.Image.open(stream).verify()` destroys parser state, so re-open with `Image.open` to read dimensions.
5. **Dimensions.** Reject `width < 200` or `height < 200` or `width > MAX_COVER_DIM` or `height > MAX_COVER_DIM` → `400 invalid_image`.
6. **Extension.** Derive ext from the sniffed type (`png|jpg|webp`), never from `file.filename`.
7. **Atomic write.** Write bytes to `<STATIC_DIR>/covers/<card_id>.<ext>.tmp`, then `os.replace` to the final path. Before replace, unlink any sibling files with the same `<card_id>.*` but a different extension. Defensive `pathlib` join asserts the resolved path is inside `<STATIC_DIR>/covers/`.
8. **DB update.** Within the same `AsyncSession`, set `card.cover = f'{COVERS_PUBLIC_PREFIX}/{card_id}.{ext}?v={int(now)}'` (the `?v=…` cache-buster is the only place we touch the URL — nginx caches with `Cache-Control: public, immutable` so a fresh query string is required).
9. **Response.** `CoverUploadResponse{ok: True, url, width, height, bytes, card: CardRead.model_validate(card)}`.

Static serving: in dev FastAPI mounts `StaticFiles(directory=settings.STATIC_DIR)` at `/static` for fallback, and the covers prefix is `app.mount('/covers', StaticFiles(directory=settings.STATIC_DIR / 'covers'))` so URLs work identically with the dev server. In prod nginx `alias /covers/` overrides the proxy.

### 3.9 Error envelope + exception handlers

**Envelope.** Failure responses are exactly:

```json
{"ok": false, "error": "<human-readable>", "code": "<machine-readable>", "detail": <optional>}
```

Success bodies are the bare resource (`CardRead`, `CardDetail`, `TokenResponse`, `list[CardListItem]`, …) so OpenAPI components stay clean and openapi-typescript produces direct types instead of envelope unwrappers. The only success bodies that include `ok: true` are `/health` and `CoverUploadResponse`.

**Stable machine codes** (frozen — frontend branches on these and they are never localized):

```
validation_failed   missing_url         missing_body       invalid_category
invalid_payload     card_not_found      slug_conflict      tag_too_long
invalid_credentials unauthenticated     forbidden          invalid_image
cover_too_large     cover_bad_type      cover_dim_invalid  http_400 http_404 http_405 http_500
internal_error
```

**Handlers** (registered by `core.errors.register_handlers(app)`):

1. `AppError` → `JSONResponse(status_code=exc.http_status, content={'ok': False, 'error': exc.message, 'code': exc.code})`.
2. `StarletteHTTPException` → same envelope; `code` is `detail.code` when `detail` is a structured dict, else `f'http_{status_code}'`.
3. `RequestValidationError` → `code='validation_failed'`, `error` is the first error rendered as `<loc>: <msg>`, `detail` is the full Pydantic error list for clients that want it.
4. Catch-all `Exception` → `500 internal_error`; the exception is logged atERROR with `request_id`, `path`, `method`, and a redacted stack.

Every handler emits a structlog event so on-call has a per-request trail without needing tracebacks.

## 4. Frontend

### 4.1 Directory tree (frontend/)

```
frontend/
├── index.html                    # title 'Link Garden'; mounts /src/main.ts as module
├── vite.config.ts                # @vitejs/plugin-vue; server.proxy['/api'] -> 127.0.0.1:5001;
│                                 # server.port 5173; vite-plugin-checker (vue-tsc + eslint);
│                                 # build.outDir 'dist'; manualChunks splits highlight.js + md-editor-v3
├── tsconfig.json                 # references app/node/vitest
├── tsconfig.app.json             # moduleResolution:'Bundler', strict: true
├── tsconfig.node.json
├── tsconfig.vitest.json
├── eslint.config.ts              # ESLint 9 flat; typescript-eslint v8; eslint-plugin-vue v10;
│                                 # ignores src/shared/api/schema.d.ts
├── .prettierrc
├── .nvmrc# 22(LTS)
├── package.json                  # engines.node>=20.19; pnpm.overrides pins single highlight.js
├── pnpm-lock.yaml
├── openapi/
│   └── schema.json               # committed snapshot of /api/v1/openapi.json
├── public/
│   ├── favicon.svg
│   └── images/avatar.jpg
├── scripts/
│   └── gen-api.ts                # tsx scripts/gen-api.ts: fetches /openapi.json (or reads
│                                 # openapi/schema.json) and runs openapi-typescript -> schema.d.ts
└── src/
    ├── main.ts                   # createApp(App).use(pinia.use(piniaPluginPersistedstate))
    │                             #.use(router).mount('#app')
    ├── App.vue                   # <component :is="currentLayout"><router-view/></component>
    ├── router/
    │   ├── index.ts              # createRouter({history: createWebHistory()})
    │   ├── routes.ts             # route table aggregated from each feature
    │   └── guards.ts             # setTitle, requireAdmin, redirectIfAuthed
    ├── layouts/
    │   ├── PublicLayout.vue      # hero + nav chrome
    │   ├── AdminLayout.vue       # admin sidebar + topbar + 回到前台 chip
    │   └── BlankLayout.vue       # bare slot for /admin/login and /404
    ├── stores/
    │   └── ui.ts                 # cross-feature UI store (keyword, theme, toasts)
    ├── shared/
    │   ├── api/
    │   │   ├── client.ts         # createClient<paths>({baseUrl:'/api/v1'}) with middleware
    │   │   ├── interceptors.ts   # attach Authorization; normalize !ok -> AppError;
    │   │   │                # emit 'auth:invalidated' on 401
    │   │   ├── errors.ts         # class AppError; mapError(envelope) -> AppError
    │   │   └── schema.d.ts       # GENERATED; ESLint excluded
    │   ├── composables/
    │   │   ├── useAsync.ts       # {data, error, loading, run, reset}
    │   │   ├── useDebounce.ts    # @vueuse-flavored, 200ms default
    │   │   ├── useToast.ts       # thin facade over stores/ui
    │   │   └── useEnhanceCodeBlocks.ts
    │   ├── ui/
    │   │   ├── BaseButton.vue
    │   │   ├── BaseInput.vue
    │   │   ├── BaseTextarea.vue
    │   │   ├── BaseSelect.vue
    │   │   ├── BaseTagInput.vue
    │   │   ├── BaseModal.vue
    │   │   ├── BaseToast.vue
    │   │   ├── AppSpinner.vue
    │   │   └── NotFoundView.vue
    │   ├── utils/
    │   │   ├── slug.ts           # client-side display preview (server is source of truth)
    │   │   ├── date.ts           # formatDate(iso, locale)
    │   │   ├── bytes.ts
    │   │   └── invariant.ts
    │   └── types/
    │       ├── env.d.ts
    │       ├── shims-vue.d.ts
    │       └── domain.ts         # re-exports paths/components from shared/api/schema.d.ts
    ├── features/
    │   ├── cards/
    │   │   ├── api.ts            # typed wrappers: listCards, getCard, publish, update,
    │   │   │                     # archive, remove
    │   │   ├── store.ts          # useCardsStore (setup, persisted: filters)
    │   │   ├── views/
    │   │   │   ├── HomeView.vue
    │   │   │   ├── CardDetailView.vue
    │   │   │   ├── AdminCardsView.vue
    │   │   │   └── AdminPublishView.vue
    │   │   ├── components/
    │   │   │   ├── CardGrid.vue
    │   │   │   ├── CardItem.vue
    │   │   │   ├── CardCover.vue       # url-encoded background-image, fallback gradient
    │   │   │   ├── CardFilters.vue     # bound to useCardsStore.filters
    │   │   │   ├── ArticleBody.vue     # v-html + useEnhanceCodeBlocks(rootRef)
    │   │   │   ├── ArticleHero.vue
    │   │   │   ├── HeroBanner.vue
    │   │   │   ├── PublishForm.vue     # md-editor-v3 + 附加信息 region; no right-side preview
    │   │   │   └── AdminCardTable.vue
    │   │   └── composables/
    │   │       ├── useCardForm.ts
    │   │       └── useFilters.ts       # binds query-string params to store.filters
    │   ├── auth/
    │   │   ├── api.ts                # login, me
    │   │   ├── store.ts                # useAuthStore (persisted: token, user)
    │   │   ├── views/LoginView.vue
    │   │   ├── components/LoginForm.vue
    │   │   └── composables/useAuthGuard.ts
    │   ├── covers/
    │   │   ├── api.ts                  # uploadCover(file, cardId)
    │   │   ├── components/CoverUploader.vue
    │   │   └── composables/useCoverUpload.ts
    │   └── tags/
    │       ├── api.ts                  # listTags(includeArchived)
    │       ├── store.ts                # useTagsStore
    │       └── components/TagCloud.vue
    ├── assets/
    │   └── styles/
    │       ├── tokens.css# :root variables (colors, spacing)
    │       ├── reset.css
    │       ├── global.css
    │       ├── article.css             # .article-prose, .markdown-body, .code-card
    │       ├── home.css
    │       ├── admin.css
    │       └── hljs-theme.css
    └── tests/
        ├── setup.ts                    # @vue/test-utils stubs, MSW handlers using generated types
        └── unit/
            ├── stores.spec.ts
            ├── components.spec.ts
            └── views.spec.ts
```

### 4.2 API client (openapi-typescript codegen workflow)

`pnpm gen:api` runs `scripts/gen-api.ts`, which:

1. Tries to fetch `http://127.0.0.1:5001/api/v1/openapi.json`. If unreachable, falls back to the committed `openapi/schema.json` (also fetched by CI from the backend test snapshot — see `backend/tests/integration/test_openapi_snapshot.py`).
2. Writes `openapi/schema.json` (pretty-printed, deterministic ordering).
3. Pipes that JSON through `openapi-typescript` and writes `src/shared/api/schema.d.ts`.

CI step: `pnpm gen:api && git diff --exit-code openapi/schema.json src/shared/api/schema.d.ts`. A red diff means the developer forgot to regenerate after a backend change. The corresponding backend test snapshots `/openapi.json` as a fixture so the contract drift is caught from both sides.

`shared/api/client.ts`:

```ts
import createClient from 'openapi-fetch'
import type { paths } from './schema'

export const api = createClient<paths>({ baseUrl: '/api/v1' })

api.use({
  onRequest({ request }) {
    const token = useAuthStore().token
    if (token) request.headers.set('Authorization', `Bearer ${token}`)
    return request
  },
  onResponse({ response }) {
    if (!response.ok) {
      // delegate to interceptors.ts: parse envelope, throw AppError,
      // dispatch 'auth:invalidated' on 401}
    return response
  },
})
```

Per-feature wrappers (`features/cards/api.ts`, `features/auth/api.ts`, …) re-export thin functions that call `api.GET('/cards', {...})` etc. with parameter type inference flowing from `schema.d.ts`. Views never call `api` directly — they call the per-feature wrapper, which gives a single place to attach feature-specific normalization or test mocks.

### 4.3 Pinia stores

All stores are setup stores. `auth` and `ui` use `pinia-plugin-persistedstate`; `cards` and `tags` are in-memory (the list is cheap to refetch, and persisted filters confuse users more than they help).

| Store | State | Actions | Persisted |
|---|---|---|---|
| `useAuthStore` (`features/auth/store.ts`) | `token: Ref<string \| null>`, `user: Ref<UserRead \| null>`, `status: Ref<'idle'\|'loading'\|'authed'\|'error'>`; `isAuthenticated = computed(() => !!token.value)`; `isAdmin = computed(() => user.value?.role === 'admin')` | `login(username, password)`, `logout()`, `fetchMe()` (called on app boot if token exists; on 401 clears state), `$reset()` (hand-rolled — Pinia 3 setup stores have no auto-reset; called from `logout()`) | `token`, `user` (localStorage key `lg_auth`) |
| `useCardsStore` (`features/cards/store.ts`) | `list: Ref<CardListItem[]>`, `byId: Map<string, CardDetail>`, `tags: Ref<string[]>`, `filters: Reactive<{category:null, group:null, tag:null, q:'', includeArchived:false}>`, `loading: Ref<boolean>`, `error: Ref<AppError \| null>` | `fetchList()`, `fetchDetail(slug)`, `fetchTags()`, `create(payload)`, `update(id, payload)` (mutates list/detail in place — fixes legacy full-reload bug), `archive(id, archived)`, `remove(id)`, `setFilter(patch)`, `$reset()` | none |
| `useTagsStore` (`features/tags/store.ts`) | `tags: Ref<string[]>`, `loading: Ref<boolean>` | `fetch(includeArchived?)`, `$reset()` | none |
| `useUiStore` (`stores/ui.ts`) | `keyword: Ref<string>` (debounced 200ms before mirroring into `cards.filters.q`), `theme: Ref<'dark'\|'light'>`, `toasts: Ref<Toast[]>`, `modal: Ref<ModalState \| null>`, `sidebarCollapsed: Ref<boolean>` | `setKeyword(v)`, `toggleTheme()`, `pushToast(t)`, `dismissToast(id)`, `openModal(s)`, `closeModal()`, `$reset()` | `theme`, `sidebarCollapsed` |

`interceptors.ts` dispatches a window event `'auth:invalidated'` on every 401. `useAuthStore` listens to that event in `onMounted` of the root `App.vue` (one-time wiring) and calls `logout()` + conditional `router.push('/admin/login?next=...')`. This avoids importing the router into the API client and keeps the dependency graph acyclic.

### 4.4 Routes + guards

`router/routes.ts` aggregates per-feature route arrays; `router/index.ts` registers a single global `beforeEach` that runs `setTitle`, then `requireAdmin` (when `to.meta.requiresAdmin`), then `redirectIfAuthed` (when `to.meta.anonOnly`).

| Path | Name | Component | Meta | Guard |
|---|---|---|---|---|
| `/` | `home` | `features/cards/views/HomeView.vue` | `{title: 'Link Garden — 是个人博客，也是技术收藏展厅', layout: 'public'}` | none |
| `/card/:slug` | `card-detail` | `features/cards/views/CardDetailView.vue` | `{title: 'Article · Link Garden', layout: 'public'}` | none — view handles 404 by routing to `NotFoundView` |
| `/admin/login` | `admin-login` | `features/auth/views/LoginView.vue` | `{title: '登录 · Link Garden', layout: 'blank', anonOnly: true}` | `redirectIfAuthed` → `/admin` when token is valid |
| `/admin` | `admin-cards` | `features/cards/views/AdminCardsView.vue` | `{title: '后台 · 文章管理', layout: 'admin', requiresAdmin: true}` | `requireAdmin` (if `useAuthStore.token` exists but `user` doesn't, calls `fetchMe()` once before redirecting) |
| `/admin/publish` | `admin-publish` | `features/cards/views/AdminPublishView.vue` | `{title: '后台 · 编辑/新增', layout: 'admin', requiresAdmin: true}` | `requireAdmin` |
| `/admin/publish/:id` | `admin-edit` | `features/cards/views/AdminPublishView.vue` | `{title: '后台 · 编辑', layout: 'admin', requiresAdmin: true}` | `requireAdmin` + pre-fetch |
| `/:pathMatch(.*)*` | `not-found` | `shared/ui/NotFoundView.vue` | `{title: '404 · Link Garden', layout: 'blank'}` | none |

`requireAdmin` pushes `'/admin/login?next=<encodeURIComponent(to.fullPath)>'` on miss. `LoginView` reads `?next=` after login and `router.replace(next || '/admin')`.

### 4.5 Shared composables

- `useAsync<T>(fn)` — `{ data, error, loading, run, reset }` so views and widgets share loading semantics without duplicating try/finally. No vue-query dependency.
- `useDebounce(ref, delayMs=200)` — drives the search input and any rapid-fire filter changes before mirroring into the store.
- `useEnhanceCodeBlocks(rootRef)` — `onMounted` and `watch(rootRef)`, walks `pre[data-language]:not([data-hl-done])` and runs `hljs.highlightElement` on each `<code>`, setting `data-hl-done="1"` so the pass is idempotent (kills the legacy double-wrap bug).
- `useToast()` — thin facade over `useUiStore.pushToast` that converts an `AppError` into a friendly toast title.
- `useCardForm(initial?)` — encapsulates publish/edit: zod-light validation (using the generated `CardCreate`/`CardUpdate` types via `valibot` or a hand-rolled checker — TBD in Phase 3, but the *interface* is locked: `{form, errors, dirty, submit, reset}`), dirty tracking, category-switch handling, and a `submit()` that picks `create` vs `update` based on `id` presence.
- `useCoverUpload(cardId)` — drives `CoverUploader.vue`; previews via `URL.createObjectURL` then revokes; calls `covers.api.uploadCover`; returns the new URL string.
- `useFilters()` — binds query-string params (`category`, `group`, `tag`, `q`) to `useCardsStore.filters` so deep links survive reloads; debounces `q` updates back to the URL.
- `useAuthGuard()` — composable form of the route guard for components that need to gate UI fragments (e.g., admin-only edit pill on a public card).
- `utils/slug.ts` — display-only slug preview (the server is the source of truth on POST).
- `utils/invariant(cond, msg)` — typescript narrowing helper for asserted branches.

### 4.6 Reusable components

- `shared/ui/Base*` — primitives. `BaseInput`, `BaseTextarea`, `BaseSelect`, `BaseTagInput` (chip input with dedupe/cap), `BaseButton`, `BaseModal`, `BaseToast`, `AppSpinner`. All accessibility-typed; emit `update:modelValue`.
- `features/cards/components/CardGrid.vue` — pure list; props `items: CardListItem[]`, `mode: 'public' | 'admin'`; emits `select`, `archive`, `edit`, `delete`. No data fetching.
- `features/cards/components/CardItem.vue` — single tile. Owns the hover rule (image scales + shadow grows, card itself does not translate — matches PROJECT_NOTES). Slot for trailing actions; admin mode renders `下架 / 编辑`.
- `features/cards/components/CardCover.vue` — handles `cover` + fallback gradient; CSS `background-image: url("...")` with the URL passed through `CSS.escape` to defeat the legacy escaping bug. Replaces the four ad-hoc cover blocks in the current codebase.
- `features/cards/components/ArticleBody.vue` — `<article class="article-prose markdown-body" v-html="html" ref="root">`; runs `useEnhanceCodeBlocks(root)`. Trusts the server's pre-sanitized HTML; no DOMPurify import.
- `features/cards/components/CardFilters.vue` — bound to `useCardsStore.filters`; renders category pills, group select, tag chips, search input.
- `features/cards/components/PublishForm.vue` — md-editor-v3 main area; bottom "附加信息" region for `summary`, `tags`, `cover`, `group`, slug preview; driven entirely by `useCardForm`. No custom right-side preview pane (per PROJECT_NOTES; the editor's built-in preview toggle suffices).
- `features/cards/components/AdminCardTable.vue` — table with sort/search; delete button hidden by default behind a `:show-delete="false"` prop; archive and edit always visible.
- `features/covers/components/CoverUploader.vue` — drag/drop + click + paste; preview + dimensions; calls `useCoverUpload`; emits `update:modelValue` (the URL).
- `features/tags/components/TagCloud.vue` — clickable tags wired to `useCardsStore.setFilter({tag})`.
- `features/auth/components/LoginForm.vue` — username/password + validation; calls `useAuthStore.login`; surfaces `AppError.code` via `useToast`.

##5. Migration plan (cards.json + notes/*.md → SQLite)

`backend/scripts/migrate_from_json.py` is a one-shot, idempotent CLI:

```
uv run python -m scripts.migrate_from_json \
  --json-file ../data/cards.json \
  --notes-dir ../content/notes \
  --owner-username admin \
  [--dry-run] [--report-html migration-report.html]
```

**Pre-flight.** The script does not run schema migrations. The operator must run `alembic upgrade head` first (or rely on the systemd `ExecStartPre`). The script asserts schema version matches `head` on startup.

**Behavior.** Single async transaction *per card*, in legacy file order:

1. Resolve owner: `SELECT FROM users WHERE username=:owner_username`. If missing, abort with a clear message ("seed admin first via alembic 0002 or scripts/seed_admin.py").
2. `legacy_id = entry['id']`. Look up `SELECT FROM cards WHERE slug=:legacy_id` (no archived filter — old data is the snapshot). If found, log `skip (already migrated)` and continue. **Idempotency is keyed solely on slug uniqueness.**
3. Mint `new_id = uuid4()`.
4. Map fields: `title=entry['title']`, `category=entry['category']`, `group=entry.get('group') or None` (legacy lacks it for most rows; logged as INFO when defaulted), `summary=entry.get('summary','')`, `cover=entry.get('cover') or None`, `tags=entry.get('tags') or []`, `archived=entry.get('archived', False)`, `created_at=parse(entry['created_at'] + 'T00:00:00+00:00')`, `updated_at=created_at`.
5. If `category=='external'`: `url=entry['url']`, `body=None`, `body_html=None`.
6. If `category=='local'`: resolve `md_path = notes_dir / Path(entry['markdown']).name`; abort the per-card transaction if missing; `body = md_path.read_text(encoding='utf-8')` (stored RAW — H1 strip happens at render); `body_html = render_markdown(body)`.
7. For covers under `../static/covers/` already pointing to `/covers/<id>.<ext>`: validate file exists on disk; warn (don't abort) if missing.
8. INSERT card row. On UNIQUE-violation against the partial slug index, append `-imported` and retry once; abort the script otherwise (this should never trigger because step 2 already gated on slug).
9. After all entries, log summary: `inserted=N, skipped=M, warnings=K`. Exit `0` only if there were no aborts.
10. `--dry-run` runs steps 1–8 inside a single outer transaction that is always rolled back; logs the same plan.
11. `--report-html` writes a per-row sanitizer audit (anything nh3 dropped vs the rendered tree) so the operator can spot legitimate constructs that were stripped before flipping production.

**Orphan note** (`multi-agent-super-universe-draft.md`): logged as a one-time WARN, not inserted. Recorded in `/var/log/linkgarden/migration.log`.

**Post-migration step**: the deploy script `chmod -R a-w data/ content/notes/` so the legacy snapshot becomes read-only. The new backend has no code path that writes to either tree.

**Rollback procedure** (documented in `docs/refactor/migration-runbook.md`):

- SQLite: `mv linkgarden.db linkgarden.db.bak && alembic upgrade head` recreates an empty schema; restore `data/cards.json` to read-write if needed; revert the systemd unit name back to `linkgarden-legacy.service`.
- Postgres swap: `pg_restore` the pre-migration dump.
- Zero data loss because the legacy tree is never mutated.

**Verification.**

- `pytest tests/scripts/test_migrate_from_json.py` exercises the script against a fresh in-memory DB with a fixture cards.json (covers external + local + archived rows, intentional missing markdown file, orphan note).
- `uv run python -m scripts.spot_check` lists card counts by category + tag distribution; operator compares to a snapshot taken from the legacy `/api/cards` before cutover.

## 6. Deployment plan

Single host. Two artifacts: a backend uv-managed venv and a frontend static `dist/`. One systemd unit. nginx terminates TLS and serves both.

**Host layout.**

```
/srv/linkgarden/
├── backend/                       # git checkout; .venv lives at /srv/linkgarden/venv
│   ├── src/app/static/covers/     # uploaded files
│   └── linkgarden.db              # SQLite (or unused when on Postgres)
├── frontend/dist/                 # rsynced Vite build
└── var/                           # log files, lock files
/etc/linkgarden/
└── linkgarden.env                 # secrets, chmod 600, owner linkgarden
```

**systemd unit** (`deploy/systemd/linkgarden.service`):

```ini
[Unit]
Description=LinkGarden API
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=linkgarden
Group=linkgarden
WorkingDirectory=/srv/linkgarden/backend
EnvironmentFile=/etc/linkgarden/linkgarden.env
ExecStartPre=/srv/linkgarden/venv/bin/alembic -c alembic.ini upgrade head
ExecStart=/srv/linkgarden/venv/bin/gunicorn app.asgi:app \
  -k uvicorn.workers.UvicornWorker -w 2 \
  --bind 127.0.0.1:5001 \
  --timeout 60 --graceful-timeout 30 \
  --proxy-headers --forwarded-allow-ips=127.0.0.1 \
  --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/srv/linkgarden/backend/src/app/static /srv/linkgarden/backend/linkgarden.db /srv/linkgarden/var

[Install]
WantedBy=multi-user.target
```

`-w 2` is the right starting point: UvicornWorker is async, SQLite serializes writes anyway. Bump to 4 if read concurrency becomes the bottleneck — never above 4 on a single-host SQLite deployment.

**nginx** (`deploy/nginx/linkgarden.conf`):

```nginx
limit_req_zone $binary_remote_addr zone=lg_login:10m rate=10r/m;

server {
  listen 443 ssl http2;
  server_name linkgarden.example.com;
  ssl_certificate/etc/letsencrypt/live/linkgarden.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/linkgarden.example.com/privkey.pem;

  root /srv/linkgarden/frontend/dist;
  index index.html;
  client_max_body_size 6m;  # > 5 MiB cover cap + slop

  add_header Content-Security-Policy "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'" always;
  add_header Referrer-Policy "strict-origin-when-cross-origin" always;
  add_header X-Content-Type-Options nosniff always;

  location = /api/v1/auth/login {
    limit_req zone=lg_login burst=5 nodelay;
    proxy_pass http://127.0.0.1:5001;proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }

  location /api/ {
    proxy_pass http://127.0.0.1:5001;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
  }

  location /covers/ {
    alias /srv/linkgarden/backend/src/app/static/covers/;
    expires 7d;
    add_header Cache-Control "public, immutable";
    access_log off;
  }

  location / {
    try_files $uri $uri/ /index.html;
  }
}
```

**Rollout order** (`scripts/deploy.sh`):

1. **Local build.** `cd frontend && pnpm install --frozen-lockfile && pnpm gen:api && pnpm typecheck && pnpm lint && pnpm test && pnpm build` — produces `frontend/dist/`.
2. **Backend deploy.** `ssh host'cd /srv/linkgarden/backend && git fetch && git checkout <sha> && uv sync --no-dev --frozen'`.
3. **Restart backend.** `ssh host 'systemctl restart linkgarden.service'`. The `ExecStartPre` runs `alembic upgrade head`; failure aborts the unit start, systemd reports `failed`, the previous binary keeps running because step 4 has not happened yet.
4. **Backend smoke.** `curl -fsS http://127.0.0.1:5001/api/v1/health` on the host; assert `{"ok": true}`.
5. **Frontend deploy.** `rsync -avz --delete frontend/dist/ user@host:/srv/linkgarden/frontend/dist/`. nginx auto-picks up new files; no reload required.
6. **End-to-end smoke.** `curl -fsS https://linkgarden.example.com/api/health`, then load `/`, `/card/<known-slug>`, `/admin/login`, `/admin`, exercise publish and cover upload.
7. **nginx config reload** (`systemctl reload nginx`) is required *only* when `deploy/nginx/linkgarden.conf` itself changed.
8. **Cutover from legacy** (one-time): rename the legacy unit to `linkgarden-legacy.service.disabled`, then enable+start `linkgarden.service`. Rollback is the inverse rename plus the migration rollback in §5.

**CI** (`.github/workflows`, gated but planned):

- Backend job: `uv sync --frozen`, `uv run ruff check`, `uv run pyright`, `uv run pytest`.
- Frontend job: `pnpm install --frozen-lockfile`, `pnpm gen:api && git diff --exit-code`, `pnpm typecheck`, `pnpm lint`, `pnpm test`, `pnpm build`.
- Contract job: spins up the backend in test mode, snapshots `/openapi.json`, compares to `frontend/openapi/schema.json`.

## 7. Backwards compatibility (legacy /api/* shim)

The old Flask backend exposed routes under `/api/*` (no version prefix). The new frontend lives at `/api/v1/*` from day one. For exactly one release after cutover, the new backend mounts a catch-all in `main.py`:

```python
# Registered AFTER the v1 router so it never shadows real routes.
@app.api_route("/api/{path:path}", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD"])
async def legacy_redirect(path: str, request: Request):
    if path == "health" or path.startswith("v1/"):
        # The /api/health mount is registered explicitly; this branch is
        # defensive in case route order is reshuffled.
        raise HTTPException(404)
    target = f"/api/v1/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    logger.warning(
        "legacy_api_hit",
        method=request.method,
        original_path=request.url.path,
        target=target,
        user_agent=request.headers.get("user-agent", ""),
    )
    return RedirectResponse(target, status_code=308)
```

`308 Permanent Redirect` preserves method + body per RFC 7538. Every hit is logged at WARN so the operator can confirm zero traffic before removing the shim. The CHANGELOG names the release in which the shim disappears.

Known caveat: a small number of old `fetch()` polyfills and `curl` versions <7.69 drop the body across a 308. Because we control the only first-party client (the SPA), we cut the SPA over to `/api/v1` in the same release that adds the shim. The shim is purely defensive for any bookmarks, scripts, or external callers we didn't know about.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| SQLite single-writer bottleneck under concurrent admin writes | WAL + `busy_timeout=5000`; workers ≤ 2; single-tenant admin workload. Postgres swap is one `DATABASE_URL` change (asyncpg declared as optional dep). |
| Alembic async env.py lands wrong (#1 cause of "alembic upgrade head" hangs) | Use the published async cookbook: `connection.run_sync(do_migrations)` with `render_as_batch=True` for SQLite; explicitly import every `features/*/models.py` in `env.py` so autogenerate sees the full metadata. |
| Pydantic v2 / SQLAlchemy 2 `Mapped[]` types silently misbehave | Pyright strict on `src/app/`, basic on `tests/`, gated in pre-commit; commits blocked until clean. |
| `JWT_SECRET` leaks via accidental commit | `.env` in `.gitignore`; `.env.example` carries placeholders only; `Settings` validates ≥32 chars and crashes uvicorn loudly before the first request. |
| nh3 strips legitimate markdown output (e.g., footnote refs, custom span classes) | Allowlist explicitly enumerated in `services/markdown.py`; pinned tests cover every supported construct including footnotes and task-lists; `--report-html` flag on the migrator surfaces real-corpus drops before cutover. |
| openapi-typescript codegen drifts vs server | `pnpm gen:api && git diff --exit-code` CI gate on the frontend job + backend snapshot test of `/openapi.json`. |
| Legacy `/api/*` 308 shim breaks clients that don't preserve body across redirects | Frontend cuts over to `/api/v1` in the same release that adds the shim; shim is defensive only; logged removal date in CHANGELOG. |
| Cover upload abuse — large files, MIME spoof, decompression bombs | 5 MiB stream cap with early abort; MIME from `Content-Type` + magic-byte sniff; `Pillow.verify()` then re-open; dimension cap 4096×4096; only `image/{png,jpeg,webp}`; admin-only endpoint. |
| Markdown rendering on every detail request burns CPU | `body_html` persisted as a column, re-rendered on every mutation that touches body or category; reads serve the cached HTML directly. No runtime LRU cache to coordinate. |
| Partial unique index on slug not portable toancient SQLite | `pyproject.toml` requires `python>=3.12`; deploy host check enforces `sqlite3≥ 3.8`. Covered by Ubuntu 22.04+ defaults. |
| Pinia 3 setup stores have no auto-`$reset` — easy to leak state on logout | Each store explicitly defines a `$reset` action that nulls/resets every `ref`; `auth.logout()` calls it; tests assert post-logout state. |
| highlight.js double-bundling (md-editor-v3 ships its own copy) | `pnpm.overrides` pins a single highlight.js version; Vite `manualChunks` splits it into its own chunk; `useEnhanceCodeBlocks` registers only the languages we use (ts, js, py, sh, json, html, css, vue, sql, md) keeping the chunk ≤50 KB. |
| Vite dev server can't reach FastAPI without proxy | `vite.config.ts` ships `server.proxy['/api'] = http://127.0.0.1:5001` from day one; documented in `frontend/README`. |
| `expire_on_commit=False` plus stale ORM objects after commit | Service layer always returns the result of an explicit re-`SELECT` after write, not the mutated instance. |
| JWT in `localStorage` is XSS-readable | Server-side sanitization (nh3); strict CSP at nginx (`script-src 'self'`); no third-party scripts; admin token short-lived (12h). Long-term migration to httpOnly cookies documented but deferred. |
| nginx config drift between envs | `deploy/nginx/linkgarden.conf` is the canonical source; the deploy script diffs it against the host's `/etc/nginx/sites-available/linkgarden.conf` and refuses to proceed on drift unless `--force-nginx` is passed. |
| WAL-mode SQLite on NFS corrupts | Deploy onto local disk (`/srv`) only; explicit warning in `deploy/README`. Container deploys require a local bind mount, not NFS. |
| Layered architecture adds boilerplate that slows feature work | Discipline is constrained: services own logic, repositories own SQL, routers stay ≤30 LOC. No DTO mappers — Pydantic does it. Trivial CRUD doesn't get extra abstraction for its own sake. |
| Admin password seeded via env shows up in shell history | `seed_admin.py` reads from `getpass()` when stdin is a TTY; alembic 0002 only runs if `LG_ADMIN_PASSWORD` is non-empty and inserts via parameterized SQL. |
| Migration script run twice creates duplicates | Idempotency keyed on slug uniqueness; partial unique index is the safety net; `SELECT WHERE slug=:legacy_id` gate before insert. |

## 9. Phase 3 work breakdown (parallelizable units)

Each unit is sized to live in its own git worktree with minimal collision against the others. `depends_on` lists are *logical* dependencies — a downstream unit can stub interfaces and run tests in parallel, integrating once upstream merges. Every unit ends with a passing test suite as its deliverable.

| id | title | owns_paths | depends_on | deliverable |
|---|---|---|---|---|
| **B1** | Backend scaffolding + core | `backend/pyproject.toml`, `backend/uv.lock`, `backend/alembic.ini`, `backend/ruff.toml`, `backend/pyrightconfig.json`, `backend/.env.example`, `backend/src/app/__init__.py`, `backend/src/app/main.py`, `backend/src/app/asgi.py`, `backend/src/app/core/**`, `backend/src/app/services/__init__.py`, `backend/tests/conftest.py`, `backend/tests/integration/test_health.py`, `backend/tests/integration/test_legacy_redirect.py`, `backend/src/app/features/health/**` | — | `uvicorn app.asgi:app` boots; `pytest tests/integration/test_health.py tests/integration/test_legacy_redirect.py` green; `GET /api/health` and `GET /api/v1/health` both return `{ok: true}`; legacy `/api/foo` 308s to `/api/v1/foo`. |
| **B2** | DB schema + Alembic init + seed | `backend/src/app/features/auth/models.py`, `backend/src/app/features/cards/models.py`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, `backend/alembic/versions/0001_initial.py`, `backend/alembic/versions/0002_seed_admin.py`, `backend/scripts/seed_admin.py`, `backend/tests/unit/test_security.py` | B1 (Base, settings, GUID type) | `alembic upgrade head` succeeds on a fresh SQLite; `0002` seeds the admin row idempotently; `pytest tests/unit/test_security.py` green. |
| **B3** | Markdown service | `backend/src/app/services/markdown.py`, `backend/tests/unit/test_markdown.py` | B1 (deps installed) | `render_markdown` round-trips the full happy-path corpus (headings, code, tables, footnotes, task-lists, links, images) and drops the full XSS corpus (`<script>`, `on*=`, `javascript:`, `<iframe>`);100% branch coverage on the file. |
| **B4** | Auth feature (router + service + repo + deps) | `backend/src/app/features/auth/{schemas.py,repo.py,service.py,deps.py,routes.py}`, `backend/tests/integration/test_auth.py` | B1, B2 | `POST /auth/login` issues a JWT; `GET /auth/me` returns the seeded admin; wrong password → 401 `invalid_credentials`; expired/forged token → 401 `unauthenticated`; `require_admin` blocks non-admin (future-proofing test). |
| **B5** | Cards feature (router + service + repo + slug) | `backend/src/app/features/cards/{schemas.py,slug.py,repo.py,service.py,routes.py}`, `backend/tests/unit/test_slug.py`, `backend/tests/integration/test_cards.py` | B1, B2, B3, B4 | Full CRUD passes: list with every filter combination, slug collision auto-suffix, partial-update preserves omitted fields, category switch re-renders body_html, archive toggles partial unique index correctly, hard delete cleans cover file. |
| **B6** | Covers feature | `backend/src/app/features/covers/{schemas.py,service.py,routes.py}`, `backend/tests/integration/test_covers.py` | B1, B4, B5 | `POST /covers` succeeds for PNG/JPEG/WebP under 5 MiB; rejects spoofed MIME, oversized files, oversized dimensions, dimension floor; atomic write verified (no partial files on simulated crash); old-extension siblings unlinked; `cards.cover` updated atomically. |
| **B7** | Tags feature + OpenAPI snapshot test | `backend/src/app/features/tags/{repo.py,routes.py}`, `backend/tests/integration/test_tags.py`, `backend/tests/integration/test_openapi_snapshot.py`, `backend/tests/fixtures/openapi_snapshot.json` | B1, B5 | `GET /tags` returns distinct sorted tags across non-archived cards; `include_archived=true` includes archived; OpenAPI snapshot test seeds and fails on drift; snapshot file committed. |
| **B8** | Migration script | `backend/scripts/migrate_from_json.py`, `backend/scripts/spot_check.py`, `backend/tests/scripts/test_migrate_from_json.py`, `backend/tests/fixtures/cards.json`, `backend/tests/fixtures/notes/*.md`, `docs/refactor/migration-runbook.md` | B2, B3, B5 | Migration is idempotent on slug, handles missing markdown gracefully, defaults `group`, logs orphan notes; `--dry-run` rolls back cleanly; `--report-html` writes the sanitizer audit; runbook covers rollback. |
| **B9** | Frontend scaffolding + shared kit | `frontend/index.html`, `frontend/vite.config.ts`, `frontend/tsconfig*.json`, `frontend/eslint.config.ts`, `frontend/.prettierrc`, `frontend/.nvmrc`, `frontend/package.json`, `frontend/pnpm-lock.yaml`, `frontend/scripts/gen-api.ts`, `frontend/src/main.ts`, `frontend/src/App.vue`, `frontend/src/router/**`, `frontend/src/layouts/**`, `frontend/src/stores/ui.ts`, `frontend/src/shared/**` (api/client.ts, api/interceptors.ts, api/errors.ts, composables/, ui/Base*.vue, ui/NotFoundView.vue, ui/AppSpinner.vue, utils/, types/), `frontend/src/assets/styles/**`, `frontend/openapi/schema.json` | B1, B4, B7 (snapshot file flows to `frontend/openapi/schema.json` initially) | `pnpm dev` boots, hits the proxy; `pnpm gen:api` produces `schema.d.ts`; router renders empty `HomeView`/`NotFoundView`; `useUiStore` toast and `BaseToast` round-trip; ESLint + vue-tsc clean. |
| **B10** | Auth feature frontend | `frontend/src/features/auth/**`, `frontend/src/tests/unit/auth.spec.ts` | B9, B4 | `LoginView` calls `auth.login`, persists token via `pinia-plugin-persistedstate`, redirects to `?next`; `auth:invalidated` event clears state and routes to login when route requires admin; `fetchMe` populates user on app boot. |
| **B11** | Cards feature frontend (public) | `frontend/src/features/cards/{api.ts,store.ts,composables/useFilters.ts}`, `frontend/src/features/cards/views/{HomeView.vue,CardDetailView.vue}`, `frontend/src/features/cards/components/{CardGrid.vue,CardItem.vue,CardCover.vue,CardFilters.vue,ArticleBody.vue,ArticleHero.vue,HeroBanner.vue}`, `frontend/src/features/tags/**`, `frontend/src/shared/composables/useEnhanceCodeBlocks.ts`, `frontend/src/tests/unit/cards-public.spec.ts` | B9, B5, B7 | Home renders list with filters from URL; detail view renders `v-html` with idempotent highlight.js; tag cloud drives store filter; cover cards encode URLs correctly; 404 view shown when slug missing. |
| **B12** | Admin frontend (publish + manage + covers UI) | `frontend/src/features/cards/views/{AdminCardsView.vue,AdminPublishView.vue}`, `frontend/src/features/cards/components/{PublishForm.vue,AdminCardTable.vue}`, `frontend/src/features/cards/composables/useCardForm.ts`, `frontend/src/features/covers/**`, `frontend/src/shared/composables/useCoverUpload.ts`, `frontend/src/tests/unit/cards-admin.spec.ts` | B10, B11, B6 | Publish creates a card, edits update it, archive toggles, cover upload previews and persists; PUT preserves omitted fields; delete button hidden by default; route guard enforced. |
| **B13** | Deployment artifacts | `deploy/systemd/linkgarden.service`, `deploy/nginx/linkgarden.conf`, `deploy/env/linkgarden.env.example`, `scripts/deploy.sh`, `scripts/gen-api.sh`, `docs/refactor/deploy-runbook.md` | B1, B9 | `scripts/deploy.sh --dry-run` succeeds against a staging host; nginx config validates with `nginx -t`; systemd unit boots in a Docker/Vagrant smoke env; runbook covers rollout + rollback + cutover. |
| **B14** | Repo hygiene + CI workflows | `.github/workflows/backend.yml`, `.github/workflows/frontend.yml`, `.github/workflows/contract.yml`, `README.md`, `CLAUDE.md`, `docs/architecture/diagrams/*`, pre-commit hooks | B1, B9 | CI runs ruff/pyright/pytest on backend, eslint/vue-tsc/vitest/build on frontend, codegen-drift gate; pre-commit hooks block commits with type or lint errors; README documents dev loop end-to-end. |

Dependency graph at a glance: B1 unblocks B2/B3/B7/B9; B2 unblocks B4/B5/B8; B3+B4+B5 unblock B6and B11/B12; B7 unblocks B9 (via the snapshot file). B10/B11/B12 can run concurrently once B9 is in place. B13 and B14 can begin in parallel as soon as B1 and B9 produce runnable artifacts.