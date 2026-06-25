#!/usr/bin/env bash
# LinkGarden production deploy driver.
#
# Implements the rollout flow specified in docs/refactor/phase2-architecture.md §6
# and the operator runbook in docs/refactor/deploy-runbook.md. This script is
# meant to run from a developer machine (or CI runner) against a single
# pre-provisioned host.
#
# Flow (paraphrased from the architecture spec):
#   1. Local build: install pnpm deps, regenerate API types, typecheck, lint,
#      test, build the frontend bundle. Failure aborts before anything touches
#      the host.
#   2. Backend deploy: ssh to the host, fetch + checkout the requested git ref,
#      sync the uv venv from the locked manifest.
#   3. Restart backend: systemctl restart linkgarden.service. The unit's
#      ExecStartPre runs `alembic upgrade head`; a bad migration aborts the
#      restart and leaves the previous binary serving traffic.
#   4. Backend smoke: curl /api/v1/health on the host's loopback, assert
#      {"ok": true}. Bail before touching the frontend if this fails.
#   5. Frontend deploy: rsync dist/ onto the host. nginx picks up new files
#      without a reload.
#   6. End-to-end smoke: curl the public /api/health and the SPA root.
#   7. nginx config drift: compare deploy/nginx/linkgarden.conf against the
#      host's copy. Refuse to proceed (or warn, depending on flag) if they
#      diverge. --force-nginx skips the gate.
#
# Usage:
#   scripts/deploy.sh [--dry-run] [--ref <git-sha>] [--host <host>]
#                     [--user <ssh-user>] [--skip-build]
#                     [--force-nginx] [--reload-nginx]
#                     [--public-url <https://...>] [--help]
#
# Required env (sourced before flag parsing; flags win):
#   LG_HOST          ssh hostname of the deploy target
#   LG_SSH_USER      ssh user (default: linkgarden)
#   LG_PUBLIC_URL    https URL fronted by nginx (e.g. https://linkgarden.example.com)
#   LG_REMOTE_ROOT   prefix on the host (default: /srv/linkgarden)
#
# Exit codes:
#   0  success
#   1  generic failure (any step aborted)
#   2  bad invocation (missing required flag/env)
#   3  prerequisite check failed (missing tool, unclean working tree)
#   4  nginx config drift; rerun with --force-nginx after review
#   5  smoke check failed; backend was restarted but frontend was NOT shipped

set -Eeuo pipefail
shopt -s inherit_errexit 2>/dev/null || true

# ---------------------------------------------------------------------------
# Defaults + global state
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_NAME="${0##*/}"
DRY_RUN=0
SKIP_BUILD=0
FORCE_NGINX=0
RELOAD_NGINX=0
GIT_REF=""
LG_HOST="${LG_HOST:-}"
LG_SSH_USER="${LG_SSH_USER:-linkgarden}"
LG_PUBLIC_URL="${LG_PUBLIC_URL:-}"
LG_REMOTE_ROOT="${LG_REMOTE_ROOT:-/srv/linkgarden}"

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
warn() { printf '[%s] WARN %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; }
die()  { printf '[%s] FATAL %s\n' "$(date -u +%H:%M:%SZ)" "$*" >&2; exit "${2:-1}"; }

usage() {
    sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)        DRY_RUN=1; shift ;;
        --ref)            GIT_REF="${2:?--ref needs a value}"; shift 2 ;;
        --host)           LG_HOST="${2:?--host needs a value}"; shift 2 ;;
        --user)           LG_SSH_USER="${2:?--user needs a value}"; shift 2 ;;
        --public-url)     LG_PUBLIC_URL="${2:?--public-url needs a value}"; shift 2 ;;
        --skip-build)     SKIP_BUILD=1; shift ;;
        --force-nginx)    FORCE_NGINX=1; shift ;;
        --reload-nginx)   RELOAD_NGINX=1; shift ;;
        -h|--help)        usage ;;
        *)                die "unknown flag: $1" 2 ;;
    esac
done

[[ -n "$LG_HOST" ]]       || die "LG_HOST or --host is required" 2
[[ -n "$LG_PUBLIC_URL" ]] || die "LG_PUBLIC_URL or --public-url is required" 2

if [[ -z "$GIT_REF" ]]; then
    GIT_REF="$(git -C "$REPO_ROOT" rev-parse HEAD)"
fi

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# run_local <cmd...>  — execute on this machine; print under --dry-run.
run_local() {
    if (( DRY_RUN )); then
        printf '  [dry-run] local$ %s\n' "$*"
        return 0
    fi
    "$@"
}

# run_remote <cmd-string>  — execute on the deploy host. The argument is a
# single string passed to bash -lc on the remote so quoting on the caller side
# stays sane.
run_remote() {
    local cmd="$1"
    if (( DRY_RUN )); then
        printf '  [dry-run] %s@%s$ %s\n' "$LG_SSH_USER" "$LG_HOST" "$cmd"
        return 0
    fi
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        "$LG_SSH_USER@$LG_HOST" bash -lc "$cmd"
}

# remote_capture <cmd-string>  — same as run_remote but returns stdout. Always
# runs even in dry-run because the output is needed for downstream decisions.
remote_capture() {
    local cmd="$1"
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        "$LG_SSH_USER@$LG_HOST" bash -lc "$cmd"
}

require_tool() {
    command -v "$1" >/dev/null 2>&1 || die "missing required tool: $1" 3
}

# ---------------------------------------------------------------------------
# Step 0 — preflight
# ---------------------------------------------------------------------------
preflight() {
    log "preflight: checking local tools"
    require_tool git
    require_tool ssh
    require_tool rsync
    require_tool curl
    if (( ! SKIP_BUILD )); then
        require_tool pnpm
        require_tool node
    fi

    log "preflight: deploying ref $GIT_REF to $LG_SSH_USER@$LG_HOST"

    # Require a clean tree when we are about to ship from it (otherwise the
    # remote checkout doesn't reflect what was built locally).
    if (( ! SKIP_BUILD )); then
        if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
            warn "working tree is dirty; built frontend may not match remote checkout"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Step 1 — local frontend build
# ---------------------------------------------------------------------------
build_frontend() {
    if (( SKIP_BUILD )); then
        log "build: --skip-build set, skipping pnpm pipeline"
        return 0
    fi
    log "build: pnpm install --frozen-lockfile"
    run_local pnpm --dir "$REPO_ROOT/frontend" install --frozen-lockfile

    log "build: regenerating API types (pnpm gen:api)"
    run_local pnpm --dir "$REPO_ROOT/frontend" gen:api

    log "build: vue-tsc / eslint / vitest / vite build"
    run_local pnpm --dir "$REPO_ROOT/frontend" typecheck
    run_local pnpm --dir "$REPO_ROOT/frontend" lint
    run_local pnpm --dir "$REPO_ROOT/frontend" test --run
    run_local pnpm --dir "$REPO_ROOT/frontend" build

    if [[ ! -d "$REPO_ROOT/frontend/dist" ]] && (( ! DRY_RUN )); then
        die "build: frontend/dist not produced; aborting" 1
    fi
}

# ---------------------------------------------------------------------------
# Step 2 — backend deploy (git + uv sync)
# ---------------------------------------------------------------------------
deploy_backend() {
    local remote_backend="$LG_REMOTE_ROOT/backend"
    local cmd
    cmd="set -Eeuo pipefail
        cd '$remote_backend'
        git fetch --prune --tags origin
        git checkout --detach '$GIT_REF'
        git --no-pager log -1 --oneline
        # uv sync uses the committed uv.lock; --no-dev keeps the prod venv lean.
        /usr/local/bin/uv sync --no-dev --frozen"
    log "deploy: checking out $GIT_REF and syncing uv venv"
    run_remote "$cmd"
}

# ---------------------------------------------------------------------------
# Step 3 — nginx config drift gate
# ---------------------------------------------------------------------------
check_nginx_drift() {
    local remote_path="/etc/nginx/sites-available/linkgarden.conf"
    local local_path="$REPO_ROOT/deploy/nginx/linkgarden.conf"
    log "nginx: diffing $local_path against $LG_HOST:$remote_path"

    local remote_sum local_sum
    remote_sum="$(remote_capture "sha256sum '$remote_path' 2>/dev/null | awk '{print \$1}'" || true)"
    local_sum="$(sha256sum "$local_path" | awk '{print $1}')"

    if [[ -z "$remote_sum" ]]; then
        warn "nginx: no remote copy at $remote_path (first deploy?)"
    elif [[ "$remote_sum" == "$local_sum" ]]; then
        log "nginx: config matches host; no drift"
        return 0
    else
        warn "nginx: drift detected (remote $remote_sum != local $local_sum)"
        if (( ! FORCE_NGINX )); then
            die "nginx: refusing to proceed without --force-nginx after review" 4
        fi
    fi

    if (( RELOAD_NGINX || FORCE_NGINX )); then
        log "nginx: installing new config and reloading"
        # Run via sudo on the host. The deploy user must have a passwordless
        # sudoers entry for `nginx -t` and `systemctl reload nginx` (see runbook).
        local install_cmd
        install_cmd="set -Eeuo pipefail
            sudo install -m 0644 '$LG_REMOTE_ROOT/backend/deploy/nginx/linkgarden.conf' '$remote_path'
            sudo nginx -t
            sudo systemctl reload nginx"
        run_remote "$install_cmd"
    fi
}

# ---------------------------------------------------------------------------
# Step 4 — restart backend + smoke
# ---------------------------------------------------------------------------
restart_backend() {
    log "backend: systemctl restart linkgarden.service (runs alembic upgrade head)"
    run_remote "sudo systemctl restart linkgarden.service"

    log "backend: waiting for /api/v1/health on 127.0.0.1:5001"
    local probe
    probe="set -Eeuo pipefail
        for i in 1 2 3 4 5 6 7 8 9 10; do
            if curl -fsS --max-time 3 http://127.0.0.1:5001/api/v1/health | grep -q '\"ok\":true'; then
                echo backend-healthy
                exit 0
            fi
            sleep 1
        done
        echo backend-unhealthy >&2
        exit 1"
    if (( DRY_RUN )); then
        printf '  [dry-run] %s@%s$ %s\n' "$LG_SSH_USER" "$LG_HOST" "<loopback smoke loop>"
    else
        run_remote "$probe" || die "backend smoke failed; previous frontend NOT replaced" 5
    fi
}

# ---------------------------------------------------------------------------
# Step 5 — frontend rsync
# ---------------------------------------------------------------------------
ship_frontend() {
    if (( SKIP_BUILD )); then
        log "frontend: --skip-build set; nothing to rsync"
        return 0
    fi
    local src="$REPO_ROOT/frontend/dist/"
    local dst="$LG_SSH_USER@$LG_HOST:$LG_REMOTE_ROOT/frontend/dist/"
    log "frontend: rsync $src -> $dst"
    local flags=(--archive --compress --delete --human-readable)
    (( DRY_RUN )) && flags+=(--dry-run)
    rsync "${flags[@]}" "$src" "$dst"
}

# ---------------------------------------------------------------------------
# Step 6 — public smoke checks
# ---------------------------------------------------------------------------
public_smoke() {
    log "smoke: $LG_PUBLIC_URL/api/health"
    if (( DRY_RUN )); then
        printf '  [dry-run] local$ curl -fsS %s/api/health\n' "$LG_PUBLIC_URL"
        printf '  [dry-run] local$ curl -fsS -o /dev/null %s/\n' "$LG_PUBLIC_URL"
        return 0
    fi
    local body
    body="$(curl -fsS --max-time 10 "$LG_PUBLIC_URL/api/health")" \
        || die "smoke: /api/health failed" 5
    if ! grep -q '"ok":true' <<<"$body"; then
        die "smoke: /api/health body unexpected: $body" 5
    fi
    curl -fsS --max-time 10 -o /dev/null "$LG_PUBLIC_URL/" \
        || die "smoke: SPA root failed" 5
    log "smoke: public endpoints healthy"
}

# ---------------------------------------------------------------------------
# Summary banner
# ---------------------------------------------------------------------------
summary() {
    log "deploy complete"
    log "  ref           : $GIT_REF"
    log "  host          : $LG_SSH_USER@$LG_HOST"
    log "  public url    : $LG_PUBLIC_URL"
    log "  dry-run       : $DRY_RUN"
    log "  skipped build : $SKIP_BUILD"
    log "  force-nginx   : $FORCE_NGINX"
}

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
main() {
    preflight
    build_frontend
    deploy_backend
    check_nginx_drift
    restart_backend
    ship_frontend
    public_smoke
    summary
}

main "$@"
