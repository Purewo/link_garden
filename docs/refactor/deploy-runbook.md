# LinkGarden Deployment Runbook

Single-host deployment, locked architecture from
`docs/refactor/phase2-architecture.md` §6. This runbook covers:

1. One-time host bring-up
2. Routine rollout via `scripts/deploy.sh`
3. Rollback (binary and data)
4. Cutover from the legacy Flask backend
5. Smoke and monitoring
6. Common operational tasks

The companion artifacts live next to this file:

- `deploy/systemd/linkgarden.service`
- `deploy/nginx/linkgarden.conf`
- `deploy/env/linkgarden.env.example`
- `scripts/deploy.sh`
- `scripts/gen-api.sh`

> All host paths in this document match the locked layout in
> phase2-architecture §6 (`/srv/linkgarden`, `/etc/linkgarden`). Do not change
> them without updating the systemd unit and the nginx alias together.

---

## 0. Prerequisites

| Item | Why |
|---|---|
| Ubuntu 22.04+ (or any distro with systemd ≥ 250 and SQLite ≥ 3.8) | `Type=notify`, `ProtectSystem=strict`, partial unique indexes |
| `linkgarden` system user/group (no login shell) | systemd unit `User=linkgarden` |
| `uv` installed at `/usr/local/bin/uv` (>= 0.4) | venv + dependency lock |
| `nginx` (any modern version with `http2 on;` directive) | TLS termination + SPA serve |
| `certbot` or another ACME client | TLS certificates under `/etc/letsencrypt/live/<host>/` |
| `git` on the host | the backend tree is a git checkout |
| SSH access for the deploy operator (`linkgarden` or a sudo-capable account) | runs `scripts/deploy.sh` |
| Local disk only — **no NFS** for `/srv/linkgarden/backend` | WAL-mode SQLite corrupts on NFS |

---

## 1. One-time host bring-up

### 1.1 System user and directories

```bash
sudo useradd --system --home-dir /srv/linkgarden --shell /usr/sbin/nologin linkgarden
sudo install -d -o linkgarden -g linkgarden /srv/linkgarden
sudo install -d -o linkgarden -g linkgarden /srv/linkgarden/backend
sudo install -d -o linkgarden -g linkgarden /srv/linkgarden/frontend
sudo install -d -o linkgarden -g linkgarden /srv/linkgarden/frontend/dist
sudo install -d -o linkgarden -g linkgarden /srv/linkgarden/var
sudo install -d -m 0750 -o root -g linkgarden /etc/linkgarden
```

### 1.2 Backend checkout + venv

```bash
sudo -u linkgarden git clone https://github.com/your-org/linkgarden /srv/linkgarden/backend
sudo -u linkgarden git -C /srv/linkgarden/backend checkout <release-sha>

# uv-managed venv lives outside the checkout so a `rm -rf` of the checkout
# never blows it away.
sudo -u linkgarden bash -lc '
  cd /srv/linkgarden/backend
  /usr/local/bin/uv venv /srv/linkgarden/venv --python 3.12
  /usr/local/bin/uv sync --no-dev --frozen --active --python /srv/linkgarden/venv/bin/python
'
```

### 1.3 Environment file

```bash
sudo install -m 0640 -o root -g linkgarden \
    deploy/env/linkgarden.env.example /etc/linkgarden/linkgarden.env
sudoedit /etc/linkgarden/linkgarden.env
```

Fill in (at minimum):

- `JWT_SECRET` — `openssl rand -hex 32`
- `LG_ADMIN_PASSWORD` — ≥ 8 characters; alembic 0002 aborts otherwise
- `APP_ENV=prod`

Verify the unit picks it up with `systemd-analyze verify` after install.

### 1.4 systemd unit

```bash
sudo install -m 0644 deploy/systemd/linkgarden.service \
    /etc/systemd/system/linkgarden.service
sudo systemd-analyze verify /etc/systemd/system/linkgarden.service
sudo systemctl daemon-reload
sudo systemctl enable linkgarden.service
```

Do **not** `start` it yet — the first migration + admin seed runs on the
first start. We want that to happen during a controlled cutover, not now.

### 1.5 nginx site

```bash
sudo install -m 0644 deploy/nginx/linkgarden.conf \
    /etc/nginx/sites-available/linkgarden.conf
sudo ln -sf /etc/nginx/sites-available/linkgarden.conf \
    /etc/nginx/sites-enabled/linkgarden.conf
sudo nginx -t
```

Provision TLS (`certbot --nginx -d linkgarden.example.com` or equivalent).
After the first `linkgarden.service` start, run `sudo systemctl reload nginx`.

### 1.6 sudoers entries for the deploy account

`scripts/deploy.sh` uses `sudo` on the host for service control and nginx
operations. Install a dropin:

```
# /etc/sudoers.d/linkgarden-deploy  (chmod 0440)
deploy ALL=(root) NOPASSWD: /bin/systemctl restart linkgarden.service, \
                              /bin/systemctl reload nginx, \
                              /usr/sbin/nginx -t, \
                              /usr/bin/install -m 0644 /srv/linkgarden/backend/deploy/nginx/linkgarden.conf /etc/nginx/sites-available/linkgarden.conf
```

Adjust paths to match your distro. Visudo-check with `sudo visudo -c -f /etc/sudoers.d/linkgarden-deploy`.

### 1.7 Migrate legacy data (if cutting over from the Flask backend)

See §4 "Cutover from legacy" — runs the one-shot importer
`backend/scripts/migrate_from_json.py` against a freshly-migrated empty DB.

### 1.8 Smoke

```bash
sudo systemctl start linkgarden.service
sudo journalctl -u linkgarden.service -f
# In another shell:
curl -fsS http://127.0.0.1:5001/api/health
curl -fsS http://127.0.0.1:5001/api/v1/health
curl -fsS https://linkgarden.example.com/api/health
```

All three must return `{"ok":true}`. If any fail, see §6.

---

## 2. Routine rollout

Operator runs `scripts/deploy.sh` from a developer machine or CI runner with
SSH access to the host. The script implements the rollout order from
phase2-architecture §6:

```bash
export LG_HOST=linkgarden.example.com
export LG_SSH_USER=deploy
export LG_PUBLIC_URL=https://linkgarden.example.com
export LG_REMOTE_ROOT=/srv/linkgarden

# Dry-run first — prints every command without executing.
./scripts/deploy.sh --dry-run --ref "$(git rev-parse HEAD)"

# Real rollout
./scripts/deploy.sh --ref "$(git rev-parse HEAD)"
```

Phases executed by `scripts/deploy.sh`:

| # | Step | Failure behaviour |
|---|---|---|
| 1 | `pnpm install --frozen-lockfile && pnpm gen:api && pnpm typecheck && pnpm lint && pnpm test --run && pnpm build` | Abort before touching the host. |
| 2 | `ssh host 'cd backend && git fetch && git checkout <ref> && uv sync --no-dev --frozen'` | Abort; previous binary keeps serving. |
| 3 | nginx config drift check (`sha256sum` of `linkgarden.conf` vs host's copy). | Abort unless `--force-nginx`. |
| 4 | `systemctl restart linkgarden.service` — runs `alembic upgrade head` as `ExecStartPre`. | systemd reports `failed`; previous binary keeps running because frontend has not been rsynced yet (exit code 5). |
| 5 | Loopback smoke: `curl http://127.0.0.1:5001/api/v1/health` (10 retries, 1s apart). | Same; exit 5. |
| 6 | `rsync -avz --delete frontend/dist/` onto the host. | Abort; frontend untouched on partial transfer (rsync writes to tmp). |
| 7 | Public smoke: `curl $LG_PUBLIC_URL/api/health` and SPA root. | Exit 5 — frontend already swapped; investigate immediately. |

Useful flags:

- `--dry-run` — print every command, run no mutations on either side.
- `--skip-build` — re-deploy a previously-built `frontend/dist/` without rerunning the toolchain.
- `--reload-nginx` — when nginx config changed, install + `nginx -t` + reload.
- `--force-nginx` — proceed despite a drift mismatch (only after manual review).
- `--ref` / `--host` / `--user` / `--public-url` — override the env defaults.

After every rollout, capture the git ref in your change log:

```bash
git -C /srv/linkgarden/backend log -1 --oneline >> /srv/linkgarden/var/deploy.log
```

---

## 3. Rollback

Rollback is **always** the inverse of the most recent change. Choose the
smallest scope that fixes the user-visible problem.

### 3.1 Frontend-only regression (CSS, JS, no migration involved)

```bash
# On the operator machine — rebuild the previous good ref and ship just the bundle.
./scripts/deploy.sh --ref <previous-good-sha>
```

`--skip-build` plus a stashed `dist/` snapshot is faster if you keep one.

### 3.2 Backend regression, no schema change

```bash
ssh deploy@linkgarden.example.com '
    cd /srv/linkgarden/backend
    git checkout <previous-good-sha>
    /usr/local/bin/uv sync --no-dev --frozen
    sudo systemctl restart linkgarden.service
'
curl -fsS https://linkgarden.example.com/api/health
```

The systemd unit will re-run `alembic upgrade head`. If both refs target the
same Alembic head, this is a no-op. If the previous ref's head is *behind*
the current DB head, you must downgrade first (§3.3).

### 3.3 Backend regression with schema change

Alembic supports `downgrade <revision>` but **only** when the revision's
`downgrade()` is implemented correctly. Treat downgrades as last resort.

Preferred recovery: forward-fix a new revision that reverses the bad change,
then deploy normally.

If a true downgrade is unavoidable:

```bash
ssh deploy@linkgarden.example.com '
    sudo systemctl stop linkgarden.service
    cd /srv/linkgarden/backend
    cp linkgarden.db linkgarden.db.pre-downgrade-$(date +%s)
    /srv/linkgarden/venv/bin/alembic -c alembic.ini downgrade <previous-revision>
    git checkout <previous-good-sha>
    /usr/local/bin/uv sync --no-dev --frozen
    sudo systemctl start linkgarden.service
'
```

Confirm the `.db.pre-downgrade-*` copy is intact before reporting success.

### 3.4 Catastrophic — data loss event

1. Stop the unit: `sudo systemctl stop linkgarden.service`.
2. Move the live DB aside:
   ```bash
   sudo mv /srv/linkgarden/backend/linkgarden.db{,.broken-$(date +%s)}
   sudo mv /srv/linkgarden/backend/linkgarden.db-wal{,.broken-$(date +%s)} 2>/dev/null || true
   sudo mv /srv/linkgarden/backend/linkgarden.db-shm{,.broken-$(date +%s)} 2>/dev/null || true
   ```
3. Restore the most recent backup or re-run the legacy importer (§4).
4. Start the unit. `alembic upgrade head` re-runs idempotently; the admin-seed
   migration is a no-op against an already-seeded users table.
5. Audit `data/cards.json` integrity. The legacy snapshot is `chmod -R a-w` and
   has never been mutated by the new backend, so it is the source of truth.

---

## 4. Cutover from legacy Flask backend

One-time procedure. The new backend lives under `/srv/linkgarden/backend`; the
old one under `/srv/linkgarden-legacy/`. Both unit names coexist for the
duration of cutover.

### 4.1 Pre-cutover

- Tag the legacy code: `git tag legacy-final && git push --tags`.
- Take a full `tar -czf` of `/srv/linkgarden-legacy/{data,content}` and copy
  it off-host.
- Snapshot the legacy `/api/cards` and `/api/tags` responses so you can
  compare counts after cutover:
  ```bash
  curl -fsS http://127.0.0.1:5000/api/cards?include_archived=1 > /tmp/legacy-cards.json
  curl -fsS http://127.0.0.1:5000/api/tags > /tmp/legacy-tags.json
  ```

### 4.2 Bring up the new backend with empty DB

```bash
sudo systemctl start linkgarden.service
sudo journalctl -u linkgarden.service -n 200
curl -fsS http://127.0.0.1:5001/api/v1/health
```

The first start runs `alembic upgrade head` and the `0002_seed_admin` data
migration. Confirm the admin row exists:

```bash
sudo -u linkgarden /srv/linkgarden/venv/bin/python -c '
import asyncio
from sqlalchemy import text
from app.core.db import async_session
async def main():
    async with async_session() as s:
        n = (await s.execute(text("SELECT COUNT(*) FROM users"))).scalar_one()
        print("users:", n)
asyncio.run(main())
'
```

### 4.3 Run the migration importer

The legacy artifacts are still under `/srv/linkgarden-legacy/`. From the new
backend directory:

```bash
sudo systemctl stop linkgarden.service   # avoid mid-write races
sudo -u linkgarden bash -lc '
    cd /srv/linkgarden/backend
    /srv/linkgarden/venv/bin/python -m scripts.migrate_from_json \
        --json-file /srv/linkgarden-legacy/data/cards.json \
        --notes-dir /srv/linkgarden-legacy/content/notes \
        --owner-username admin \
        --report-html /srv/linkgarden/var/migration-report.html
'
sudo systemctl start linkgarden.service
```

Review `/srv/linkgarden/var/migration-report.html` for any rows where the
HTML sanitizer dropped legitimate content. Hold cutover until those are
either acknowledged or fixed in the markdown source.

### 4.4 Freeze the legacy snapshot

```bash
sudo chmod -R a-w /srv/linkgarden-legacy/data /srv/linkgarden-legacy/content/notes
```

The new backend has zero code paths that write to either tree.

### 4.5 Flip nginx + disable the legacy unit

```bash
sudo systemctl stop linkgarden-legacy.service
sudo systemctl disable linkgarden-legacy.service
sudo mv /etc/systemd/system/linkgarden-legacy.service \
        /etc/systemd/system/linkgarden-legacy.service.disabled
sudo systemctl daemon-reload
sudo systemctl reload nginx
```

`linkgarden.conf` already proxies to `127.0.0.1:5001`, so once
`linkgarden.service` owns the port, public traffic lands on the new stack.

### 4.6 Verify

```bash
# Counts should match the legacy snapshot from §4.1.
curl -fsS https://linkgarden.example.com/api/v1/cards?include_archived=true | jq 'length'
curl -fsS https://linkgarden.example.com/api/v1/tags | jq 'length'

# Spot-check a known slug from the legacy URLs — should resolve identically.
curl -fsS https://linkgarden.example.com/api/v1/cards/<legacy-id>

# Legacy URL paths should 308-redirect to /api/v1/...
curl -fsS -I https://linkgarden.example.com/api/cards | grep -E 'HTTP/|location:'
```

### 4.7 Rolling back the cutover

If something goes wrong before §4.5:

- Nothing user-visible has changed yet; just `systemctl stop linkgarden.service`,
  re-`chmod` the legacy snapshot back to writable, and resume traffic.

If something goes wrong after §4.5 (legacy already disabled):

- `sudo mv /etc/systemd/system/linkgarden-legacy.service.disabled` back, then
  `systemctl enable --now linkgarden-legacy.service`. nginx must be updated
  to proxy back to whatever port the legacy unit listened on. The data is
  untouched.

### 4.8 Removing the legacy 308 shim

The new backend ships a catch-all `/api/{path}` → `/api/v1/{path}` 308 redirect
that is logged at WARN with the original UA. The shim sunsets one release
after the SPA cuts over to `/api/v1/*` (which happens in the same release that
adds the shim).

Steps when the time comes:

1. `grep legacy_api_hit /var/log/linkgarden/*.log` for the previous 14 days.
   Confirm zero unexpected callers. Document any third-party scripts you find.
2. Remove the catch-all route in `app/main.py`.
3. Update the CHANGELOG with the removal date.
4. Roll out via `scripts/deploy.sh` as usual.

---

## 5. Smoke and monitoring

### 5.1 Liveness

External monitor: `GET https://linkgarden.example.com/api/health` — version-stable.
Internal probe: `GET http://127.0.0.1:5001/api/v1/health`.

Both must return `{"ok":true}` with a 200. Anything else pages on-call.

### 5.2 Logs

structlog emits JSON to stdout in `APP_ENV=prod`. journald captures it:

```bash
sudo journalctl -u linkgarden.service -n 200 --output=json --no-pager | \
    jq -r 'select(.MESSAGE | fromjson | .level == "error") | .MESSAGE'
```

Useful event names to alert on (see phase2-architecture §3.9):

- `legacy_api_hit` (WARN) — caller hit the 308 shim
- `cover_too_large`, `cover_bad_type`, `invalid_image` (WARN) — upload abuse
- `internal_error` (ERROR) — 500 catch-all; always investigate
- `invalid_credentials` spike per IP — credential stuffing; check nginx rate-limit

### 5.3 Backups

SQLite is one file plus a WAL sidecar. Online-safe backup:

```bash
sudo -u linkgarden /srv/linkgarden/venv/bin/python -c "
import sqlite3, sys
src = sqlite3.connect('/srv/linkgarden/backend/linkgarden.db')
dst = sqlite3.connect('/srv/linkgarden/var/backup-$(date +%F).db')
with dst:
    src.backup(dst)
"
```

Schedule via systemd timer; retain at least 14 days off-host. Covers under
`backend/src/app/static/covers/` should be `rsync`ed to the same backup target.

### 5.4 Rate-limit visibility

nginx writes `lg_login` 429s to the access log. A quick count:

```bash
sudo awk '$9==429 && $7~"/api/v1/auth/login" {print $1}' /var/log/nginx/access.log | sort | uniq -c | sort -nr | head
```

If a single IP dominates, consider a hard block in nginx or upstream firewall.

---

## 6. Common operational tasks

### 6.1 Reset the admin password

`alembic 0002_seed_admin` only seeds when the users table is empty. To rotate:

```bash
sudo -u linkgarden /srv/linkgarden/venv/bin/python -m scripts.seed_admin
```

The script reads username + new password via `getpass()` on a TTY only and
updates `password_hash` in place. Never commit a password to the env file.

### 6.2 Rebuild the OpenAPI snapshot

When the backend contract changes, regenerate the frontend types and the
committed snapshot:

```bash
./scripts/gen-api.sh             # local
./scripts/gen-api.sh --check     # CI gate; fails if generated files drifted
```

Commit both `frontend/openapi/schema.json` and
`frontend/src/shared/api/schema.d.ts`.

### 6.3 nginx config change

1. Edit `deploy/nginx/linkgarden.conf` in the repo.
2. `scripts/deploy.sh --ref <sha> --reload-nginx` installs the new config,
   runs `nginx -t`, and reloads.
3. If the drift gate complains and you have already reviewed the diff,
   add `--force-nginx` to bypass.

### 6.4 Adjust gunicorn worker count

Edit `ExecStart=` in `deploy/systemd/linkgarden.service`. Cap is `-w 4` on
single-host SQLite (writes serialize anyway). After editing:

```bash
sudo install -m 0644 deploy/systemd/linkgarden.service \
    /etc/systemd/system/linkgarden.service
sudo systemctl daemon-reload
sudo systemctl restart linkgarden.service
```

### 6.5 Add a TLS rotation

`certbot renew` runs from its own systemd timer. After renewal:

```bash
sudo systemctl reload nginx   # picks up the new cert without dropping connections
```

linkgarden.service does not terminate TLS, so it does not need to restart.

### 6.6 Investigate a 5xx spike

```bash
sudo journalctl -u linkgarden.service --since "10 min ago" \
    | grep -E 'internal_error|status_code":5[0-9][0-9]'
```

`request_id` is bound on every structlog event for that request. Grep that
id across the journal for the full trail.

### 6.7 Detach the database for inspection

```bash
sudo systemctl stop linkgarden.service
sudo -u linkgarden sqlite3 /srv/linkgarden/backend/linkgarden.db
# .schema, SELECT ... , then .exit
sudo systemctl start linkgarden.service
```

Do not run schema-altering statements outside Alembic. If you need a quick
read against a live system, `sqlite3 -readonly` is safe to use without
stopping the service (WAL mode permits concurrent readers).

---

## 7. Glossary

- **Locked layout** — phase2-architecture §6 paths; the systemd unit and
  nginx alias both hard-code them.
- **Legacy 308 shim** — catch-all `/api/{path}` → `/api/v1/{path}` redirect in
  `app/main.py`. One-release sunset; see §4.8.
- **Drift gate** — `scripts/deploy.sh` refuses to proceed if the in-repo
  `deploy/nginx/linkgarden.conf` does not match the host's copy. Override
  with `--force-nginx` only after manual review.
- **Snapshot** — the committed `frontend/openapi/schema.json`. Regenerate
  with `scripts/gen-api.sh`; gate CI with `--check`.

---

## 8. Quick reference

| Action | Command |
|---|---|
| Routine deploy | `./scripts/deploy.sh --ref <sha>` |
| Dry-run | `./scripts/deploy.sh --dry-run --ref <sha>` |
| Frontend-only re-ship | `./scripts/deploy.sh --ref <sha> --skip-build` |
| Restart backend (no code change) | `sudo systemctl restart linkgarden.service` |
| Reload backend (gunicorn re-exec) | `sudo systemctl reload linkgarden.service` |
| Reload nginx | `sudo nginx -t && sudo systemctl reload nginx` |
| Tail logs | `sudo journalctl -u linkgarden.service -f` |
| Rotate admin password | `sudo -u linkgarden /srv/linkgarden/venv/bin/python -m scripts.seed_admin` |
| Regenerate API types | `./scripts/gen-api.sh` |
| CI codegen drift check | `./scripts/gen-api.sh --check` |
