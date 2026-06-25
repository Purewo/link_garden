Skipping task tracking; the Phase-4 task is already in_progress and this review is the work being done. Now writing the review.

# Review R2 — security

## P0 findings (must fix before any deploy)

### Cover-upload admin guard fails OPEN on import error
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\covers\routes.py:42-51,63-70`
- **Symptom:** `POST /api/v1/covers` is gated by `dependencies=[Depends(_require_admin)]`. The `_require_admin` symbol is imported under a `try/except Exception` that, on any failure, installs a stub `async def _require_admin() -> Any: return None`. The router still accepts the `Depends(_require_admin)` reference, so the gate is registered — but the gate is now a no-op that always succeeds. Result: the cover endpoint becomes a fully public, unauthenticated multipart-upload endpoint that overwrites arbitrary `cards.cover` fields and writes arbitrary attacker-controlled bytes to `<STATIC_DIR>/covers/<card_id>.<ext>`, served by nginx with `Cache-Control: public, immutable`.
- **Root cause:** "Tolerate missing dependency at import time" was treated as the same problem as "tolerate missing dependency at deployment time." It is not. Anything that perturbs `app.features.auth.deps` (a circular-import regression, an editor save-corruption, a typo in another module imported transitively, a botched `git rebase`) silently disables auth on the upload route. The `# integrator wires this in` comment does not run in production.
- **Fix:** Delete the fallback. Import unconditionally; if auth is missing, the module *must* refuse to import. Same for `CardRepository`.```python
  # routes.py — replace the entire try/except blocks with:
  from app.core.db import get_session
  from app.features.auth.deps import _require_admin
  from app.features.cards.repo import CardRepository
  ```
  If you want graceful degradation in B1's stand-alone runs, gate the *router registration* (in `main.py`) on whether the auth module imports — never the dependency itself.
- **Verification:** Add `tests/integration/test_covers.py::test_post_covers_requires_auth` that issues `POST /api/v1/covers` with no `Authorization` header and asserts `401`. Then break `app.features.auth.deps` (rename it temporarily) and rerun: import of `app.features.covers.routes` must now raise, the FastAPI app must fail to boot, and `pytest` must error before any 200 response is observed.

### Auth router prefix missing — login lands at `/api/v1/login`, nginx login rate-limit is bypassed
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\routes.py:27`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\main.py:77`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\deploy\nginx\linkgarden.conf:101`
- **Symptom:** `router = APIRouter(tags=["auth"])` carries no `/auth` prefix and `_build_v1_router` mounts feature routers without an `include_router(..., prefix="/auth")` override, so the actual paths in production are `POST /api/v1/login` and `GET /api/v1/me`. The nginx config has an exact-match `location = /api/v1/auth/login` that applies the `lg_login` rate-limit zone. Because the path no longer matches the location, the credential-stuffing rate limit is silently disabled; the endpoint also disagrees with the OpenAPI contract the SPA was generated against. (The phase 3 report flags it; it is unfixed in tree.)
- **Root cause:** The router constructor does not declare its prefix and `main.py` does not supply one at inclusion time.
- **Fix:** In `backend/src/app/features/auth/routes.py:27`, change to `router = APIRouter(prefix="/auth", tags=["auth"])`. Re-snapshot OpenAPI and regenerate the frontend client.
- **Verification:** `pytest backend/tests/integration/test_auth.py -k login` after asserting `client.post("/api/v1/auth/login", ...)` returns 200; assert `client.post("/api/v1/login", ...)` returns 404. `nginx -T | grep '/api/v1/auth/login'` and run a script POSTing to that path30× in a minute — observe 429s after 5/burst.

### `_validation_exception_handler` returns a 500 on every Pydantic validation error
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\errors.py:174-196`
- **Symptom:** `[dict(err) for err in errors]` runs over `RequestValidationError.errors()`. In Pydantic v2 each entry's `ctx` field can carry the original `ValueError` (or any `Exception` subclass) — `dict(err)` keeps the live exception object inside `detail`. `JSONResponse` then attempts `json.dumps(...)` and raises `TypeError: Object of type ValueError is not JSON serializable`. That error propagates to `_unhandled_exception_handler`, which serves a generic 500 envelope. So every malformed payload gets a 500 with `code="internal_error"` instead of a structured 422 with the validation errors. The 500 path also stack-traces the original `ValueError` into the logs (information disclosure into journald) and breaks the public/SPA contract that promises `code="validation_failed"` for bad input.
- **Root cause:** `dict(err)` is a shallow conversion; it does not coerce non-JSON values. The phase 3 report flagged this and it remains unfixed.
- **Fix:** Use `fastapi.encoders.jsonable_encoder` (it already strips `BaseException` instances) or whitelist serialisable keys.
  ```python
  from fastapi.encoders import jsonable_encoder
  ...detail=jsonable_encoder(errors, exclude_none=True),
  ```
- **Verification:** Add `tests/integration/test_errors.py` that POSTs `{"username":""}` to `/api/v1/auth/login`, asserts `response.status_code == 422`, `response.json()["code"] == "validation_failed"`, and `response.json()["detail"]` is a list of plain dicts. Without the fix the response is 500 / `internal_error`.

### `encode_jwt(...)` keyword mismatch — login crashes the worker
- **Severity:** P0
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\service.py:68`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\security.py:46`
- **Symptom:** `mint_token` calls `encode_jwt(claims, ttl=ttl)`; `encode_jwt` accepts only `(claims, ttl_seconds=None)`. At runtime `TypeError: encode_jwt() got an unexpected keyword argument 'ttl'` is raised inside the `POST /auth/login` handler. The catch-all `_unhandled_exception_handler` returns a 500 envelope, but no one ever logs in. (Documented in phase 3 report as "fix during merge"; still unfixed.)
- **Root cause:** Cross-unit signature drift between B1 and B4 was never reconciled.
- **Fix:** In `service.py:68` change to `token = encode_jwt(claims, ttl_seconds=ttl)`.
- **Verification:** `pytest backend/tests/integration/test_auth.py::test_login_returns_jwt`. Manually `curl -X POST .../auth/login -d '{"username":"admin","password":"…"}'`; expect a `TokenResponse` body, not a 500.

## P1 findings (must fix before declaring v1)

### Cover endpoint trusts `Form(card_id: UUID)` value to build the destination filename without proving the requester owns the card
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\covers\service.py:329, 343`
- **Symptom:** Once the P0 admin gate is fixed, `card_id` is the *only* thing identifying which row gets clobbered, and any admin can target any other admin's card — fine for v1 single-admin, but the architecture spec keeps the door open for multi-admin (`role` is a string today). More importantly, `filename = f"{card_id}.{ext}"` uses the stringified UUID directly. If anyone weakens the `Form(...)` type to `str` later (for "compatibility"), the filename becomes attacker-controlled and the only thing protecting the directory is `_safe_join`. Hardening now keeps the regression cheap.
- **Root cause:** Filename derivation never independently validates the UUID shape after `Form` parsing; `_safe_join` is the only structural check.
- **Fix:** After `card_id: UUID` is parsed, immediately re-stringify via `card_id = UUID(str(card_id))` (forces canonical-form normalization) and assert the resulting string matches `^[0-9a-f-]{36}$`. Also add `assert candidate.is_relative_to(covers_resolved)` (Python 3.9+) instead of the `parents` check, which fails on case-insensitive filesystems with symlinked covers dirs.
- **Verification:** Unit test `_safe_join(covers_dir, "../../etc/passwd")` raises `BadRequest`; `_safe_join(covers_dir, "..\\\\..\\\\etc\\\\passwd")` raises on Windows hosts.

### `JWT_SECRET` validator rejects only three placeholder values
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\config.py:81-89`
- **Symptom:** `_refuse_placeholder_secret` blocks `change-me`, `changeme`, `secret` (case-insensitive). It does *not* block the literal placeholder shipped in `deploy/env/linkgarden.env.example`: `REPLACE_ME_WITH_openssl_rand_hex_32_OUTPUT`. That string is 41 chars so passes `min_length=32`. An operator who copies the example file and forgets to fill it in will boot a server signing tokens with a publicly-known secret. The `LG_ADMIN_PASSWORD` placeholder `REPLACE_ME_AT_LEAST_8_CHARS` (27 chars) is similarly accepted and seeded into the admin row.
- **Root cause:** Defense-in-depth check is too narrow — it lists three legacy strings and ignores the placeholders the example file actually ships with.
- **Fix:** Reject any value containing `REPLACE_ME` (case-insensitive) and any value matching `^[A-Z_]+$` (the example file convention). Also enforce a Shannon-entropy floor (≥3.5bits/byte) — a 32-char single-char string passes `min_length` today.```python
  if "replace_me" in value.lower() or value.lower() in forbidden:
      raise ValueError("JWT_SECRET must be replaced before booting")
  ```
  Apply the same pattern to `LG_ADMIN_PASSWORD` validation.
- **Verification:** Add `tests/unit/test_config.py::test_placeholder_secret_rejected` that constructs `Settings(JWT_SECRET="REPLACE_ME_WITH_openssl_rand_hex_32_OUTPUT", ...)` and asserts `ValidationError` is raised.

### Repository writes commit each statement; service-layer rollback is not transactional
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\repo.py:136-185`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\covers\service.py:337-344`
- **Symptom:** `CardRepository.insert/update/delete/set_cover` each `await self.session.commit()` immediately. The cover-upload service writes the file to disk first, then calls `card_repo.set_cover(...)` which commits the cover-URL update. If the file write succeeds and the DB commit fails (disk full, foreign-key violation in a future schema, asyncpg connection drop), the file is on disk under `<card_id>.<ext>` but the column still points at the old URL — readers via nginx serve the new file at the next cache-bust window because the URL itself is timestamped. Equally, `CardService.update` mutates `card.title/group/summary/...` in place, then calls `repo.update`; if a slug collision raises mid-flight the `session.rollback()` cannot undo the prior in-process attribute mutations on the ORM instance, so a re-tried request sees a half-updated row in the identity map.
- **Root cause:** The repository commits per call instead of per request. The architecture spec implied unit-of-work at request scope (`get_session` rolls back on exception, closes in finally), but the implementation breaks it.
- **Fix:** Strip every `await self.session.commit()` out of `repo.py` (keep `flush` + `refresh`). Make `get_session` commit on successful generator return, rollback on exception. Service layer never calls `commit` either; FastAPI's dep teardown does.
- **Verification:** Inject a session fake whose `commit` raises mid-cover-upload; assert that `cards.cover` retains its previous value and the new file is unlinked (or, at minimum, that the DB and disk agree at end-of-request).

### `gitleaks` runs only at pre-commit; no CI gate, and the `.env.example` files use predictable placeholders that a real secret could be diff-noised into
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\.pre-commit-config.yaml:36-39`, `.github\workflows\backend.yml`/`frontend.yml`/`contract.yml`
- **Symptom:** Gitleaks is configured as a local pre-commit hook only. Developers can bypass with `git commit --no-verify`, and contributors who never installed pre-commit have no protection at all. None of the three workflow files runs gitleaks on PRs, so a real `JWT_SECRET` slipping into a `.env.example` line under the `REPLACE_ME_WITH_openssl_rand_hex_32_OUTPUT` placeholder pattern would land on `main` undetected.
- **Root cause:** Server-side enforcement was never wired.
- **Fix:** Add a CI job that runs `gitleaks detect --redact --no-banner --exit-code 1` against the PR diff and the full history on `main` pushes. Pin to the same `v8.21.2` rev as the pre-commit hook.
- **Verification:** Open a draft PR that adds `JWT_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef` to `deploy/env/linkgarden.env.example`; CI must turn red.

### Nginx CSP allows `img-src https:` — opens a side-channel for tracking pixels in admin-published markdown
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\deploy\nginx\linkgarden.conf:75`
- **Symptom:** `img-src 'self' data: https:` (and the markdown sanitizer's allowed `<img>`/`src` schemes `http`/`https`/`mailto`) means any inline image URL in markdown is fetched from arbitrary third-party origins. This is fine for trust-the-author single-admin v1, but combined with `Referrer-Policy: strict-origin-when-cross-origin` the third party still learns the visitor's IP, UA, accept-language, and the referrer origin. If an attacker ever socially-engineers the admin into pasting a markdown image (`![](https://evil.example/track.gif)`) every public visitor exfiltrates to evil.example. nh3 also strips no `data:image/svg+xml;base64,…` payload — SVG-data-URI XSS is still on the table because `data:` is in `img-src`. Verify nh3's URL filter actually blocks `data:` in `<img src>`; spot-check shows `URL_SCHEMES = {"http", "https", "mailto"}` does block `data:` for href/src so this part is OK, but the CSP would still allow `data:` images injected via other vectors (e.g., a future bypass).
- **Root cause:** CSP was scoped to the legacy "embed third-party images in articles" requirement; that requirement is incompatible with privacy hygiene.
- **Fix:** Tighten CSP to `img-src 'self' data:` and proxy any required third-party images through a server-side fetcher that strips referrer/cookies (or simply require images to live under `/covers/`). If you keep `https:`, drop `data:` from the CSP and rely on nh3's allowlist alone.
- **Verification:** With the tightened CSP, render `<img src="https://example.com/x.png">` in a card body and confirm the browser blocks the request (DevTools → Console: "Refused to load the image").

### Login throttling lives only in nginx — direct backend access bypasses it
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\routes.py`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\deploy\nginx\linkgarden.conf:15,101-115`
- **Symptom:** The10r/min/IP cap is an nginx `limit_req_zone`. The backend listens on `127.0.0.1:5001` so it is not directly reachable from the internet *today*, but: (a) any operator who ever exposes the port for debugging removes the only credential-stuffing brake, (b) requests forwarded with `X-Forwarded-For` are not used by nginx for the limit key (`$binary_remote_addr` is the connection peer, fine for the front edge but means a misconfigured front-front proxy collapses every IP into one). Defense-in-depth: also enforce on the application.
- **Root cause:** Single-layer rate limiting; no app-side knowledge of attempt frequency.
- **Fix:** Add a per-username + per-IP attempt counter in the auth service (Redis or, for SQLite v1, a `login_attempts(username, ip, attempted_at)` table). Lock for 60s after5 failures in the last 5 minutes; serve `429 too_many_attempts`. Record success too so a successful login resets the counter.
- **Verification:** Test 6 wrong-password attempts in succession; the 6th should return 429.

### Bcrypt timing-equalization dummy hash is malformed; `verify_password` short-circuits to False on `ValueError`
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\service.py:80`, `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\security.py:36-43`
- **Symptom:** `_DUMMY_HASH = "$2b$12$abcdefghijklmnopqrstuuOZ0X1l5N4w2C8b6r3v0z1Y7s9eK6QHy"`. A real bcrypt hash is `$2b$<rounds>$<22-char salt><31-char digest>` totalling 60 bytes. The shipped string has a 22-char salt segment but a 30-char digest segment (count it). `bcrypt.checkpw` on a malformed hash raises `ValueError`, which `verify_password` catches and returns `False` immediately — without doing the bcrypt work. Result: the "user-not-found" branch is fast, the "wrong-password" branch is slow (12-round bcrypt ≈ 250ms), and the timing oracle the dummy was meant to close is wide open.
- **Root cause:** Hand-edited placeholder string was never validated.
- **Fix:** Generate a real hash at module load: `_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))`. Constant cost across every process restart, no risk of using it for actual auth (the random plaintext is discarded).
- **Verification:** Add `tests/unit/test_security.py::test_dummy_hash_is_valid_bcrypt` that asserts `verify_password("anything", _DUMMY_HASH)` returns `False` *and* takes ≥50ms (i.e., bcrypt actually ran). Compare timings to the wrong-password path — should agree within 10%.

### `/api/v1/docs` and `/api/v1/openapi.json` are public in production
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\main.py:148-150`
- **Symptom:** `create_app` unconditionally enables `docs_url`, `redoc_url`, `openapi_url`. In production any unauthenticated visitor can enumerate every admin endpoint and its expected payload at `https://linkgarden.example.com/api/v1/docs`. This is an attack-surface map a real attacker would otherwise need to crawl for — it now sits one URL away.
- **Root cause:** No `APP_ENV` gating.
- **Fix:** When `settings.APP_ENV == "prod"`, pass `docs_url=None, redoc_url=None`. Keep `openapi_url` if you need the contract test, but mount it under an admin-only dep, or behind a per-IP allowlist in nginx.
- **Verification:** `curl -fsS https://linkgarden.example.com/api/v1/docs` returns404 in prod; same on the test config with `APP_ENV=prod`.

### Markdown allowlist permits `<input>` with `type` attribute — turns task-list items into HTML form fields
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\services\markdown.py:81, 99`
- **Symptom:** `ALLOWED_TAGS` includes `"input"` and `ALLOWED_ATTRS["input"] = {"type", "checked", "disabled"}`. The intent is GFM task-lists (`- [ ] item`). nh3 will keep any `<input>` produced by the renderer, includingones with `type="text"`, `type="image"`, `type="hidden"` — markdown-it's tasklists plugin always emits `type="checkbox"` plus `disabled`, but if a future plugin or a markdown-source HTML escape leakever outputs a non-checkbox `<input>`, nh3 has been told it's fine. `type="image"` carries a `src` (rejected because `src` is not in the input attr list) but `type="hidden"` is enough to host clickjacking-helpful state. Also `<input>` is a void tag — an unbalanced parser bug elsewhere can pivot off it.
- **Root cause:** Allowlist is broader than the actual GFM output.
- **Fix:** Pin to checkbox-only via `set_tag_attribute_values={"input": {"type": "checkbox"}}` and shrink `ALLOWED_ATTRS["input"]` to `{"checked", "disabled"}`. Better still, post-process `<input>` tokens to render as a `<span class="task-checkbox">` and drop the tag from the allowlist entirely.
- **Verification:** Add a corpus row in `tests/unit/test_markdown.py` asserting `render_markdown('<input type="hidden" name="x">')` → no `<input>` survives, and `render_markdown('- [x] item')` → exactly one `<input type="checkbox" checked disabled>` survives.

### `client_max_body_size 6m` only protects covers — JSON endpoints have no upper bound at the edge
- **Severity:** P1
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\deploy\nginx\linkgarden.conf:60`
- **Symptom:** 6 MiB applies to every `/api/` path, including JSON. A 6 MiB markdown body posted to `POST /api/v1/cards` is parsed by Pydantic (allocates), passed to markdown-it (allocates), then to nh3 (allocates), then persisted as `body_html`. A handful of concurrent admin posts at6 MiB each can OOM a `-w 2` gunicorn. Card body is never legitimately that large.
- **Root cause:** Single body-size knob.
- **Fix:** Add a per-location `client_max_body_size` override. Cards routes get `1m`; covers gets `6m`. In FastAPI, add a `max_length` to `CardCreate.body`/`CardUpdate.body` (e.g. 256 KiB) so an attacker can't squeeze a 1 MiB markdown bomb through.
- **Verification:** `curl -fsS -X POST -d "$(python -c 'print("a"*2_000_000)')" https://.../api/v1/cards` returns 413 from nginx; a 200 KiB body with valid auth succeeds.

## P2 findings (nice-to-have)

### Legacy `backend/app.py`, `backend/data/`, `backend/content/` still in tree alongside the new code
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\app.py`, `backend/data/cards.json`, `backend/content/notes/`
- **Symptom:** The pre-refactor Flask app is still importable via `python -c "import app"` if anyone runs from `backend/`. The legacy data tree is the integration source for the migrator, but the spec says it should be `chmod -R a-w` after migration. With the new layout `app.py` shadows the package layout (`from app.core import ...`) on Python's import path — depending on `sys.path` order, the wrong module wins and tests can pass against stale code.
- **Root cause:** Legacy files were not removed in the cutover.
- **Fix:** Move `backend/app.py` to `backend/_legacy/app.py` (or delete after the migrator's last test run), add `backend/data/` and `backend/content/` to `.gitignore` if they are operator-supplied snapshots, or commit them under `legacy/` outside the import path.
- **Verification:** `cd backend && python -c "import app; print(app.__file__)"` resolves to `src/app/__init__.py`, not `backend/app.py`. CI to grep for the legacy filename.

### `Settings` rejects placeholder JWT secrets only at instance construction; the example file ships with a placeholder that passes `min_length`
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\deploy\env\linkgarden.env.example:33`
- **Symptom:** Beyond the P1 above, the example value `REPLACE_ME_WITH_openssl_rand_hex_32_OUTPUT` is 41 ASCII chars and passes the `min_length=32` check. The convention-based fix in P1 closes this, but separately consider committing the example with a literal `__UNSET__` and making `Settings` refuse `__UNSET__`. That gives one canonical "you forgot to set this" pattern across all secrets.
- **Root cause:** Each placeholder spells out a different sentinel.
- **Fix:** Standardise on `__UNSET__`. Refuse it everywhere a secret is read.
- **Verification:** `grep -r REPLACE_ME deploy/env` returns nothing; settings tests assert `__UNSET__` rejected on every secret field.

### Cover URL cache-buster `?v=int(time.time())` is 1-second granular — concurrent uploads collide
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\covers\service.py:342-343`
- **Symptom:** Two cover uploads to the same card within the same second produce the same `?v=` value. nginx serves with `Cache-Control: public, immutable`; CDNs (and Chrome's bfcache) honour that. The second upload's bytes will not be visible to clients that already cached the first.
- **Root cause:** Coarse-grained timestamp.
- **Fix:** Use `time.time_ns()` or include a 6-byte random suffix. Better: hash the bytes (sha256 first12 chars) and use that — content-addressable, idempotent, immutable-safe.
- **Verification:** Upload two distinct images for the same card within the same second; assert returned URLs differ; assert curling each URL returns the corresponding bytes.

### structlog and stdlib `logging` are mixed; some call sites bypass the structlog formatter
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\cards\service.py:48,299`
- **Symptom:** `_log = logging.getLogger(__name__)` and `_log.warning("failed_to_unlink_cover", extra={"path": ...})`. structlog is used elsewhere; this call goes through stdlib and won't be JSON-formatted in prod. Operators searching for `failed_to_unlink_cover` events get inconsistent records.
- **Root cause:** Mixed logger usage.
- **Fix:** `structlog.get_logger(__name__)` everywhere.
- **Verification:** `grep "logging.getLogger" backend/src/app` returns no hits.

### Admin role check is a string compare on `user.role == "admin"` — typo or missed migration silently demotes everyone
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\features\auth\deps.py:93`
- **Symptom:** `role` is `String(16)` with `default="admin"`. There is no enum, no DB-side CHECK constraint, no Alembic constraint. A future "Admin"/"administrator"/`"admin "` value ends up `Forbidden`. Worse, an UPDATE that accidentally clears the field returns an empty string, which silently flips the user to non-admin without anyone noticing — login still succeeds, every admin route403s.
- **Root cause:** Schema is loose.
- **Fix:** Add a `CHECK (role IN ('admin'))` constraint in Alembic; or define `Role(StrEnum)` and validate at the model level.
- **Verification:** Direct UPDATE of `users.role ='foo'` raises `IntegrityError`.

### `_legacy_redirect`308 also reissues the body on `OPTIONS` and `HEAD`
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\main.py:92-116`
- **Symptom:** The shim accepts `OPTIONS` and `HEAD` and308s them. CORS preflight (`OPTIONS`) should never308 — browsers may not follow on preflight, breaking the SPA when the legacy shim is hit. Low likelihood given the SPA was cut over.
- **Root cause:** Methods list copied from the spec verbatim.
- **Fix:** Drop `OPTIONS` from the legacy method list; have CORS middleware respond directly.
- **Verification:** `curl -X OPTIONS -i .../api/cards` returns CORS headers from the middleware (not 308).

### `bcrypt.gensalt()` cost factor unspecified — uses bcrypt default (12)
- **Severity:** P2
- **Location:** `G:\AI\AI_private\Cluade_code_projects\LinkGarden\backend\src\app\core\security.py:32`
- **Symptom:** `bcrypt.gensalt()` uses12 rounds by default at the time of writing, but defaults change. Pinning the cost at the call site documents the choice and survives library upgrades.
- **Root cause:** Implicit default.
- **Fix:** `bcrypt.gensalt(rounds=12)` with the rounds value pulled from a `Settings.BCRYPT_ROUNDS = 12` field so test runs can lower it.
- **Verification:** `tests/unit/test_security.py::test_hash_password_uses_12_rounds` asserts the resulting hash starts with `$2b$12$`.

## Summary

The architecture and per-module spec are solid (HS256 pinned, sanitiser explicit, atomic writes, structured errors, hardened systemd, edge rate-limit), but the actual tree ships with three live boot-time bugs (cover admin gate fails open, validation handler returns 500, login keyword crashes the worker) and one routing mismatch (auth router missing its prefix) that together mean a fresh deploy off this commit cannot accept a single login *and* exposes uploads as anonymous — exactly the failure mode the spec was written to prevent. Fix the four P0s and the JWT/admin-password placeholder validators (P1) before any environment that can be reached over the public internet sees this build; the rest of the P1/P2 list is reasonable to land in the same release window. Confidence in the underlying design: high. Confidence in the merged tree as-is: low — the phase3 report listed every P0 here as known and unfixed.
