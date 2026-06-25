#!/usr/bin/env bash
# Convenience wrapper around the frontend OpenAPI codegen flow.
#
# What it does:
#   1. cd into frontend/.
#   2. Run `pnpm gen:api`, which executes `tsx scripts/gen-api.ts` (see B9):
#        - tries http://127.0.0.1:5001/api/v1/openapi.json
#        - falls back to the committed openapi/schema.json
#        - writes openapi/schema.json (pretty, deterministic)
#        - pipes through openapi-typescript -> src/shared/api/schema.d.ts
#   3. Optionally fail (--check) if the generated outputs differ from HEAD,
#      so CI can use the same entry point as developers.
#
# Usage:
#   scripts/gen-api.sh                  # regenerate locally
#   scripts/gen-api.sh --check          # regenerate and fail on git drift
#   BACKEND_URL=http://localhost:5001 scripts/gen-api.sh
#
# Env vars (forwarded to the underlying tsx script):
#   BACKEND_URL   override the FastAPI base URL probed for openapi.json
#   GEN_API_OFFLINE=1  skip the network probe; use the committed snapshot
#
# Exit codes:
#   0  success
#   1  codegen failure
#   2  --check found generated files differ from git
#   3  prerequisite missing (pnpm/node)

set -Eeuo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"

CHECK_MODE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --check) CHECK_MODE=1; shift ;;
        -h|--help)
            sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) printf 'unknown flag: %s\n' "$1" >&2; exit 1 ;;
    esac
done

command -v pnpm >/dev/null 2>&1 || { echo "pnpm not on PATH" >&2; exit 3; }
command -v node >/dev/null 2>&1 || { echo "node not on PATH" >&2; exit 3; }

[[ -d "$FRONTEND_DIR" ]] || { echo "no frontend/ at $FRONTEND_DIR" >&2; exit 1; }

echo "==> regenerating API types in $FRONTEND_DIR"
pnpm --dir "$FRONTEND_DIR" gen:api

if (( CHECK_MODE )); then
    echo "==> --check: diffing generated outputs against git HEAD"
    # The two artifacts produced by the codegen step. If either drifted, fail
    # so CI surfaces the missing commit immediately.
    targets=("frontend/openapi/schema.json" "frontend/src/shared/api/schema.d.ts")
    if ! git -C "$REPO_ROOT" diff --exit-code -- "${targets[@]}"; then
        echo "ERROR: regenerated outputs differ from HEAD; commit them." >&2
        exit 2
    fi
    echo "==> --check: clean"
fi

echo "==> done"
