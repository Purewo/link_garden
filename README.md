# Link Garden / 净界

A personal content garden. Two content types share one storefront:

- **External** cards bookmark off-site work. Click jumps to the source URL; nothing is stored locally.
- **Local** cards are Markdown authored in-site. Rendered, sanitized, and served from the same backend.

The site is a single-admin blog, not a multi-tenant platform. Stack and decisions are tuned for that shape.

---

## Stack

### Backend (`backend/`)

- Python 3.12, FastAPI 0.118, async everywhere
- SQLAlchemy 2.0 (async) + Alembic 1.14, SQLite (aiosqlite) in dev, PostgreSQL (asyncpg) one DSN away in prod
- Pydantic 2.11 + pydantic-settings for typed schemas and `.env` loading
- PyJWT 2.10 (HS256, pinned), bcrypt 4.x for auth
- markdown-it-py + mdit-py-plugins + linkify-it-py for rendering, nh3 for sanitization
- Pillow 11+ for cover validation, structlog for JSON logs
- Served by gunicorn 23 + uvicorn workers behind nginx
- Managed by **uv** (lockfile committed, `uv sync --frozen` on every checkout)

### Frontend (`frontend/`)

- Vue 3.5 (`<script setup>`), TypeScript 5.7 strict, Vite 7
- Pinia 3 setup stores + `pinia-plugin-persistedstate`, vue-router 4
- API client generated from FastAPI's `/openapi.json` via `openapi-typescript` + `openapi-fetch` (no axios)
- `md-editor-v3` for authoring, `highlight.js` for read-side code blocks
- ESLint 9 flat config + Prettier 3, Vitest 3 for tests
- Managed by **pnpm** (lockfile committed, Node 20.19+/22 LTS)

### Repo layout

```
LinkGarden/
├── backend/                 FastAPI app (src layout, uv-managed)
├── frontend/                Vue 3 SPA (pnpm-managed)
├── deploy/                  systemd unit, nginx config, env template
├── scripts/                 deploy.sh, codegen wrapper
├── docs/
│   ├── refactor/            ADRs, briefs, migration runbook
│   └── architecture/        spec + diagrams
├── data/                    FROZEN legacy snapshot (chmod a-w after migration)
├── content/notes/           FROZEN legacy snapshot
├── README.md                this file
└── CLAUDE.md                handoff notes for the AI partner
```

The repo is a logical monorepo, not a pnpm workspace — backend and frontend have independent toolchains and CI matrices.

---

## Dev loop

### Prerequisites

- Python 3.12 with [uv](https://github.com/astral-sh/uv) installed (`pipx install uv` or the project recommends `uv tool install`).
- Node 20.19+ or 22 LTS with [pnpm](https://pnpm.io/) 9.
- For sanitizer audits and cover validation, no system libs beyond Pillow's own wheels are required.

### Bootstrap the backend

```bash
cd backend
cp .env.example .env                  # then fill JWT_SECRET, LG_ADMIN_PASSWORD
uv sync                               # creates .venv from uv.lock
uv run alembic upgrade head           # creates tables + seeds admin from .env
uv run uvicorn app.asgi:app --host 127.0.0.1 --port 5001 --reload
```

The backend listens on `127.0.0.1:5001`. `GET /api/health` and `GET /api/v1/health` should both return `{"ok": true}`.

### Bootstrap the frontend

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm gen:api                          # regenerate types from the running backend
pnpm dev                              # http://localhost:5173, proxies /api to :5001
```

`pnpm gen:api` tries the running backend at `127.0.0.1:5001` first and falls back to the committed snapshot under `frontend/openapi/schema.json`.

### Useful commands

| Command (in `backend/`) | What it does |
|---|---|
| `uv run pytest` | full backend test suite |
| `uv run ruff check . && uv run ruff format .` | lint + format |
| `uv run pyright` | strict types on `src/app`, basic on tests |
| `uv run alembic revision --autogenerate -m "msg"` | new migration |
| `uv run python -m scripts.seed_admin` | rotate the admin password interactively |
| `uv run python -m scripts.migrate_from_json --json-file ../data/cards.json --notes-dir ../content/notes --owner-username admin` | one-shot legacy import |

| Command (in `frontend/`) | What it does |
|---|---|
| `pnpm dev` | Vite dev server with `/api` proxy |
| `pnpm build` | production build to `frontend/dist/` |
| `pnpm test` | Vitest in watch mode (`-- --run` for one-shot) |
| `pnpm typecheck` | `vue-tsc --noEmit` |
| `pnpm lint` | ESLint flat config (max-warnings 0) |
| `pnpm gen:api` | regenerate `schema.json` + `schema.d.ts` from backend |

---

## API contract (overview)

Everything routable lives under `/api/v1`. `GET /api/health` is mounted directly on the app so external monitors stay version-stable. Failures use the envelope `{"ok": false, "error": <human>, "code": <machine>}`; successes are the bare resource. The machine code list is frozen and never localized. Full details: [`docs/architecture/`](docs/architecture/) and the spec in [`docs/refactor/phase2-architecture.md`](docs/refactor/phase2-architecture.md) §3.5.

```
GET    /api/health
GET    /api/v1/health
POST   /api/v1/auth/login
GET    /api/v1/auth/me                          (Bearer)
GET    /api/v1/cards
GET    /api/v1/cards/{slug}
POST   /api/v1/cards                            (admin)
PUT    /api/v1/cards/{id}                       (admin)
PATCH  /api/v1/cards/{id}/archive               (admin)
DELETE /api/v1/cards/{id}                       (admin)
GET    /api/v1/tags
POST   /api/v1/covers                           (admin)
ANY    /api/{path}        (legacy 308 shim, one release)
```

Legacy `/api/*` (non-`v1`) paths return `308 Permanent Redirect` to the v1 equivalent for one release after cutover, then disappear. Each hit is logged at WARN so operators can verify zero traffic before removal.

---

## Identity model

- `cards.id` is an immutable `uuid4` primary key. Mutating endpoints address cards by `id`.
- `cards.slug` is a regenerable URL handle, unique only among non-archived rows via a partial unique index. Read endpoints address cards by `slug`.
- Legacy `cards.json` ids become the initial `slug` values verbatim so existing public URLs keep resolving.

---

## Auth

JWT HS256, secret loaded from `JWT_SECRET`, 12-hour TTL, decoder pinned to `algorithms=["HS256"]`. Bearer token in the `Authorization` header. No refresh tokens in v1; on `401`, the SPA clears the persisted token and (only when the route requires admin) redirects to `/admin/login?next=...`. The admin row is seeded by Alembic data migration `0002_seed_admin` when no users exist, reading `LG_ADMIN_USERNAME` and `LG_ADMIN_PASSWORD` from the environment.

---

## Markdown pipeline

Markdown is rendered **server-side** on every write and persisted to `cards.body_html`:

1. Strip a leading `# H1` line (the title is owned by the card row).
2. Parse with markdown-it-py (GFM-like, `html: false`, linkify, footnotes, tables, task-lists).
3. Annotate code fences with `data-language="<lang>"` for client highlighting.
4. Render to HTML.
5. Sanitize through nh3 with an explicit tag/attribute allowlist; `a` gets `rel="noopener noreferrer nofollow"`.

Reads serve the cached HTML directly. The client trusts it via `v-html`; no DOMPurify on the client. When the allowlist changes, an Alembic data migration re-renders every local card.

---

## Cover uploads

`POST /api/v1/covers` is multipart, admin-only, accepts `image/png|jpeg|webp` only, max 5 MiB, max 4096×4096 px. Content-Type is verified by magic-byte sniff and `Pillow.verify()` re-open. Writes are atomic (`.tmp` + `os.replace`) into `<STATIC_DIR>/covers/<card_id>.<ext>`; siblings with other extensions for the same `card_id` are unlinked. The endpoint updates `cards.cover` in the same transaction and returns the refreshed `CardRead`. In prod, nginx `alias /covers/` serves the directory directly.

---

## Deployment

Single Ubuntu host, single `linkgarden.service` systemd unit running `gunicorn -k uvicorn.workers.UvicornWorker -w 2`. `alembic upgrade head` runs as `ExecStartPre`; failure aborts the unit start so the previous binary keeps running. nginx terminates TLS, serves the SPA from `dist/`, proxies `/api/` to `127.0.0.1:5001`, and `alias`-serves `/covers/`. Full canonical configs live in `deploy/` and the runbook in [`docs/refactor/deploy-runbook.md`](docs/refactor/deploy-runbook.md).

SQLite runs in WAL mode with `foreign_keys=ON` and `busy_timeout=5000`, set by a SQLAlchemy connect listener. Postgres swap is a one-line `DATABASE_URL` change.

---

## CI

Three workflows in `.github/workflows/`:

- **`backend.yml`** — `uv sync --frozen`, `ruff check`, `ruff format --check`, `pyright`, `alembic upgrade head`, `pytest`.
- **`frontend.yml`** — `pnpm install --frozen-lockfile`, `pnpm gen:api` then `git diff --exit-code` for codegen drift, `eslint`, `vue-tsc`, `vitest --run`, `pnpm build`.
- **`contract.yml`** — boots the FastAPI app, exports `/openapi.json`, diffs against the committed `frontend/openapi/schema.json` and regenerates `schema.d.ts` to confirm no drift.

Runtime secrets (`JWT_SECRET`, `LG_ADMIN_PASSWORD`, etc.) are **not** in CI. The workflows use throwaway values; production secrets live in the deploy host's `/etc/linkgarden/linkgarden.env`.

---

## Pre-commit hooks

```bash
pip install pre-commit              # or `uv tool install pre-commit`
pre-commit install
pre-commit run --all-files
```

Hooks: trailing whitespace, EOF, merge conflicts, large files, YAML/TOML/JSON syntax, private-key + gitleaks secret scanning, ruff (lint + format) on backend, ESLint + Prettier on frontend, and a guard that refuses hand-edits to the generated `schema.d.ts`. Heavy checks (`pyright`, `vue-tsc`) are gated to the `manual` stage; they run in CI on every push.

---

## Legacy data

`data/cards.json` and `content/notes/*.md` are the pre-refactor snapshot. The new backend never writes to either tree; after migration, the deploy script runs `chmod -R a-w` on both. The one-shot importer is `backend/scripts/migrate_from_json.py` — idempotent on slug, supports `--dry-run` and `--report-html` for a sanitizer audit. Rollback procedure lives in [`docs/refactor/migration-runbook.md`](docs/refactor/migration-runbook.md).

---

## Diagrams

- [`docs/architecture/diagrams/system-context.md`](docs/architecture/diagrams/system-context.md) — request flow from browser → nginx → FastAPI → SQLite.
- [`docs/architecture/diagrams/backend-modules.md`](docs/architecture/diagrams/backend-modules.md) — feature-modular tree with router → service → repository discipline.
- [`docs/architecture/diagrams/frontend-modules.md`](docs/architecture/diagrams/frontend-modules.md) — feature folders, shared kit, Pinia stores.

---

## License & ownership

Single-admin personal project. No third-party authors; no contributor agreement. See `PROJECT_NOTES.md` for the long-running design log.
