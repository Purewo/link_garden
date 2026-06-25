# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Project

Link Garden / 净界 — a single-admin personal content site. Two card categories share one storefront:

- `external` — bookmark cards that jump to off-site URLs. No body stored locally.
- `local` — site-authored Markdown rendered, sanitized, and served from the same backend.

Design language: dark, cool blue/cyan-purple, restrained, lightly cyberpunk. Several layout decisions are explicitly ruled out in `PROJECT_NOTES.md` (the "已明确否掉 / 需要避免的坑" sections). Re-read it before redesigning page layouts.

Authoritative architecture spec lives in `docs/refactor/phase2-architecture.md`. When the spec contradicts this file, **the spec wins** — patch this file to match.

---

## Stack at a glance

### Backend (`backend/`)

- Python 3.12, FastAPI 0.118, async everywhere
- SQLAlchemy 2.0 async, Alembic 1.14, SQLite (aiosqlite) dev / PostgreSQL (asyncpg) prod-swap
- Pydantic 2.11 + pydantic-settings, PyJWT (HS256 pinned), bcrypt 4.x
- markdown-it-py + mdit-py-plugins + linkify-it-py, nh3 sanitizer, Pillow 11+
- structlog JSON logs; gunicorn + uvicorn workers behind nginx
- Tooling: **uv** for deps/venv, **ruff** lint+format, **pyright** strict on `src/app`

### Frontend (`frontend/`)

- Vue 3.5 `<script setup>`, TypeScript 5.7 strict, Vite 7
- Pinia 3 setup stores + `pinia-plugin-persistedstate`, vue-router 4
- API client: `openapi-typescript` + `openapi-fetch` (no axios, no `@tanstack/vue-query` in v1)
- `md-editor-v3` for authoring, `highlight.js` for read-side highlighting
- ESLint 9 flat + Prettier 3, Vitest 3
- Tooling: **pnpm** (Node 20.19+/22 LTS)

---

## Commands

### Backend (in `backend/`)

```bash
uv sync                                   # install/lock deps
uv run uvicorn app.asgi:app --reload      # dev server on 127.0.0.1:5001
uv run alembic upgrade head               # migrate + seed admin
uv run alembic revision --autogenerate -m "msg"
uv run pytest                             # full test suite
uv run pytest tests/integration/test_cards.py -q
uv run ruff check . && uv run ruff format .
uv run pyright
uv run python -m scripts.seed_admin       # rotate admin password (TTY)
uv run python -m scripts.migrate_from_json \
  --json-file ../data/cards.json --notes-dir ../content/notes \
  --owner-username admin --dry-run
```

### Frontend (in `frontend/`)

```bash
pnpm install --frozen-lockfile
pnpm dev                                  # http://localhost:5173 with /api proxy to :5001
pnpm gen:api                              # regenerate schema.json + schema.d.ts
pnpm typecheck                            # vue-tsc --noEmit
pnpm lint                                 # ESLint flat (--max-warnings 0)
pnpm test -- --run                        # one-shot Vitest
pnpm build                                # production build to dist/
```

### Deploy host (Ubuntu, single host)

```bash
systemctl status  linkgarden.service
systemctl restart linkgarden.service
journalctl -u linkgarden.service -n 200 --no-pager
nginx -t && systemctl reload nginx
```

Tests, lint, and typecheck are the verification floor — don't ship without running them. CI re-runs everything (`.github/workflows/{backend,frontend,contract}.yml`).

---

## Architecture (short tour)

Long-form: `docs/refactor/phase2-architecture.md`. Diagrams: `docs/architecture/diagrams/`.

### Backend layout

`src/app/` is split into `core/` (config, db, security, errors, logging, types), `services/` (pure helpers like `markdown.py`), and `features/<domain>/` slices. Every feature owns its own `models.py` / `schemas.py` / `repo.py` / `service.py` / `routes.py`. Discipline:

- **Routers ≤ 30 LOC.** No SQL, no business logic. They wire DI and call a service.
- **Services own logic.** No SQL there either; they call repository methods.
- **Repositories own SQL.** All `select`/`insert`/`update`/`delete` lives in `<feature>/repo.py`.
- **`AsyncSession`** is one-per-request via `core.db.get_session`. `expire_on_commit=False`; services always re-`SELECT` after writes to avoid stale ORM rows.

### Identity model

- `cards.id` is an immutable `uuid4` PK. Mutating endpoints address cards by `id`.
- `cards.slug` is a regenerable URL handle, unique only among non-archived rows (partial unique index). Read endpoints address cards by `slug`.
- Legacy `cards.json` ids carry forward as the initial slug so existing URLs keep resolving.

### Auth

JWT HS256, `JWT_SECRET` from env, 12-hour TTL, decoder pinned to `algorithms=["HS256"]`. Bearer token in `Authorization`. No refresh tokens. The admin row is seeded by Alembic data migration `0002_seed_admin` from `LG_ADMIN_USERNAME` / `LG_ADMIN_PASSWORD` when no users exist (idempotent). Rotate via `scripts/seed_admin.py`.

### Markdown

`services/markdown.render_markdown(md)` is pure: H1 strip → markdown-it-py (`html=False`, linkify, footnotes, deflist, tasklists, tables) → code-fence `data-language` annotation → render → nh3 sanitize with an explicit allowlist. The result is persisted to `cards.body_html` on every write that touches `body` or `category`. Reads serve the cached HTML directly. The client trusts it via `v-html` — **never add DOMPurify on the client**.

### Cover uploads

`POST /api/v1/covers` is multipart, admin-only. Validates Content-Type, size (≤ 5 MiB streamed), magic bytes, `Pillow.verify()` + re-open for dims (max 4096, min 200), derives ext from the sniffed type, atomic write `.tmp` + `os.replace` into `<STATIC_DIR>/covers/<card_id>.<ext>`, unlinks old-ext siblings, updates `cards.cover` in the same transaction, returns refreshed `CardRead`. In prod, nginx `alias /covers/` serves the directory directly.

### Error envelope

Failures: `{"ok": false, "error": <human>, "code": <machine>, "detail"?: [...]}`. Successes are the bare resource. The only success bodies with `ok: true` are `/health` and `CoverUploadResponse`. Machine codes are frozen (see `core/errors.py`); the frontend branches on `code` so they are **never localized**.

### Legacy `/api/*` shim

A catch-all in `main.py` registered after the v1 router returns `308 Permanent Redirect` to `/api/v1/<path>` for one release after cutover. Each hit logs `legacy_api_hit` at WARN. Removal date is recorded in `CHANGELOG.md` once the shim is sunset.

### Frontend layout

`src/features/<domain>/` slices mirror the backend. `shared/` holds the API client (`shared/api/client.ts` wraps `openapi-fetch` with auth middleware), composables (`useAsync`, `useDebounce`, `useEnhanceCodeBlocks`, `useToast`), Base UI primitives, utils, and types. Views call **per-feature wrappers** (`features/cards/api.ts`, etc.), never `api` directly. Pinia setup stores live next to their feature; `auth` and `ui` persist via `pinia-plugin-persistedstate` (`token`, `user`, `theme`, `sidebarCollapsed`).

The router has a single global `beforeEach` that runs `setTitle` → `requireAdmin` (when `meta.requiresAdmin`) → `redirectIfAuthed` (when `meta.anonOnly`). Layouts (`PublicLayout`, `AdminLayout`, `BlankLayout`) are switched in `App.vue` from `route.meta.layout`.

---

## Things that bite (must-read before patching)

1. **Routers don't touch the DB.** Add a service method instead. If you find yourself writing `session.execute(...)` outside a `repo.py`, stop.
2. **`expire_on_commit=False` means stale ORM objects after commit.** Always return the result of an explicit re-`SELECT` from service writes.
3. **Slug uniqueness is partial (only among non-archived).** When testing archive + re-publish, expect the partial index to allow the new live slug to coexist with the archived twin.
4. **PUT preserves omitted fields.** `CardUpdate` uses `model_dump(exclude_unset=True)` semantics. The legacy "PUT silently wipes summary/cover" behavior is fixed and must not regress.
5. **Markdown is rendered on writes.** Read paths must not call `render_markdown`. Re-rendering on schema/sanitizer change is an Alembic data migration.
6. **Cover ext is sniffed, never trusted from `file.filename`.** Atomic write asserts the resolved path stays inside `<STATIC_DIR>/covers/`.
7. **JWT decoder is pinned.** `algorithms=["HS256"]` only; `none` must never be accepted. `JWT_SECRET` must be ≥ 32 chars; settings init crashes uvicorn loudly otherwise.
8. **CORS only in `APP_ENV='dev'`.** Prod is same-origin via nginx.
9. **`pnpm gen:api && git diff --exit-code`** is a CI gate. After any backend OpenAPI-affecting change, regenerate and commit `frontend/openapi/schema.json` + `src/shared/api/schema.d.ts`.
10. **`useEnhanceCodeBlocks` is idempotent.** It marks `data-hl-done="1"` and refuses to re-process. The legacy double-wrap bug must not regress.
11. **No DOMPurify on the client.** Server sanitization (nh3 + explicit allowlist) is the only sanitizer; the client trusts `body_html` directly.
12. **Pinia 3 setup stores have no auto-`$reset`.** Every store defines an explicit `$reset` action. `auth.logout()` calls it.
13. **`auth:invalidated` event** is dispatched by the API middleware on every 401. `App.vue` listens once on mount; the client never imports the router.
14. **`category` switch wipes the stale field** (`url` ↔ `body`) and re-renders `body_html`. Test this path when touching `cards/service.py`.
15. **Legacy snapshot is read-only.** The new backend never writes to `data/` or `content/notes/`. Both trees are `chmod -R a-w` post-migration.

---

## CI workflows

`.github/workflows/`:

- `backend.yml` — `uv sync --frozen`, `ruff check`, `ruff format --check`, `pyright`, `alembic upgrade head`, `pytest`. Throwaway env vars only; production secrets are not present.
- `frontend.yml` — `pnpm install --frozen-lockfile`, `pnpm gen:api` then `git diff --exit-code`, ESLint, vue-tsc, Vitest, build, upload `dist/` on main.
- `contract.yml` — boots the FastAPI app, exports `/openapi.json`, compares against committed `frontend/openapi/schema.json`, regenerates `schema.d.ts` to confirm no drift.

Production secrets (`JWT_SECRET`, `LG_ADMIN_PASSWORD`, anything else) live in the deploy host's `/etc/linkgarden/linkgarden.env` and reference org-level GitHub secrets symbolically if/when a deploy workflow is added. CI uses placeholder values; never paste real secrets into the workflow files.

---

## Pre-commit

`.pre-commit-config.yaml` runs trailing-whitespace, EOF, merge-conflict, large-file, YAML/TOML/JSON syntax, private-key + gitleaks secret scanning, ruff (lint + format) on backend, ESLint + Prettier on frontend, and a guard that refuses hand-edits to the generated `schema.d.ts`. Heavy checks (`pyright`, `vue-tsc`) are gated to the `manual` stage and run in CI.

```bash
pre-commit install
pre-commit run --all-files
pre-commit run --hook-stage manual --all-files   # pyright + vue-tsc
```

---

## Where to read more

- `docs/refactor/phase2-architecture.md` — authoritative spec, including the API contract (§3.5), Pydantic schemas (§3.4), error codes (§3.9), and the Phase 3 work breakdown (§9).
- `docs/refactor/phase1-brief.md` — the constraints carried over from the legacy app.
- `docs/architecture/diagrams/` — system context, backend modules, frontend modules.
- `PROJECT_NOTES.md` — long-running design log; honor the "已明确否掉 / 需要避免的坑" sections.
