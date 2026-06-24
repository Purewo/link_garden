# Phase 1 Brief — LinkGarden refactor

## 1. What we have today

**Backend.** A single-file Flask 3.1app (`backend/app.py`,215 LOC) exposes eight `/api` routes — health, list, detail, tags, publish, update, archive, delete. Storage is two flat artifacts: `data/cards.json` (full array rewritten on every mutation) and `content/notes/<id>.md` per local card. Markdown is rendered per-request with python-markdown (fenced_code, tables) after stripping a leading `# H1`. There is no auth, no rate limiting, no schema validation library, no tests, no concurrency control, and CORS is wide-open. Prod runs the Flask dev server under systemd behind nginx, despite gunicorn being declared and PROJECT_NOTES warning against it.

**Frontend.** Vue 3 + Vite SPA with four flat routes (`/`, `/card/:id`, `/admin`, `/admin/publish`), a single `App.vue` shell that branches chrome by route, and one~2400-line global stylesheet (`src/assets/style.css`) with several dead layout subsystems. Data flows via axios to `/api/*` (relative — no Vite proxy is configured). Article HTML is rendered with `v-html` and post-processed by a custom `decorateCodeBlocks` pass plus highlight.js. Two unused components (Vite scaffold + Milkdown experiment) and `@milkdown/*`, `marked`, `marked-highlight`ship in `package.json` unused. The hero background is a hardcoded external signed URL — the exact anti-pattern PROJECT_NOTES forbids.

## 2. Data shapes that must survive

| Shape | Key fields | Invariants that must not change |
|---|---|---|
| **Card** | `id` (slug), `title`, `category`∈ {`external`,`local`}, `summary`, `tags[]`, `cover`, `created_at` (YYYY-MM-DD), `archived` (bool, may be missing on legacy entries), `url?` (external), `markdown?` (local) | `id` unique; collisions resolved with `-2`,`-3`; `external`⇒`url`, `local`⇒`markdown` file exists; `archived` read with `.get('archived', False)` |
| **CardDetail** | Card + `content` (raw MD), `content_html` (rendered) — local only | First-line `# H1` stripped before render; `content_html` treated as safe by `v-html`; external cards have no body |
| **Publish body** | `category`, `title`, `summary?`, `tags[]?`, `cover?`, `id?`, `url\|content` by category | category strictly validated; tags must be a list; new card prepended at index 0; `created_at` server-set UTC |
| **Update body** | any subset of card fields | `summary`/`cover` unconditionally overwritten with stripped value; switching category migrates storage; slug never renames |
| **Archive body** | `{archived?: bool}` | Empty body defaults to `True` (set, not toggle) |
| **Tag list** | opaque array | Frontend reads only `.length`; backend currently leaks archived-card tags |
| **Error envelope** | `{ok, error?}` for mutations; `abort(404)` HTML for detail GET | **Inconsistent today** — target should unify as JSON |

## 3. Endpoints to preserve

| Method | Path | Semantics that must carry over |
|---|---|---|
| GET | `/api/health` | Liveness `{ok:true}` |
| GET | `/api/cards` | List, default excludes archived; `include_archived=1\|true\|yes` returns all |
| GET | `/api/cards/<id>` | Card + (local) `content`+`content_html` with H1 strip |
| GET | `/api/tags` | Distinct sorted tag union |
| POST | `/api/publish` | Slugify id, write MD for local, prepend to list, set `created_at` UTC |
| PUT | `/api/cards/<id>` | In-place edit; supports category switch with file migration; id never renames |
| PATCH | `/api/cards/<id>/archive` | Setter (not toggle); body `{archived:bool}` |
| DELETE | `/api/cards/<id>` | Hard delete card + MD file (UI keeps the button hidden) |

## 4. Pain points and bugs to fix (prioritized)

**P0 — correctness / data loss**
- `cards.json` read-modify-write with no locking, no atomic rename, no backup. Concurrent gunicorn workers can lose updates or truncate the file.
- `load_cards()` raises 500 if the file is missing; no graceful seed.
- Detail GET aborts with HTML while mutations return JSON — inconsistent error contract.
- Frontend has no Vite `/api` proxy; `npm run dev` against `:5173` hits 404 for every API call.

**P1 — schema / validation**
- No typed schema; category enum duplicated between publish and update.
- `tags` accepted without element validation, trim, dedupe, or cap.
- `url`/`cover` accepted as any string (incl. `javascript:`).
- PUT silently wipes `summary`/`cover` when omitted (asymmetric vs `title`).
- Archive endpoint defaults to True on empty body — surprising; no toggle, no unarchive route.
- `datetime.utcnow()` deprecated; `created_at` is date-only, no `updated_at`.
- `/api/tags` includes archived cards while `/api/cards` excludes them.

**P2 — frontend correctness**
- `App.vue` hero is a hardcoded external signed URL (violates PROJECT_NOTES 坑#5).
- HomeView ships fake stats/timestamps inline (`23:39:42`, `🔥 11 热度`); category sidebar UI doesn’t actually filter.
- DetailView hardcodes `13:35:55`, byline `pureworld`, fake counters; uses `card.cover` unencoded inside `url(...)`; `v-html` with no sanitizer; no loading/404 states.
- AdminPublishView’s `form.group` is collected but never sent; `loadForEdit` resets it to `技术类`.
- AdminView search button is a no-op; archive toggle does full reload, no optimistic update.
- Eight top-nav links are `href="#"`.

**P3 — performance / hygiene**
- Markdown re-rendered every request; no mtime-keyed cache.
- No pagination, no search/filter endpoint.
- Open CORS, no auth, no rate limiting on mutations.
- Orphan `.md` (`multi-agent-super-universe-draft.md`) with no GC.
- Dead code: `src/style.css`, `HelloWorld.vue`, `MilkdownEditor.vue`, `@milkdown/*`, `marked`, `marked-highlight`.
- `style.css` carries multiple obsolete layout systems, `!important` cascade workarounds, and conflicting `.card-cover.has-image` heights (168/186/210).

## 5. Decisions pinned by PROJECT_NOTES (deduped)

- Two categories: `external` (jump out) vs `local` (in-site MD). Branch the whole pipeline on this.
- Detail page uses **its own** cover for the hero, never the homepage hero.
- Strip a leading `# H1` from MD before rendering to avoid duplicating the hero title.
- Detail page has **no** right-side TOC, **no** back button.
- Homepage shows only the three big category entry cards; no extra first-level nav.
- Publish/edit page: title at top, md-editor-v3 as the main work area, secondary fields (summary/tags/cover) sink to a bottom 附加信息 region. No custom right-side preview.
- Admin list: delete button hidden;查看 repurposed as下架; 回到前台 entry top-left.
- Covers normalize to local `/covers/<id>.png`; do not depend on long-lived external URLs.
- Card hover: image scale + shadow, card itself does not translate.
- `h1`/`h2`/`h3` keep independent visual hierarchy; `.markdown-body h*` rules must not override `.article-prose` colors.
- Code-card wrapping must be idempotent (never run twice on the same `<pre>`).
- Hero copy: “是个人博客，也是技术收藏展厅”. English “LINK GARDEN” removed.
- Do NOT run the backend in Flask debug/reloader as a persistent service; syntax-check before reloading systemd.

## 6. Recommended target stack

### Backend
**FastAPI 0.118 + Pydantic v2.11 + SQLAlchemy 2.0 (async) + Alembic 1.14 + aiosqlite (dev) / asyncpg (prod-swap), gunicorn 23 with `uvicorn.workers.UvicornWorker`, src-layout under `backend/src/app`. Tooling: uv, ruff, pyright, pytest+pytest-asyncio+httpx, pre-commit, Docker.**

| Lib | Pin | Why |
|---|---|---|
| fastapi | ~=0.118 | Annotated deps, lifespan stable |
| pydantic / pydantic-settings | ~=2.11 / ~=2.6 | Typed schemas, .env loading |
| sqlalchemy[asyncio] | ~=2.0.36 | Typed `Mapped[]`, AsyncSession |
| alembic | ~=1.14 | Async env.py + batch mode for SQLite |
| aiosqlite / asyncpg | ~=0.20 / ~=0.30 | Dev / prod drivers |
| pyjwt / bcrypt | ~=2.10 / ~=4.2 | Avoid python-jose, avoid passlib |
| uvicorn[standard] / gunicorn | ~=0.34 / ~=23.0 | ASGI worker + supervisor |
| structlog / tenacity / httpx | ~=24.4 / ~=9.0 / ~=0.28 | Logs, retries, test client |

Pitfalls one-liners:
- Alembic env.py must use `connection.run_sync(...)`; import all model modules or autogenerate misses tables.
- Set `MetaData.naming_convention` before the first migration; `render_as_batch=True` for SQLite.
- Enable WAL + `PRAGMA foreign_keys=ON` + `busy_timeout=5000` via a `connect` listener.
- Pydantic v2: `from_attributes`, `model_dump`, `@field_validator`, `ConfigDict`.
- One AsyncSession per request; `expire_on_commit=False`; rollback on exception.
- Pin JWT `algorithms=['HS256']`; never accept `none`; secret via pydantic-settings.
- Run `alembic upgrade head` as a deploy step; do not call `create_all` in prod.
- Lifespan context manager; dispose engine on shutdown; uvicorn `--proxy-headers` behind nginx.

### Frontend
**Vue 3.5 (`<script setup>`) + TypeScript 5.7 + Vite 7 + vue-router 4 + Pinia 3 (setup stores) + md-editor-v3 5.x + highlight.js 11. API layer: openapi-typescript 7 + openapi-fetch (or orval+@tanstack/vue-query if generated composables are wanted). ESLint 9 flat config + Prettier 3. Tests: Vitest 3 + @vue/test-utils 2, optional Playwright. Node 20.19+/22 LTS, pnpm.**

| Lib | Pin | Why |
|---|---|---|
| vue / vue-router / pinia | ^3.5 / ^4.5 / ^3.0 | Composition + typed routing +ESM stores |
| typescript / vue-tsc | ~5.7 / ^2.2 | Volar2type-check |
| vite / @vitejs/plugin-vue | ^7.0 / ^5.2 | GA build tool |
| openapi-typescript / openapi-fetch | ^7.5 / ^0.13 | Types from FastAPI `/openapi.json` |
| @tanstack/vue-query | ^5.62 | Cache/retry over typed fetch |
| md-editor-v3 / highlight.js | ^5.4 / ^11.10 | Required by PROJECT_NOTES |
| @vueuse/core / vee-validate / zod | ^12/ ^4.15 / ^3.23 | Composables, forms, runtime validation |
| vite-plugin-checker | ^0.8 | Worker-thread vue-tsc +ESLint |

Pitfalls one-liners:
- Vite7 requires Node 20.19+/22; CI/Docker images must match.
- vue-tsc is3-5x slower than tsc; gate it as its own CI job.
- Pinia 3 is ESM-only; setup stores have no auto `$reset`.
- `openapi-typescript` is types-only — pair with `openapi-fetch` or types lie.
- Dedupe `highlight.js` via pnpm overrides; md-editor-v3 ships its own copy.
- ESLint 9 flat config requires `eslint-plugin-vue` v10; older versions silently drop Vue rules.
- DO add a Vite `/api` proxy this time; current dev is broken without nginx.
- `<script setup>` + `defineModel` needs explicit `modelValue` types under strict TS.

## 7. Open questions for Phase 2

1. **Storage migration.** Does Phase 2 introduce SQLite immediately, or run a JSON-compat shim for one release so prod can roll back? Confirm whether `cards.json` + `notes/*.md` get imported once and retired, or stay as an export format.
2. **Stable IDs vs slugs.** Decouple `id` (UUID, immutable) from `slug` (URL-friendly, renamable)? Required if titles ever rename — but it changes every existing URL.
3. **Auth scope.** Is admin a single shared password (env var + bcrypt) or a real user table? Where does the JWT live — httpOnly cookie or Authorization header?
4. **Cover upload.** Add `POST /api/covers` that writes to `frontend/public/covers/<id>.png`, or keep covers as a path users place manually? PROJECT_NOTES requires local covers but no upload UI exists.
5. **Search/filter contract.** Server-side tag/category/keyword filtering and pagination, or stay client-side until N grows? Affects whether `/api/cards` gains query params or a dedicated `/api/search`.
6. **Archive semantics.** Keep PATCH-as-setter, add `/unarchive`, or move to a generic `PATCH /api/cards/<id>` partial update?
7. **Sanitization.** Render Markdown server-side and trust it (current), or sanitize on the client with DOMPurify? Decision affects whether `v-html` stays.
8. **API codegen pick.** `openapi-typescript + openapi-fetch` (light) vs `orval + @tanstack/vue-query` (richer). Pick one before scaffolding `src/api/`.
9. **Category data model.** Today `category` is `external|local` (storage type). PROJECT_NOTES also tracks `技术类/随笔类/生活类` as a content group that the UI collects but drops. Phase 2 should split storage-type from content-group on the schema and surface the latter in the API.
10. **Routing.** Adopt `unplugin-vue-router` for typed routes, or stay on hand-rolled `createRouter`? Affects DX and lock-in.
11. **Testing baseline.** What is the minimum test set that gates Phase 2 merge — endpoint contract tests for the eight routes, plus a Vitest smoke suite for the four views?
12. **Deployment.** Switch the systemd unit to `gunicorn -k UvicornWorker` from day one, or keep Flask-style single-process during cutover?