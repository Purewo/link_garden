# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Link Garden / 净界 — a front-end / back-end split personal content site. Not a traditional blog template; it is a "personal content garden / tech bookmark hall / blog facade". Two content types coexist:

- `external`: bookmarked links. Card click jumps to the original URL. No body stored locally.
- `local`: site-authored Markdown. Metadata in `cards.json`, body as a `.md` file under `backend/content/notes/`.

Design language is dark, cool blue/cyan-purple, restrained, lightly cyberpunk. Several specific decisions have been deliberately ruled out (see PROJECT_NOTES.md "已明确否掉" / "需要避免的坑") — re-read it before redesigning page layouts or backend service mode.

## Commands

### Backend (Python 3.12, Flask)
```bash
cd backend
pip install -r requirements.txt
python app.py                 # dev: http://127.0.0.1:5001
gunicorn -b 0.0.0.0:5001 app:app   # prod-style
```
On the deployment host the backend runs under systemd as `link-garden-backend.service` on port 5001, bound to `127.0.0.1` only — it is not exposed directly, nginx reverse-proxies `/api/` to it. The unit currently runs `python app.py` (Flask dev server) rather than gunicorn; PROJECT_NOTES "需要避免的坑" #1 warns against using Flask debug/reloader mode as a persistent service.

### Frontend (Vue 3 + Vite)
```bash
cd frontend
npm install
npm run dev                   # http://0.0.0.0:5173
npm run build                 # outputs frontend/dist
npm run preview
```
In production the frontend is **not** run as a Vite/systemd service. Instead `npm run build` output is copied to `/srv/projects/link-garden/frontend/` and served as static files by nginx (see "Deployment" below). The older README/PROJECT_NOTES that describe a `link-garden-frontend.service` on port 5173 reflect an earlier dev setup; the current production host has no such unit.

### Service inspection (deployment host only)
```bash
systemctl status  link-garden-backend.service
systemctl restart link-garden-backend.service
journalctl -u link-garden-backend.service -n 100 --no-pager
# nginx serves the frontend statically — no frontend systemd unit
nginx -t && systemctl reload nginx
tail -n 100 /srv/projects/link-garden/logs/backend.log
```

There is no test suite or linter configured. Verify changes by hitting the API directly and loading affected pages in a browser.

## Architecture

### Storage model — flat files, no database
- `backend/data/cards.json` — single source of truth for the card list. Each entry has `id`, `title`, `category` (`external`|`local`), `summary`, `tags`, `cover`, `created_at`, `archived`. `external` cards also carry `url`; `local` cards carry `markdown` (a path relative to `backend/content/`, typically `notes/<id>.md`).
- `backend/content/notes/<id>.md` — body for `local` articles. Written/updated/deleted by the publish/update/delete endpoints in lockstep with `cards.json`.
- `frontend/public/covers/<id>.png` — article covers are stored locally on purpose; external image URLs caused header issues in detail-page rendering (PROJECT_NOTES "需要避免的坑" #5).

`cards.json` is gitignored as data, not absent. When a fresh checkout has no file, `load_cards()` will fail — seed it with `[]` or restore from elsewhere before starting the backend.

### Backend (`backend/app.py`)
Single-file Flask app, CORS open. All routes under `/api`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | liveness |
| GET | `/api/cards` | list cards; `?include_archived=1` to include archived |
| GET | `/api/cards/<id>` | detail; for `local` cards, reads the markdown file, strips a leading `# H1` line (avoid duplicating with detail-page hero title), and returns both `content` (raw) and `content_html` (rendered with `markdown` extensions `fenced_code`, `tables`) |
| POST | `/api/publish` | create a card; for `local`, also writes the `.md` file |
| PUT | `/api/cards/<id>` | update card; switching category between `external` and `local` deletes/creates the markdown file as needed |
| PATCH | `/api/cards/<id>/archive` | toggle `archived` |
| DELETE | `/api/cards/<id>` | remove card and its markdown file |

`slugify()` produces ids from Chinese + ASCII titles and falls back to a timestamped slug; collisions get a numeric suffix.

### Frontend (`frontend/src/`)
Vue 3 + Vite. Router (in `main.js`) is flat with four routes:

- `/` → `HomeView.vue` — hero banner, three category cards, card feed
- `/card/:id` → `DetailView.vue` — uses the article's own cover as the detail-page hero (not the home hero); h1 in markdown is stripped server-side to avoid duplicate titles
- `/admin` → `AdminView.vue` — article management; the "下架" button is a placeholder over the archive endpoint; the delete button is intentionally hidden to prevent mis-clicks
- `/admin/publish` → `AdminPublishView.vue` — title at top, `md-editor-v3` body editor takes the main work area, secondary fields (summary/tags/cover) sink to the bottom

`App.vue` switches between three shells (home / admin / detail) by route, so layout-affecting changes usually live there rather than in individual views. Particles + hero banner are home-only.

Markdown rendering libs:
- Detail page server-side HTML comes from the Python `markdown` package; code highlight is then applied client-side via `highlight.js` and code blocks are wrapped into "code cards". The wrapping must not run twice on the same `<pre>` or it will strip the block (PROJECT_NOTES "需要避免的坑" #4).
- Editor uses `md-editor-v3`; don't rebuild a right-side preview, rely on the editor's own preview.

### Frontend ↔ backend wiring
In dev: Vite serves on `5173`, backend on `5001`, no Vite proxy configured — the frontend talks to the backend directly via absolute URLs (axios). When changing the backend host/port, search the frontend for the API base before assuming a proxy will absorb it.

In production: same-origin via nginx, so relative `/api/...` works. The frontend bundle should call `/api/...` (relative) rather than hardcoding `http://host:5001`, otherwise prod will hit CORS or fail to resolve. Verify before shipping a build.

## Deployment (current production host)

Production lives on a single Ubuntu 24.04 host under `/srv/projects/link-garden/`:

```
/srv/projects/link-garden/
├── backend/                # synced from the repo; runs via systemd
│   ├── app.py
│   ├── .venv/              # local virtualenv used by the unit file
│   ├── data/cards.json
│   └── content/notes/*.md
├── frontend/               # contents of `npm run build`'s dist/, copied flat
│   ├── index.html
│   ├── assets/             # hashed JS/CSS chunks
│   ├── covers/, images/    # static media (covers/<id>.png)
│   └── favicon.svg, icons.svg
├── frontend.bak-YYYYMMDD-HHMMSS/   # previous frontend(s) kept as backup on each deploy
└── logs/backend.log
```

Notable facts:

- **`/srv/projects/link-garden/` is not a git repo.** Deploys are done by syncing files in (rsync/scp), not `git pull`. Don't assume `git status` works there.
- **systemd unit**: `/etc/systemd/system/link-garden-backend.service` runs `.venv/bin/python app.py` as `root`, `Restart=always`, binds `127.0.0.1:5001`.
- **nginx**: `/etc/nginx/sites-enabled/link-garden` → `sites-available/link-garden`. Listens on port `29472` (the public-facing port published by the host's NAT mapping), `root /srv/projects/link-garden/frontend;`, `location /api/` proxies to `127.0.0.1:5001`, `location /` does SPA fallback (`try_files $uri $uri/ /index.html`).
- **Frontend deploy step** is "build locally → replace `/srv/projects/link-garden/frontend/`". The `.bak-...` directory on the server is the previous version — a quick rollback target.

To redeploy the frontend:
1. `cd frontend && npm run build`
2. Sync `dist/*` into `/srv/projects/link-garden/frontend/` (keeping `covers/` and `images/` intact, or re-shipping them if they live in `public/`).
3. No nginx reload needed unless the site config changed.

To redeploy the backend:
1. Replace `backend/app.py` (and `requirements.txt` if deps changed; re-run `.venv/bin/pip install -r requirements.txt` then).
2. `systemctl restart link-garden-backend.service`.
