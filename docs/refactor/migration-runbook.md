# Migration runbook — `cards.json` + `notes/*.md` → SQLite

Operator-facing runbook for the one-shot legacy-to-SQLite import. Pair this
with `backend/scripts/migrate_from_json.py` and `backend/scripts/spot_check.py`.
Phase-2 architecture §5 is the source of truth; this document is the executable
recipe.

> **Scope.** This runbook covers a single-host SQLite deployment (the
> production target). PostgreSQL swap is one `DATABASE_URL` change away; the
> verification + rollback steps below apply equally.

## 0. Pre-flight

| Check | Command | Expected |
|---|---|---|
| Schema is at head | `cd backend && uv run alembic current` | matches `head` |
| Admin user is seeded | `uv run python -c "from sqlalchemy import select; ..."` | one row |
| Legacy data is intact | `wc -l data/cards.json` | non-zero |
| Backend can boot | `uv run uvicorn app.asgi:app --port 5099` | `GET /api/health` returns `{"ok": true}` |

If any pre-flight check fails, **stop**. The migration is not what you want
to fix the failure.

## 1. Back up the legacy snapshot

The migration never writes to the legacy tree, but a defensive copy is cheap:

```bash
cp -r data/cards.json data/cards.json.bak.$(date +%F)
cp -r content/notes content/notes.bak.$(date +%F)
```

## 2. Dry-run

Run the migration with `--dry-run` first. The script does the full plan, then
rolls the transaction back. Inspect the log + HTML report before going live.

```bash
cd backend
uv run python -m scripts.migrate_from_json \
  --json-file ../data/cards.json \
  --notes-dir ../content/notes \
  --owner-username admin \
  --dry-run \
  --report-html /tmp/lg-migration-dryrun.html \
  -v
```

Pay attention to:

- **`aborts=`** must be **0**. The non-zero exit code (5) means at least one
  row was rejected; fix the source data and re-run the dry-run.
- **`orphan notes`** in the log — these are `.md` files in `content/notes/`
  with no corresponding `cards.json` entry. They are not migrated. Decide
  whether to delete them or to add a JSON entry.
- The HTML report's **sanitizer dropped** column flags any markdown that the
  renderer's nh3 allowlist stripped. A non-zero count is normal for legacy
  content with `<script>` blocks, inline styles, or javascript-uri links;
  scan the rows to make sure no legitimate construct was lost.

## 3. Commit the migration

When the dry-run is clean, run for real:

```bash
cd backend
uv run python -m scripts.migrate_from_json \
  --json-file ../data/cards.json \
  --notes-dir ../content/notes \
  --owner-username admin \
  --report-html /var/log/linkgarden/migration-$(date +%F).html
```

Idempotency is keyed on slug uniqueness: re-running this command after a
successful import inserts zero new rows (every legacy id resolves to an
existing slug and is `skipped`). Don't be afraid to re-run if the previous
invocation crashed midway — only successfully-committed rows persist.

## 4. Verify

Run the spot check **before** flipping production traffic over to the new
backend:

```bash
cd backend
uv run python -m scripts.spot_check --include-archived --json > /tmp/lg-spot.json
cat /tmp/lg-spot.json
```

The script prints card counts by category, by content group, archived count,
top tags, and a slug sample. Compare against the legacy snapshot:

```bash
# Snapshot the legacy state for comparison.
python - <<'PY'
import json, collections
cards = json.load(open("data/cards.json"))
by_cat = collections.Counter(c["category"] for c in cards)
arch = sum(1 for c in cards if c.get("archived"))
tags = collections.Counter(t for c in cards for t in c.get("tags", []))
print(json.dumps({
    "total": len(cards),
    "by_category": by_cat,
    "archived": arch,
    "top_tags": tags.most_common(20),
}, ensure_ascii=False, indent=2))
PY
```

The two outputs must agree on:

- total card count
- per-category counts
- archived count
- tag distribution (case-insensitive)

A mismatch is a stop-the-line bug — escalate before continuing.

## 5. Freeze the legacy tree

Once spot-check passes, make the legacy snapshot read-only so neither humans
nor the new backend can accidentally write to it:

```bash
chmod -R a-w data/cards.json content/notes
```

The new backend has no code path that writes to either location, so this is
purely defensive. Keep the snapshot on disk for one release cycle.

## 6. Cutover

The cutover itself lives in `scripts/deploy.sh`, but for completeness:

```bash
sudo systemctl disable --now linkgarden-legacy.service
sudo systemctl daemon-reload
sudo systemctl enable --now linkgarden.service
sudo systemctl status linkgarden.service
```

Smoke-test from a remote host:

```bash
curl -fsS https://linkgarden.example.com/api/health
curl -fsS https://linkgarden.example.com/api/v1/cards | jq 'length'
curl -fsS "https://linkgarden.example.com/api/v1/cards/<known-slug>" | jq '.title'
```

## 7. Rollback

The legacy tree is unchanged, so rollback is fast.

### 7a. SQLite

```bash
sudo systemctl stop linkgarden.service
mv /srv/linkgarden/backend/linkgarden.db /srv/linkgarden/backend/linkgarden.db.bak.$(date +%s)
sudo systemctl disable linkgarden.service
sudo systemctl enable --now linkgarden-legacy.service
```

The legacy Flask service reads from `data/cards.json` + `content/notes/*.md`
directly, so it will resume serving from where it left off. The freshly-named
`.db.bak` is preserved for post-mortem inspection.

### 7b. PostgreSQL swap

If you migrated onto Postgres, the procedure is the same but with `pg_restore`
in place of the SQLite file move:

```bash
sudo systemctl stop linkgarden.service
pg_restore --clean --if-exists -d $DATABASE_URL /var/backups/lg-pre-migration.dump
sudo systemctl disable linkgarden.service
sudo systemctl enable --now linkgarden-legacy.service
```

## 8. Failure modes & symptoms

| Symptom | Diagnosis | Fix |
|---|---|---|
| `LookupError: owner user 'admin' not found` | Admin row missing (Alembic 0002 skipped or `LG_ADMIN_*` unset). | Run `uv run alembic upgrade head` then re-set `LG_ADMIN_USERNAME` / `LG_ADMIN_PASSWORD` and re-run; or use `uv run python -m scripts.seed_admin`. |
| Row stays in `aborts` with `markdown file missing` | `cards.json` references a `.md` that doesn't exist on disk. | Either restore the missing file from VCS / backup, or remove the entry from `cards.json` (and re-run the dry-run). |
| `IntegrityError` on a slug that already exists | A concurrent run inserted the same slug. | The script auto-retries once with a `-imported` suffix; if it still fails, abort and inspect the DB by hand. Migration must run from a single host. |
| `sanitizer dropped` > 0 for a row you trust | Legacy content used a tag that nh3 strips by default (e.g., inline `<style>`). | Update the allowlist in `services/markdown.py` or rewrite the offending markdown before re-running. |
| Exit code 5 | At least one row aborted. | Inspect the log + HTML report; the script never writes the aborted rows. After fixing the source, re-run — already-imported rows skip cleanly. |

## 9. Related artifacts

- `backend/scripts/migrate_from_json.py` — the import script.
- `backend/scripts/spot_check.py` — the verification digest.
- `backend/scripts/seed_admin.py` — interactive admin creator (covers the
  pre-flight prereq).
- `backend/tests/scripts/test_migrate_from_json.py` — unit tests for the
  importer (fixtures under `backend/tests/fixtures/`).
- Phase-2 architecture §5 — the design that this runbook executes against.
- Phase-1 brief §2 — the legacy data shapes that must survive the move.

## 10. Sign-off checklist

Tick all eight before declaring the migration done:

- [ ] Pre-flight all-green (schema at head, admin seeded, backend boots)
- [ ] Backup taken (`cards.json.bak.*`, `notes.bak.*`)
- [ ] Dry-run clean: `aborts=0`, HTML report reviewed
- [ ] Real run committed; exit code `0`
- [ ] Spot-check digest matches legacy snapshot
- [ ] Legacy tree set to read-only (`chmod -R a-w`)
- [ ] Cutover smoke tests passed (`/api/health`, list, detail)
- [ ] HTML report archived to `/var/log/linkgarden/`
