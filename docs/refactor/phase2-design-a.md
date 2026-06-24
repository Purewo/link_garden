# Proposal A

## Overview

Pragmatic, flat-layered FastAPI + SQLAlchemy backend paired with a feature-folder Vue 3.5 SPA. Backend is one router per resource (health/auth/cards/tags/covers), one service module per concern (cards/covers/auth/markdown), thin Pydantic schemas, AsyncSession injected via FastAPI Depends. No DDD layers, no repositories — services own transactions and call the ORM directly. Frontend is view-as-feature (public views flat, admin views nested under views/admin/), three Pinia setup stores (auth/cards/ui), one openapi-fetch client with a tiny middleware for auth + error normalization, and md-editor-v3/highlight.js as the only heavy dependencies. JWT (HS256, 12h) goes through Authorization: Bearer; auth state persists via pinia-plugin-persistedstate. All endpoints under /api/v1; legacy /api/* paths return a one-release 308 shim. Markdown is rendered + sanitized server-side and trusted via v-html on the client. Covers upload to backend/static/covers/ and are served directly by nginx.

## Repository layout

```
(see backend tree below + frontend tree under §Frontend)
```

## Backend

### Directory tree (backend/)

```
backend/
├── pyproject.toml            # PEP 621; deps: fastapi~=0.118, pydantic~=2.11, pydantic-settings~=2.6, sqlalchemy[asyncio]~=2.0.36, alembic~=1.14, aiosqlite~=0.20, pyjwt~=2.10, bcrypt~=4.2, python-multipart~=0.0.20, markdown-it-py~=3.0, mdit-py-plugins~=0.4, linkify-it-py~=2.0, nh3~=0.2, Pillow~=11.0, structlog~=24.4, uvicorn[standard]~=0.34, gunicorn~=23.0; [project.optional-dependencies] postgres = [asyncpg~=0.30]; [tool.ruff]/[tool.pyright]/[tool.pytest.ini_options]
├── uv.lock
├── alembic.ini               # script_location = app/alembic; URL overridden in env.py from settings
├── .env.example              # DATABASE_URL, JWT_SECRET, JWT_TTL_SECONDS=43200, LG_ADMIN_USERNAME, LG_ADMIN_PASSWORD, COVERS_DIR, COVERS_PUBLIC_PREFIX=/covers, ALLOWED_ORIGINS, APP_ENV
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py               # create_app() factory, lifespan(engine.dispose), CORSMiddleware (dev only), exception handlers, mounts /api/v1 + legacy /api shim
│   ├── settings.py           # Settings(BaseSettings) singleton; reads .env at import time
│   ├── db.py                 # async_engine, async_sessionmaker(expire_on_commit=False), get_db() generator, sqlite "connect" listener (WAL, foreign_keys=ON, busy_timeout=5000)
│   ├── models.py             # Base(DeclarativeBase) with MetaData(naming_convention=...); User, Card ORM with Mapped[]
│   ├── deps.py               # DbDep, CurrentUserDep, AdminUserDep type aliases (Annotated[..., Depends(...)])
│   ├── errors.py             # LGException, lg_exception_handler, validation_exception_handler, http_exception_handler — all return {ok:false,error,code} envelope
│   ├── security.py           # hash_password / verify_password (bcrypt direct), encode_token / decode_token (PyJWT, HS256 pinned)
│   ├── slug.py               # slugify(text, fallback) (CJK-safe), unique_slug(session, base, exclude_id)
│   ├── routers/
│   │   ├── __init__.py       # api_v1_router = APIRouter(prefix="/v1"); include_router(health, auth, cards, tags, covers)
│   │   ├── health.py         # GET /health
│   │   ├── auth.py           # POST /auth/login, GET /auth/me
│   │   ├── cards.py          # GET /cards, GET /cards/{slug}, POST /cards, PUT /cards/{id}, PATCH /cards/{id}/archive, DELETE /cards/{id}
│   │   ├── tags.py           # GET /tags
│   │   └── covers.py         # POST /covers (multipart)
│   ├── schemas/
│   │   ├── __init__.py       # re-exports
│   │   ├── common.py         # ErrorResponse, OkResponse, OkBoolField helper
│   │   ├── auth.py           # LoginRequest, TokenResponse, UserPublic
│   │   ├── cards.py          # CardCreate, CardUpdate, CardPublic, CardDetail, CardListQuery, ArchiveRequest
│   │   └── covers.py         # CoverUploadResponse
│   ├── services/
│   │   ├── __init__.py
│   │   ├── markdown.py       # render_markdown(md) -> sanitized html via markdown-it-py + nh3 strict allowlist
│   │   ├── cards.py          # list_cards(filters), get_card_by_slug, create_card, update_card, set_archive, delete_card, list_tags
│   │   ├── covers.py         # save_upload(file, card_id) -> public_url; validates content-type, magic bytes (Pillow), dimensions (max 4096), size (max 5MB)
│   │   └── auth.py           # authenticate(username, password), mint_token(user), seed_admin(session, settings)
│   └── alembic/
│       ├── env.py            # async migrate via run_sync; render_as_batch=True for sqlite; imports app.models so autogenerate sees all tables
│       ├── script.py.mako
│       └── versions/
│           ├── 0001_initial.py    # users + cards + indexes + admin row seeded from env (uses op.bulk_insert)
│           └── 0002_xxx.py        # placeholder for future migrations
├── scripts/
│   ├── migrate_from_json.py  # one-shot legacy importer; idempotent on slug
│   └── create_admin.py       # interactive admin creator (uv run python -m scripts.create_admin)
├── static/
│   └── covers/               # uploaded files; nginx alias /covers/ → here
└── tests/
    ├── conftest.py           # in-memory aiosqlite engine fixture, AsyncSession, httpx.AsyncClient(ASGITransport), admin_token
    ├── factories.py
    ├── test_health.py
    ├── test_auth.py
    ├── test_cards.py
    ├── test_covers.py
    ├── test_markdown.py
    └── test_legacy_redirect.py
```

### Modules and responsibilities

| module | responsibility | depends_on |
| --- | --- | --- |
| app/main.py | FastAPI factory create_app(); installs lifespan (engine dispose on shutdown), CORSMiddleware (only when APP_ENV=='dev'), registers exception handlers from errors.py, mounts api_v1_router under /api, registers a catch-all /api/{path:path} legacy shim that 308-redirects to /api/v1/{path}, mounts no static (nginx serves covers). | app/settings.py, app/db.py, app/errors.py, app/routers/__init__.py |
| app/settings.py | Settings(BaseSettings) singleton: DATABASE_URL, JWT_SECRET, JWT_ALG='HS256', JWT_TTL_SECONDS=43200, LG_ADMIN_USERNAME, LG_ADMIN_PASSWORD, COVERS_DIR (Path), COVERS_PUBLIC_PREFIX='/covers', ALLOWED_ORIGINS (list), APP_ENV ('dev'\|'prod'). Reads .env at import time. |  |
| app/db.py | Builds AsyncEngine from settings.DATABASE_URL, async_sessionmaker(expire_on_commit=False); registers a sqlalchemy event 'connect' listener that runs PRAGMA journal_mode=WAL, synchronous=NORMAL, foreign_keys=ON, busy_timeout=5000 when dialect is sqlite; exposes get_db() async generator that yields a session, rollbacks on exception, closes in finally. | app/settings.py |
| app/models.py | Base(DeclarativeBase) with MetaData(naming_convention={'ix':'ix_%(table_name)s_%(column_0_N_name)s','uq':'uq_%(table_name)s_%(column_0_N_name)s','ck':'ck_%(table_name)s_%(constraint_name)s','fk':'fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s','pk':'pk_%(table_name)s'}); TimestampMixin (created_at, updated_at). Defines User and Card with typed Mapped[]. |  |
| app/deps.py | Type aliases for FastAPI dependencies: DbDep = Annotated[AsyncSession, Depends(get_db)]; CurrentUserDep = Annotated[User, Depends(get_current_user)] which decodes Authorization header, loads user from DB, raises LGException('UNAUTHENTICATED'); AdminUserDep = Annotated[User, Depends(require_admin)] which extends CurrentUserDep and asserts role=='admin', raises LGException('FORBIDDEN'). | app/db.py, app/models.py, app/security.py, app/errors.py, app/settings.py |
| app/errors.py | LGException(code: str, message: str, status: int = 400) raised throughout the app. Three FastAPI exception handlers: (1) LGException -> JSONResponse({'ok':False,'error':msg,'code':code}, status); (2) RequestValidationError -> {'ok':False,'error':'invalid request body','code':'INVALID_BODY','detail':errs}, 422; (3) StarletteHTTPException -> envelope using a code derived from status (404→NOT_FOUND, etc). |  |
| app/security.py | hash_password(pw)/verify_password(pw, hashed) wrapping bcrypt directly (truncates to 72 bytes, raises LGException if longer). encode_token(user) returns JWT with claims {sub:user_id_str, username, role, iat, exp} using settings.JWT_SECRET + HS256. decode_token(token) verifies signature with algorithms=['HS256'], returns claims dict or raises LGException('UNAUTHENTICATED'). | app/settings.py, app/errors.py |
| app/slug.py | slugify(text) -> str (lowercase; replace whitespace with '-'; keep [a-z0-9-一-鿿]; strip leading/trailing '-'; fallback to 'article-<short_uuid>' when empty). unique_slug(session, base, exclude_id=None) -> str: queries Card rows with archived=False, finds the lowest -2/-3/... suffix that is unused (the partial unique index is the safety net). | app/models.py |
| app/routers/health.py | GET /health -> {'ok': True}. Mirrored mount also exists at bare /api/health (registered directly in main.py) so external monitors stay on a stable path. |  |
| app/routers/auth.py | POST /auth/login (body LoginRequest) -> TokenResponse via services.auth.authenticate + mint_token; GET /auth/me (CurrentUserDep) -> UserPublic. | app/deps.py, app/services/auth.py, app/schemas/auth.py, app/errors.py |
| app/routers/cards.py | All 6 card endpoints. Reads CardListQuery via Query(...) bundle; calls services/cards. Requires AdminUserDep on POST/PUT/PATCH/DELETE; GET endpoints are public. | app/deps.py, app/services/cards.py, app/schemas/cards.py, app/errors.py |
| app/routers/tags.py | GET /tags?include_archived= -> list[str] via services.cards.list_tags; default excludes archived (matches /cards default). | app/deps.py, app/services/cards.py |
| app/routers/covers.py | POST /covers (multipart: file: UploadFile, card_id: UUID = Form). Verifies card exists, calls services.covers.save_upload, returns CoverUploadResponse. Updates Card.cover to the returned public URL atomically. | app/deps.py, app/services/covers.py, app/services/cards.py, app/schemas/covers.py, app/errors.py |
| app/services/markdown.py | render_markdown(md: str) -> str. Configures markdown-it-py with linkify=True, html=False, plugins: footnote, anchors disabled (no slugged headings), table, deflist; emits fenced_code with class='language-X' and data-language='X' attribute on <code>. Pipes output through nh3.clean(html, tags={'h1','h2','h3','h4','h5','h6','p','ul','ol','li','blockquote','pre','code','a','img','table','thead','tbody','tr','th','td','hr','em','strong','br','span','div'}, attributes={'a':{'href','title','rel','target'},'img':{'src','alt','title'},'code':{'class','data-language'},'span':{'class'},'div':{'class'}}, url_schemes={'http','https','mailto'}); strips a leading '# H1' line before render (preserves today's behavior). |  |
| app/services/cards.py | list_cards(session, filters: CardListQuery) -> list[Card] with WHERE archived=False unless include_archived; case-insensitive q filter on title \|\| summary \|\| tags JSON; ORDER BY created_at DESC, id DESC. get_card_by_slug(session, slug) (raises LGException('CARD_NOT_FOUND',404) if missing). create_card(session, payload, author_id): mints uuid4(), runs slugify+unique_slug, validates category↔(url\|body), renders body_html lazily (no — render on read; see notes). update_card(session, card_id, payload): partial update, fields omitted are kept (fixes today's PUT bug); never changes slug. set_archive(session, card_id, archived). delete_card(session, card_id): unlinks cover file if cover starts with COVERS_PUBLIC_PREFIX. list_tags(session, include_archived) -> sorted distinct flatten of cards.tags. Markdown rendering happens in get_card_by_slug only (cached via @lru_cache keyed on (id, updated_at)). | app/models.py, app/slug.py, app/services/markdown.py, app/errors.py, app/settings.py |
| app/services/covers.py | save_upload(file: UploadFile, card_id: UUID) -> str. Validates content-type ∈ {image/png, image/jpeg, image/webp}; reads bytes (max 5 MiB; raises COVER_TOO_LARGE); opens with Pillow, verifies dims ≤ 4096×4096; picks ext from MIME; writes atomically (tmp + os.replace) to settings.COVERS_DIR/<card_id>.<ext>; returns f'{settings.COVERS_PUBLIC_PREFIX}/{card_id}.{ext}'. Old extension files for the same card_id (other ext) get unlinked. | app/settings.py, app/errors.py |
| app/services/auth.py | authenticate(session, username, password) -> User or raise LGException('INVALID_CREDENTIALS',401); seed_admin(session, settings) called from alembic 0001 (op.run_async-equivalent via op.bulk_insert with pre-hashed password) and from a test fixture; mint_token(user) wraps security.encode_token. | app/models.py, app/security.py, app/settings.py, app/errors.py |

### SQLAlchemy models


#### users

Columns:
```
id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4); username: Mapped[str] = mapped_column(String(64), nullable=False); password_hash: Mapped[str] = mapped_column(String(255), nullable=False); role: Mapped[str] = mapped_column(String(16), nullable=False, default='admin'); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

Indexes:
- uq_users_username UNIQUE (username)

Relationships:
- cards: Mapped[list[Card]] = relationship(back_populates='author')


#### cards

Columns:
```
id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4); slug: Mapped[str] = mapped_column(String(255), nullable=False); title: Mapped[str] = mapped_column(String(255), nullable=False); category: Mapped[str] = mapped_column(String(16), nullable=False)  # 'external' | 'local'; group: Mapped[str | None] = mapped_column(String(16), nullable=True)  # '技术类' | '随笔类' | '生活类'; summary: Mapped[str] = mapped_column(Text, nullable=False, default=''); cover: Mapped[str | None] = mapped_column(String(512), nullable=True); url: Mapped[str | None] = mapped_column(String(2048), nullable=True); body: Mapped[str | None] = mapped_column(Text, nullable=True); tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list); archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False); author_id: Mapped[UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False); updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

Indexes:
- ix_cards_slug_active UNIQUE (slug) WHERE archived = false  -- partial unique; slug uniqueness only among non-archived (works on SQLite >= 3.8 and PostgreSQL)
- ix_cards_archived_created_at (archived, created_at DESC)
- ix_cards_category (category)
- ix_cards_group (group)
- ix_cards_author_id (author_id)
- ck_cards_category CHECK (category IN ('external','local'))

Relationships:
- author: Mapped[User | None] = relationship(back_populates='cards')


### Pydantic schemas

| name | fields | used_by |
| --- | --- | --- |
| ErrorResponse | ok: Literal[False] = False; error: str; code: str; detail: list[dict] \| None = None | all error responses (declared as the 4xx response_model in router signatures via responses={400: {'model': ErrorResponse}, ...}) |
| OkResponse | ok: Literal[True] = True | DELETE /cards/{id}, COVER on success-only, generic acks |
| LoginRequest | username: str (min 1, max 64); password: str (min 1, max 256) | POST /auth/login body |
| UserPublic | id: UUID; username: str; role: str; created_at: datetime; model_config = ConfigDict(from_attributes=True) | GET /auth/me, embedded in TokenResponse |
| TokenResponse | access_token: str; token_type: Literal['bearer'] = 'bearer'; expires_in: int; user: UserPublic | POST /auth/login response |
| CardCategory | Literal['external', 'local']  # type alias | Card schemas |
| CardGroup | Literal['技术类', '随笔类', '生活类']  # extensible — keep as Literal until DB migration adds enum table | Card schemas |
| CardListQuery | category: CardCategory \| None = None; group: CardGroup \| None = None; tag: str \| None = None; q: str \| None = None; include_archived: bool = False  # bound via Query(...) in router signature | GET /cards |
| CardCreate | title: str (min 1, max 255); category: CardCategory; group: CardGroup \| None = None; summary: str = ''; cover: str \| None = None; tags: list[str] = []  # validated: trim, dedupe ci, max 16 tags, each ≤32 chars; url: str \| None = None  # required iff category=='external', validated as http(s) URL; body: str \| None = None  # required iff category=='local'; slug_seed: str \| None = None  # optional override of slug source; @model_validator enforces category↔(url\|body) coupling | POST /cards body |
| CardUpdate | title: str \| None = None; category: CardCategory \| None = None; group: CardGroup \| None = None; summary: str \| None = None; cover: str \| None = None; tags: list[str] \| None = None; url: str \| None = None; body: str \| None = None; archived: bool \| None = None  # all optional; only fields present (model_dump(exclude_unset=True)) get applied — fixes the legacy 'PUT silently wipes summary/cover' bug | PUT /cards/{id} body |
| ArchiveRequest | archived: bool  # required; no default — fixes legacy 'empty body archives' surprise | PATCH /cards/{id}/archive body |
| CardPublic | id: UUID; slug: str; title: str; category: CardCategory; group: CardGroup \| None; summary: str; cover: str \| None; url: str \| None; tags: list[str]; archived: bool; created_at: datetime; updated_at: datetime; model_config = ConfigDict(from_attributes=True) | GET /cards items, POST /cards / PUT /cards / PATCH archive responses |
| CardDetail | extends CardPublic with: body: str \| None = None  # raw md, H1-stripped; body_html: str \| None = None  # sanitized html — both populated only when category=='local' | GET /cards/{slug} response |
| CoverUploadResponse | ok: Literal[True] = True; url: str  # e.g. /covers/<uuid>.png; card: CardPublic  # the updated card with new cover field | POST /covers response |

### API v1 contract

| method | path | auth | request | response_2xx | response_4xx | notes |
| --- | --- | --- | --- | --- | --- | --- |
| GET | /api/health | public | — | {ok: true} | — | Stable monitor path; mounted directly in main.py outside the /v1 prefix so external monitoring never breaks on a version bump. |
| GET | /api/v1/health | public | — | {ok: true} | — | Mirror under /v1 for consistency. |
| POST | /api/v1/auth/login | public | JSON LoginRequest | TokenResponse {access_token, token_type:'bearer', expires_in:43200, user:UserPublic} | 401 ErrorResponse{code:'INVALID_CREDENTIALS'}; 422 ErrorResponse{code:'INVALID_BODY'} | Constant-time bcrypt compare; identical 401 message for missing user vs bad password. |
| GET | /api/v1/auth/me | bearer-any | — | UserPublic | 401 ErrorResponse{code:'UNAUTHENTICATED'} | Used by frontend on app boot to validate persisted token. |
| GET | /api/v1/cards | public | Query CardListQuery: category?, group?, tag?, q?, include_archived? | list[CardPublic] | 422 ErrorResponse{code:'INVALID_BODY'} | Default excludes archived. Sort: created_at DESC, id DESC. q is case-insensitive substring across title \|\| summary \|\| tags. tag is exact-match (case-insensitive) against any element of cards.tags. |
| GET | /api/v1/cards/{slug} | public | Path slug:str | CardDetail (body+body_html only for category=='local') | 404 ErrorResponse{code:'CARD_NOT_FOUND'} | body_html is server-rendered + sanitized via services/markdown.py. Looks up by slug, NOT id. Cached at the service layer keyed on (card.id, updated_at). |
| POST | /api/v1/cards | bearer-admin | JSON CardCreate | 201 CardPublic | 400 ErrorResponse{code:'MISSING_FIELD'\|'INVALID_CATEGORY'}; 422 INVALID_BODY; 401/403 | Mints UUID id, computes slug from slug_seed\|\|title, regenerates with -2/-3 on collision among non-archived. external⇒url required; local⇒body required. |
| PUT | /api/v1/cards/{id} | bearer-admin | Path id:UUID; JSON CardUpdate (partial) | CardPublic | 404 CARD_NOT_FOUND; 400 INVALID_CATEGORY; 422 INVALID_BODY; 401/403 | Only present fields applied (model_dump(exclude_unset=True)). Slug NEVER changes. Switching category enforces required url/body coupling on the resulting state. |
| PATCH | /api/v1/cards/{id}/archive | bearer-admin | Path id:UUID; JSON ArchiveRequest | CardPublic | 404 CARD_NOT_FOUND; 422 INVALID_BODY; 401/403 | Setter (not toggle); body required. Archiving a card with a slug that has a non-archived twin succeeds because partial unique index permits it once archived=true. |
| DELETE | /api/v1/cards/{id} | bearer-admin | Path id:UUID | OkResponse | 404 CARD_NOT_FOUND; 401/403 | Hard delete. Unlinks cover file under settings.COVERS_DIR if cover URL starts with settings.COVERS_PUBLIC_PREFIX. UI keeps the button hidden per PROJECT_NOTES; endpoint exists for ops use. |
| GET | /api/v1/tags | public | Query include_archived?: bool | list[str] (sorted, distinct) | — | Default excludes archived (fixes today's bug where tags leak from archived cards while /cards excludes them). |
| POST | /api/v1/covers | bearer-admin | multipart/form-data: file: UploadFile, card_id: UUID | CoverUploadResponse {ok, url, card} | 400 BAD_REQUEST; 404 CARD_NOT_FOUND; 413 COVER_TOO_LARGE; 415 COVER_BAD_TYPE; 401/403 | MIME ∈ {image/png, image/jpeg, image/webp}; ≤ 5 MiB; ≤ 4096×4096 verified via Pillow magic bytes (defense vs MIME spoof). Atomic write tmp + os.replace. Updates card.cover and returns the updated card. |
| ANY | /api/{path:path}  (legacy shim — non-/v1) | passthrough | any | 308 Permanent Redirect to /api/v1/{path} | — | Registered with low priority in main.py; only catches paths not starting with v1/ or health. 308 preserves method+body. Removed one release after the new frontend ships. |

### Auth flow

**Login Flow:** Frontend POSTs JSON {username, password} to /api/v1/auth/login. services.auth.authenticate(session, u, p) selects the user by username, runs bcrypt.checkpw(password.encode()[:72], user.password_hash); on mismatch raises LGException('INVALID_CREDENTIALS', 401). On success, mint_token(user) returns the JWT and the handler returns TokenResponse. Frontend stores access_token + user in the auth Pinia store (persisted via pinia-plugin-persistedstate to localStorage) and starts including 'Authorization: Bearer <token>' on every subsequent request via the openapi-fetch middleware.
**Password Hash:** bcrypt 4.x called directly (no passlib). hash_password(pw) -> bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds=12)).decode(). verify_password(pw, hashed) -> bcrypt.checkpw(pw.encode()[:72], hashed.encode()). 72-byte truncation documented in README. Reject passwords shorter than 8 chars at the schema layer (LoginRequest min_length=1 for login but the seed/create_admin script enforces ≥8).
**Jwt Claims:** Algorithm HS256 only (decode pinned). Claims: {sub: str(user.id), username: str, role: 'admin'|..., iat: int, exp: int}. Secret from settings.JWT_SECRET (≥32 bytes; generated via `openssl rand -hex 32`).
**Token Lifetime:** 12 hours (43200 seconds) via settings.JWT_TTL_SECONDS. Single-tenant single-admin app — long-lived token is acceptable. expires_in returned alongside access_token so the frontend can preempt refresh-by-relogin a few minutes early if desired.
**Refresh Strategy:** No refresh token in v1. On any 401 from the API, the openapi-fetch middleware clears the auth store and (if the current route requires admin) redirects to /admin/login with a ?next= return URL. Re-login is the refresh mechanism. Refresh tokens deferred until multi-user/role expansion.
**Guard Decorator:** FastAPI Depends, no custom decorator. Type aliases in app/deps.py: CurrentUserDep = Annotated[User, Depends(get_current_user)] decodes the Authorization header (raises UNAUTHENTICATED on missing/invalid/expired token), loads the user row, returns it. AdminUserDep = Annotated[User, Depends(require_admin)] composes CurrentUserDep and asserts role=='admin' (raises FORBIDDEN otherwise). Routes write `_: AdminUserDep` as a parameter to enforce.


### Markdown pipeline
(see backend services/markdown.py per locked decisions; A inherits the pipeline)


### Cover upload pipeline
(see API contract row for POST /api/v1/covers)


### Error envelope and exception handlers

- Error envelope is exactly {ok: false, error: string, code: string, detail?: any}; success bodies are the resource itself (CardPublic / CardDetail / list / TokenResponse) — no top-level {ok: true, data: ...} wrapping for resource reads. — Resource shape parity with FastAPI's natural OpenAPI types; codegen produces clean components/schemas. Errors are the only place the envelope shows up, which keeps the success path 1:1 with the OpenAPI types and trivially typed via openapi-fetch.

- Stable error codes: INVALID_BODY, MISSING_FIELD, INVALID_CATEGORY, CARD_NOT_FOUND, SLUG_CONFLICT, INVALID_CREDENTIALS, UNAUTHENTICATED, FORBIDDEN, COVER_TOO_LARGE, COVER_BAD_TYPE, COVER_DIM_TOO_LARGE, INTERNAL. — Frontend can branch on code without parsing free-text error strings; codes never localized.


## Frontend

### Directory tree (frontend/)

```
frontend/
├── index.html                # title 'Link Garden'; mounts /src/main.ts as module
├── vite.config.ts            # @vitejs/plugin-vue, server.proxy['/api'] = http://127.0.0.1:5001, server.port 5173, vite-plugin-checker (vue-tsc + eslint), build.outDir 'dist'
├── tsconfig.json             # references app/node/vitest
├── tsconfig.app.json         # moduleResolution: 'Bundler', strict: true
├── tsconfig.node.json
├── tsconfig.vitest.json
├── eslint.config.ts          # ESLint 9 flat: typescript-eslint v8, eslint-plugin-vue v10 flat preset, eslint-config-prettier; ignores src/api/schema.d.ts
├── .prettierrc
├── package.json              # see locked stack; NO axios, NO @milkdown/*, NO marked, NO marked-highlight; pnpm overrides for highlight.js
├── pnpm-lock.yaml
├── public/
│   ├── favicon.svg
│   └── images/
│       └── avatar.jpg
├── openapi/
│   └── schema.json           # snapshot of backend /api/v1/openapi.json (committed)
├── scripts/
│   └── gen-api.ts            # `tsx scripts/gen-api.ts`: fetches /openapi.json from BACKEND_URL or reads ./openapi/schema.json, runs openapi-typescript → writes src/api/schema.d.ts
└── src/
    ├── main.ts               # createApp(App).use(pinia.use(piniaPluginPersistedstate)).use(router).mount('#app')
    ├── App.vue               # <component :is="currentLayout"><router-view/></component>; layout chosen from route.meta.layout
    ├── router/
    │   ├── index.ts          # createRouter({history: createWebHistory(), routes}) with lazy() imports
    │   └── guards.ts         # beforeEach: setTitle, requireAdmin, redirectIfAuthenticated
    ├── stores/
    │   ├── auth.ts           # setup store; persisted: token, user
    │   ├── cards.ts          # setup store: list cache, filters, fetchers
    │   └── ui.ts             # setup store: keyword (debounced), theme
    ├── api/
    │   ├── client.ts         # createClient<paths>({baseUrl: '/api/v1'}); registers middleware from interceptors.ts
    │   ├── interceptors.ts   # onRequest: attach Authorization from auth store; onResponse: if !res.ok, throw normalized LGError({code, message, status, detail}); on 401 -> auth.logout() + router.push if needed
    │   ├── schema.d.ts       # GENERATED — committed; ESLint excluded
    │   └── modules/
    │       ├── auth.ts       # login(req), me(), logout()
    │       ├── cards.ts      # listCards(query), getCard(slug), createCard, updateCard, archiveCard, deleteCard
    │       ├── covers.ts     # uploadCover(file, cardId)
    │       └── tags.ts       # listTags(includeArchived)
    ├── views/
    │   ├── HomeView.vue
    │   ├── DetailView.vue
    │   ├── NotFoundView.vue
    │   └── admin/
    │       ├── LoginView.vue
    │       ├── AdminListView.vue
    │       └── AdminPublishView.vue
    ├── layouts/
    │   ├── PublicLayout.vue  # hero+nav chrome (replaces App.vue route-branching)
    │   ├── AdminLayout.vue   # admin sidebar + topbar + 回到前台 chip
    │   └── BlankLayout.vue   # bare slot for /admin/login and /404
    ├── components/
    │   ├── CardItem.vue
    │   ├── HeroBanner.vue          # accepts cover prop; encodes URL via CSS.escape + url("…")
    │   ├── ArticleHero.vue
    │   ├── MarkdownView.vue        # v-html + onMounted decoration; idempotent via [data-decorated] attr
    │   ├── TagPicker.vue
    │   ├── CoverUploader.vue       # file input + preview + POST /covers; emits update:cover
    │   └── form/
    │       ├── BaseInput.vue
    │       ├── BaseTextarea.vue
    │       └── BaseSelect.vue
    ├── composables/
    │   ├── useApi.ts               # tiny ergonomic wrapper: returns data or throws LGError
    │   ├── useHighlight.ts         # registers a curated language set on a single hljs instance (deduped via pnpm overrides)
    │   └── useAuthGuard.ts
    ├── styles/
    │   ├── tokens.css              # :root vars (colors, spacing); replaces today's --bg/--panel/...
    │   ├── global.css              # body resets, typography
    │   ├── article.css             # .article-prose, .markdown-body, .code-card
    │   ├── admin.css
    │   └── home.css
    ├── assets/
    ├── types/
    │   ├── env.d.ts
    │   ├── shims-vue.d.ts
    │   └── api.ts                  # re-exports paths/components from api/schema.d.ts
    └── tests/
        ├── setup.ts                # @vue/test-utils stubs, MSW handlers using openapi-typescript types
        └── unit/
            ├── stores.spec.ts
            └── views.spec.ts
```

### Pinia stores

| store | state | actions |
| --- | --- | --- |
| auth (defineStore('auth', () => {...})) | token: Ref<string \| null> = ref(null)  // persisted; user: Ref<components['schemas']['UserPublic'] \| null> = ref(null)  // persisted; loading: Ref<boolean>; isAuthenticated = computed(() => !!token.value); isAdmin = computed(() => user.value?.role === 'admin') | login(username, password) -> calls api/modules/auth.login, sets token+user, returns user; logout() -> clears token+user, routes to /; loadMe() -> if token, calls /auth/me; on 401 clears state; $reset() -> manually nulls everything (Pinia 3 setup stores have no auto-reset) |
| cards (defineStore('cards', () => {...})) | list: Ref<components['schemas']['CardPublic'][]> = ref([]); detail: Ref<components['schemas']['CardDetail'] \| null> = ref(null); tags: Ref<string[]> = ref([]); loading: Ref<boolean>; filters: reactive({category: null, group: null, tag: null, q: '', includeArchived: false}) | fetchList() -> sets list from listCards(filters); fetchDetail(slug) -> sets detail; fetchTags() -> sets tags; createCard(payload) -> POST then refresh list; updateCard(id, payload) -> PUT then patch list/detail; archiveCard(id, archived) -> PATCH; on success mutate row in place (optimistic, fixes today's full-reload bug); deleteCard(id); setFilter(k, v); $reset() |
| ui (defineStore('ui', () => {...})) | keyword: Ref<string> = ref('')  // debounced via @vueuse/core useDebounceFn 200ms before mirroring into cards.filters.q; theme: Ref<'dark' \| 'light'> = ref('dark')  // persisted; sidebarCollapsed: Ref<boolean> | setKeyword(v); toggleTheme(); $reset() |

### Routes and guards

| path | name | component | meta | guard |
| --- | --- | --- | --- | --- |
| / | home | () => import('@/views/HomeView.vue') | {title: 'Link Garden — 是个人博客，也是技术收藏展厅', layout: 'public'} | none |
| /card/:slug | card-detail | () => import('@/views/DetailView.vue') | {title: 'Article · Link Garden', layout: 'public'} | none — fetchDetail handles 404 by routing to NotFoundView |
| /admin/login | admin-login | () => import('@/views/admin/LoginView.vue') | {title: '登录 · Link Garden', layout: 'blank'} | redirectIfAuthenticated -> /admin |
| /admin | admin-list | () => import('@/views/admin/AdminListView.vue') | {title: '后台 · 文章管理', requiresAdmin: true, layout: 'admin'} | requireAdmin (router.beforeEach checks auth.isAdmin; if false, push /admin/login?next=…) |
| /admin/publish | admin-publish | () => import('@/views/admin/AdminPublishView.vue') | {title: '后台 · 编辑/新增', requiresAdmin: true, layout: 'admin'} | requireAdmin |
| /:pathMatch(.*)* | not-found | () => import('@/views/NotFoundView.vue') | {title: '404 · Link Garden', layout: 'blank'} | none |

### Composables and shared utils
(see frontend_layout above; A keeps composables minimal)


### Reusable components
(per frontend_layout)


## Migration plan

backend/scripts/migrate_from_json.py — one-shot, idempotent CLI script.

USAGE: `uv run python -m scripts.migrate_from_json --json-file ../data/cards.json --notes-dir ../content/notes --owner-username admin [--dry-run]`

BEHAVIOR (single async transaction per card):
1. Bootstrap: ensure DB schema is current (`alembic upgrade head` is the operator's responsibility and runs before this script). Open AsyncSession.
2. Resolve owner: SELECT users WHERE username=owner_username. If missing, abort with a clear message ("seed admin first via alembic 0001 or scripts/create_admin.py").
3. Parse cards.json. For each entry, in legacy file order:
   a. legacy_id = entry['id']. Look up SELECT cards WHERE slug=legacy_id (no archived filter — old data is the snapshot). If found, log "skip (already migrated)" and CONTINUE. This is the idempotency key.
   b. Mint new_id = uuid4().
   c. Map fields: title=entry['title']; category=entry['category']; group=None (legacy lacks it); summary=entry.get('summary',''); cover=entry.get('cover') or None; tags=entry.get('tags') or []; archived=entry.get('archived', False); created_at=parse('YYYY-MM-DD' + 'T00:00:00+00:00') from entry['created_at']; updated_at=created_at; author_id=owner.id.
   d. If category=='external': url=entry['url']; body=None.
   e. If category=='local': md_path = notes_dir / Path(entry['markdown']).name; raise if missing; body = md_path.read_text(encoding='utf-8'); url=None. Markdown body stored RAW (H1 not stripped — strip happens at render time).
   f. INSERT card row. On UNIQUE-violation (partial slug index), suffix '-imported' and retry once; abort otherwise.
4. After all entries, log summary: inserted=N, skipped=M, errors=K. Exit 0 only if errors=0.
5. --dry-run: prints the same plan without committing (rolls back the outer transaction).

IDEMPOTENCY: keyed solely on slug uniqueness within non-archived. Re-running on a populated DB produces 0 inserts. Operator is told NOT to re-run after edits — to force re-import, manually `DELETE FROM cards WHERE slug='<x>'` first.

ROLLBACK PROCEDURE (manual; documented in docs/refactor/migration-runbook.md):
- For aiosqlite: `mv linkgarden.db linkgarden.db.bak && alembic upgrade head` recreates an empty schema; restore the JSON snapshot to data/cards.json and revert the systemd unit to the legacy Flask deploy. Old data/cards.json + content/notes/ are preserved as a read-only snapshot per the locked decisions.
- For Postgres swap: `pg_restore` the pre-migration dump.

The legacy data/cards.json and content/notes/*.md remain on disk untouched after migration. After a successful migration + verification, the deploy script chmods them to 0444 to prevent accidental writes. Orphan note (multi-agent-super-universe-draft.md) is logged but NOT inserted — it lives in /var/log/linkgarden as a one-time WARN.

VERIFICATION (run after migration):
- `pytest tests/test_migrate_from_json.py` exercises the script against a fresh in-memory DB with a fixture cards.json.
- A spot-check command `uv run python -m scripts.spot_check` lists card counts by category and tag distribution; operator compares to the legacy `/api/cards` snapshot before flipping nginx to the new backend.

## Deployment plan

SINGLE HOST. Two systemd units (backend gunicorn + nothing for frontend; nginx serves the static dist directly). pnpm for frontend, uv for backend.

LAYOUT ON HOST:
/srv/projects/link-garden/
├── backend/          # git checkout; .venv lives here (uv-managed)
│   ├── .env          # secrets (chmod 600, owner linkgarden)
│   ├── linkgarden.db (or pg connection)
│   └── static/covers/
└── frontend/         # plain rsynced dist; no node_modules in prod

deploy/systemd/linkgarden-backend.service:
[Unit]
Description=Link Garden FastAPI backend
After=network.target

[Service]
Type=notify
User=linkgarden
Group=linkgarden
WorkingDirectory=/srv/projects/link-garden/backend
EnvironmentFile=/srv/projects/link-garden/backend/.env
ExecStartPre=/srv/projects/link-garden/backend/.venv/bin/alembic upgrade head
ExecStart=/srv/projects/link-garden/backend/.venv/bin/gunicorn app.main:app \\
  -k uvicorn.workers.UvicornWorker \\
  -w 2 \\
  --bind 127.0.0.1:5001 \\
  --proxy-headers --forwarded-allow-ips=127.0.0.1 \\
  --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/srv/projects/link-garden/backend/static /srv/projects/link-garden/backend/linkgarden.db

[Install]
WantedBy=multi-user.target

NOTES on the unit: workers=2 is the right starting point (UvicornWorker is async; SQLite serializes writes anyway). ExecStartPre runs alembic upgrade head every restart — Alembic is no-op on idempotent revisions. systemd's Type=notify works with uvicorn workers via gunicorn's notify support.

deploy/nginx/linkgarden.conf (sketch):
server {
  listen 443 ssl http2;
  server_name linkgarden.example.com;
  ssl_certificate /etc/letsencrypt/live/.../fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/.../privkey.pem;

  root /srv/projects/link-garden/frontend;
  index index.html;
  client_max_body_size 6m;  # > 5MB cover limit + slop

  location / { try_files $uri $uri/ /index.html; }

  location /api/ {
    proxy_pass http://127.0.0.1:5001;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }

  location /covers/ {
    alias /srv/projects/link-garden/backend/static/covers/;
    expires 7d;
    add_header Cache-Control \"public, immutable\";
    access_log off;
  }
}

DEPLOY STEPS (script in scripts/deploy.sh):
1. Backend: `git pull && cd backend && uv sync --no-dev` on host. systemctl restart linkgarden-backend (ExecStartPre runs alembic upgrade head before gunicorn binds).
2. Frontend: locally `cd frontend && pnpm install --frozen-lockfile && pnpm gen:api && pnpm build`. Then `rsync -avz --delete frontend/dist/ user@host:/srv/projects/link-garden/frontend/`. nginx auto-picks up new files; no reload needed.
3. systemctl reload nginx is required only when deploy/nginx/linkgarden.conf itself changes.
4. Health check: `curl -fsS https://linkgarden.example.com/api/health` after step 1; `curl -fsS https://linkgarden.example.com/` after step 2.
5. Cutover from legacy: rename current legacy systemd unit (linkgarden.service) to linkgarden-legacy.service.disabled, then enable+start linkgarden-backend.service. Roll back is a swap of those two unit names + restoring data/cards.json from snapshot.

ALEMBIC AS DEPLOY STEP: `alembic upgrade head` runs in ExecStartPre with the same .env that gunicorn uses. Alembic 0001 ships an op.bulk_insert that seeds the admin user from LG_ADMIN_USERNAME / LG_ADMIN_PASSWORD when no users exist (uses bcrypt-hashed password computed in the migration script — settings imported inside the upgrade() function, never at module level).

CI (.github/workflows; deferred but planned): on push, run `uv run ruff check`, `uv run pyright`, `uv run pytest`, `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm gen:api && git diff --exit-code openapi/schema.json src/api/schema.d.ts`.

## Risks and mitigations

| risk | mitigation |
| --- | --- |
| SQLite single-writer bottleneck under concurrent admin writes. | WAL + busy_timeout=5000; gunicorn workers ≤ 2; admin workload is single-tenant. Postgres swap is one DATABASE_URL change away (asyncpg already declared as optional dep). |
| Alembic env.py async setup lands wrong (#1 cause of 'alembic upgrade head' hangs). | Use the cookbook async pattern: connection.run_sync(do_migrations) with render_as_batch=True for sqlite; explicitly `from app.models import *` in env.py to populate target_metadata. |
| Pydantic v2 / SQLAlchemy 2 typed Mapped[] migration produces silent type errors that pyright flags but humans miss. | pyright in strict mode on app/, basic on tests/, gated in pre-commit; commits blocked until clean. |
| JWT secret leak via accidental commit or env dump. | .env in .gitignore; .env.example carries placeholders only; secret read by pydantic-settings at import time so a missing/short secret crashes uvicorn loudly before the first request. |
| nh3 strips legitimate markdown output (e.g. footnote refs, custom span classes). | Allowlist explicitly enumerated in services/markdown.py with tests covering: headings, inline code, fenced code with language, tables, blockquote, links (http/https/mailto only), images (http/https), strong/em, footnotes via mdit-plugin. Tests pin the expected sanitized output. |
| openapi-typescript codegen drifts vs server, frontend types lie. | CI step: `pnpm gen:api && git diff --exit-code openapi/schema.json src/api/schema.d.ts` fails the pipeline if not regenerated; openapi/schema.json and src/api/schema.d.ts both committed. |
| Legacy /api/* 308 shim breaks clients that don't preserve body across redirects (older curl, some fetch polyfills). | Frontend cuts over to /api/v1 in the same release that adds the shim; shim is for the brief window where the live frontend still hits /api/*. Documented removal date in CHANGELOG. |
| Cover upload abuse — large files, MIME spoof, decompression bombs. | 5 MiB hard cap (read-stream + early abort); MIME from Content-Type + magic-byte verify via Pillow.open(BytesIO(payload)).verify(); dimension cap 4096×4096; only image/{png,jpeg,webp}; admin-only endpoint behind JWT. |
| Markdown rendering on every /cards/{slug} request burns CPU. | @lru_cache(maxsize=128) keyed on (card.id, updated_at) inside services/cards.get_card_by_slug; cache invalidates naturally on update because updated_at flips. |
| Partial unique index on slug is not portable to all SQLite < 3.8. | pyproject pins python>=3.12 and aiosqlite which bundles modern SQLite (3.40+); deploy host check enforces sqlite3 ≥ 3.8 (covered by Ubuntu 22.04+ default). |
| Pinia 3 setup stores have no auto $reset, easy to leak state on logout. | Each store explicitly defines a $reset action that nulls/resets every ref it returns; auth.logout() calls it; tests assert post-logout state. |
| highlight.js double-bundling (md-editor-v3 ships its own copy). | pnpm overrides pin a single highlight.js version; useHighlight.ts registers only the languages we use (ts, js, py, sh, json, html, css, vue, sql, md) keeping the bundle ≤50KB. |
| Vite dev server can't reach FastAPI without proxy (today's bug). | vite.config.ts ships server.proxy['/api'] = http://127.0.0.1:5001 from day one; documented in frontend/README. |
| Migration script run twice creates duplicates if slug index missing. | Script wraps each card insert in a savepoint; partial unique index on slug is the safety net; idempotency check is the primary defense (SELECT by slug before insert). |
| WAL-mode SQLite on NFS or networked filesystem corrupts. | Deploy onto local disk (/srv) only; explicit note in deploy/README. Docker volume must be a local bind mount, not an NFS share. |
| OAuth2/JWT token in localStorage is XSS-readable. | Sanitization is server-side (nh3); no third-party scripts loaded; CSP header (set in nginx) restricts script sources to 'self'. Long-term move to httpOnly cookies is documented but deferred. |