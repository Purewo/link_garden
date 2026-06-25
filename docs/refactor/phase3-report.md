# Phase 3 — Implementation report

## Headline

All14 builder units delivered their owned paths; integration is gated on resolving a small number of cross-unit signature and wiring mismatches before CI will go green end-to-end.

## Status per unit

| id| title                                              | status               | notable gaps |
|-----|----------------------------------------------------|----------------------|--------------|
| B1  | Backend scaffolding + core                         | done, verified       | `features/__init__.py` deliberately omitted (PEP 420); `_validation_exception_handler` leaks Pydantic `ctx.error` ValueError into JSON envelope (flagged by B5) |
| B2  | DB schema + Alembic init + admin seed              | done, 12/12 tests    | Notes B4↔B1 kwarg mismatch on `encode_jwt(ttl=)` vs `ttl_seconds`; depends on B1 envs |
| B3  | Markdown service                                   | done, 65 tests / 100% cov | Dropped `rel` from allowlist (nh3 conflict with `link_rel`); added `<s>` for GFM strikethrough; deflist tags dropped |
| B4  | Auth feature                | files written, not run | Router has no `/auth` prefix — currently mounts as `/api/v1/login`, `/api/v1/me`; depends on B1+B2 to test |
| B5  | Cards feature                                      | done, 58/58 own tests; 186/201 full suite | Fixed `AppError(code, message)` signature site-wide; needs B1 validation-handler fix and B4 prefix fix for full wire coverage |
| B6  | Covers feature                                     | done, 20/20 tests    | Calls `CardRepository.set_cover` — confirm B5 exposes this exact name; `CoverUploadResponse.card` typed `Any` to avoid B5 import |
| B7  | Tags feature + OpenAPI snapshot                    | written, not run (no Python on host) | `openapi_snapshot.json` ships empty by design; first run with `LG_UPDATE_OPENAPI_SNAPSHOT=1` regenerates and commits |
| B8  | Migration script| done, 12/12 tests    | Lazy-imports B3's `render_markdown`; falls back to raw markdown with WARN if missing |
| B9  | Frontend scaffolding + shared kit                  | install + typecheck + build green | Legacy `vite.config.js` and `src/main.js` must be deleted before `pnpm dev` works without `--config` flag |
| B10 | Auth feature frontend                              | written, not run     | Persisted-state plugin option name (`pick` vs `paths`) version-dependent; relies on B9 runtime registration |
| B11 | Cards feature frontend (public)                    | written, not run     | `CardListQuery` defined locally (openapi-ts can't lift `Query()` models); widens `CardItem` to optionally read `url` |
| B12 | Admin frontend (publish + manage)                  | written, not run     | `useCoverUpload` placed under `shared/composables/` per §9 (not `features/covers/composables` per §4.1); `// @ts-expect-error` on multipart body |
| B13 | Deployment artifacts                | scripts syntax-clean, not exercised on host | `scripts/deploy.sh` hard-codes `/usr/local/bin/uv` and Debian-style nginx paths; legacy unit rename assumed |
| B14 | Repo hygiene + CI workflows + README/CLAUDE.md| YAML validated, not executed | Workflows fail until B1/B7/B9 artifacts land — desired behaviour; uses `astral-sh/setup-uv@v3` |

## Critical contradictions found across units

1. **`encode_jwt` kwarg mismatch (B1 vs B4).** B1 ships `encode_jwt(claims, ttl_seconds=...)`; B4 calls `encode_jwt(claims, ttl=...)`. Rename in one place before merge — recommend updating B4 to match B1.
2. **Auth router prefix missing (B4 vs B5/spec §3.5).** B4 ships `router = APIRouter()` with no `/auth` prefix; endpoints land at `/api/v1/login`. Fix: add `prefix="/auth"` either at router construction or on `include_router`.
3. **`_validation_exception_handler` serialization bug (B1, flagged by B5).** `[dict(err) for err in errors]` keeps a non-JSON `ctx.error` ValueError. Apply `jsonable_encoder` or strip `ctx` before serializing.
4. **`useCoverUpload` location (§4.1 vs §9).** Spec §9 places it under `shared/composables/`; §4.1 directory tree implied `features/covers/composables/`. B12 followed §9 ("law"). Verify any docs/diagrams referencing the §4.1 path get updated.
5. **`CardRepository.set_cover` name (B6 expectation vs B5 surface).** B6 calls `card_repo.set_cover(card_id, public_url)`; confirm B5 exports exactly this method name before merging covers.

## Recommended merge order

1. **B1** (everyone imports `app.core.*`). Apply the validation-handler fix and pick the canonical `encode_jwt` kwarg before tagging the merge commit.
2. **B2** and **B3** in parallel (no cross-deps).
3. **B4** with the `/auth` prefix fix applied.
4. **B5**, then **B6** and **B7** in parallel (B6 needs `set_cover` on B5's repo; B7 only needs B2).
5. **B8** (needs B2 + B5; B3 lazy-imported).
6. **B9** (frontend scaffolding stands alone; also delete legacy `vite.config.js`/`src/main.js`).
7. **B10**, then **B11**, then **B12** (frontend feature waterfall).
8. **B13** and **B14** in parallel (docs/infra; CI goes green once 1-9 land).

After step 4 run B7's snapshot regen with `LG_UPDATE_OPENAPI_SNAPSHOT=1` and commit the resulting `openapi_snapshot.json` plus a fresh `frontend/openapi/schema.json` via `pnpm gen:api`.

## Integration risks worth a Phase-4 review pass

- **End-to-end test coverage is thin in the merged tree.** Each unit ran tests in isolation with mocks or `dependency_overrides`; the full suite shows 10failures + 5 errors in B5's run (B4auth, B7 tags, openapi snapshot). Phase 4 should run the full `pytest` + `pnpm test` after each merge step and treat the first all-green commit as the integration baseline.
- **OpenAPI contract gate is currently a placeholder.** `frontend/openapi/schema.json` was hand-rolled by B9, B7's snapshot ships empty, and B11 defined `CardListQuery` locally. Drift between server and client types is silent until the contract workflow runs against a live `create_app()` — make this a blocking CI step before any frontend PR merges.
- **Windows vs POSIX file semantics in covers and migration.** B6's atomic write uses `os.replace` (fine on Windows for single-writer); B8's importer assumes POSIX line endings. Verify both on the production Linux host before cutover.
- **Sudoers + service rename on deploy host.** B13 assumes a `linkgarden` user with a sudoers dropin and a legacy unit named `linkgarden-legacy.service`. Current production likely runs `linkgarden.service` for the Flask app — schedule the rename in the cutover window.
- **Pyright strict relaxation in B1.** Three `reportUnknown*` rules are off globally; B2/B3/B4/B5 may unknowingly leak `Any` through public APIs. Phase 4 should re-enable per-file strict for `core/`, `features/auth/service.py`, `services/markdown.py`, and `features/cards/service.py`.
- **Frontend bundle warnings.** `hljs` (969 KB) and `md-editor-v3` (864 KB) chunks are split but still hefty. Confirm B11/B12 dynamic-import them behind the detail and admin routes — a regression here doubles homepage TTI.
- **Legacy file cleanup.** `frontend/vite.config.js`, `frontend/src/main.js`, legacy `src/views/*` and `src/components/*` need to be deleted in the integrator's cleanup commit (B9 ignores them in lint but they will shadow real modules at runtime).
