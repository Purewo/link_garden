"""FastAPI application factory.

``create_app`` is the integration seam. It builds the ASGI app, registers
exception handlers, mounts the stable ``/api/health`` monitor path, mounts the
versioned ``/api/v1`` router, and installs the legacy ``/api/*`` 308 shim so
old clients keep working for exactly one release.

Sibling features (auth, cards, covers, tags) ship their own routers and are
imported lazily through :func:`_load_feature_routers`. Missing modules are
logged at warning level rather than aborting boot — this keeps B1's deliverable
runnable in isolation, and the integrator wires the rest after merge.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Final

import structlog
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import Settings, get_settings
from app.core.db import dispose_engine
from app.core.errors import register_handlers
from app.core.logging import RequestContextMiddleware, configure_logging
from app.features.health.routes import router as health_router

logger = structlog.get_logger(__name__)


# Tuples of (module_path, attribute_name). Order matters only for OpenAPI
# stability. Anything that fails to import is logged + skipped.
_FEATURE_ROUTERS: Final[tuple[tuple[str, str], ...]] = (
    ("app.features.auth.routes", "router"),
    ("app.features.cards.routes", "router"),
    ("app.features.covers.routes", "router"),
    ("app.features.tags.routes", "router"),
)


def _load_feature_routers() -> list[APIRouter]:
    """Import every feature router, skipping ones that aren't merged yet."""

    routers: list[APIRouter] = []
    for module_path, attr in _FEATURE_ROUTERS:
        try:
            module = importlib.import_module(module_path)
        except ModuleNotFoundError:
            logger.warning("feature_router_missing", module=module_path)
            continue
        router = getattr(module, attr, None)
        if router is None:
            logger.warning("feature_router_attr_missing", module=module_path, attr=attr)
            continue
        if not isinstance(router, APIRouter):
            logger.warning(
                "feature_router_wrong_type",
                module=module_path,
                attr=attr,
                got=type(router).__name__,
            )
            continue
        routers.append(router)
    return routers


def _build_v1_router() -> APIRouter:
    """Compose the ``/api/v1`` router from feature routers."""

    v1 = APIRouter(prefix="/api/v1")
    v1.include_router(health_router)
    for feature_router in _load_feature_routers():
        v1.include_router(feature_router)
    return v1


def _register_legacy_shim(app: FastAPI) -> None:
    """Install the catch-all 308 redirect from ``/api/<path>`` to ``/api/v1/<path>``.

    Registered AFTER the v1 router so it never shadows real routes. Excludes
    ``health`` and anything beginning with ``v1/`` so the explicit monitor
    mount and the v1 router both take precedence.
    """

    legacy_logger = structlog.get_logger("app.legacy")

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
        name="legacy_redirect",
    )
    async def _legacy_redirect(  # pyright: ignore[reportUnusedFunction]
        path: str, request: Request
    ) -> RedirectResponse:
        if path == "health" or path.startswith("v1/") or path == "v1":
            # Defensive: the explicit mounts should already match these.
            raise HTTPException(status_code=404)

        target = f"/api/v1/{path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"

        legacy_logger.warning(
            "legacy_api_hit",
            method=request.method,
            original_path=request.url.path,
            target=target,
            user_agent=request.headers.get("user-agent", ""),
        )
        return RedirectResponse(target, status_code=308)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: log boot, dispose engine on shutdown."""

    logger.info("app_startup")
    try:
        yield
    finally:
        logger.info("app_shutdown")
        try:
            await dispose_engine()
        except Exception:
            logger.exception("engine_dispose_failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a configured :class:`FastAPI` instance.

    ``settings`` is dependency-injected primarily for tests; production passes
    ``None`` so the cached :func:`get_settings` singleton is used.
    """

    settings = settings or get_settings()
    configure_logging(env=settings.APP_ENV)

    # In production, suppress the public docs surface — the live OpenAPI
    # blueprint should not be discoverable through Google/random scans.
    docs_url: str | None = "/api/v1/docs"
    redoc_url: str | None = "/api/v1/redoc"
    if settings.APP_ENV == "prod":
        docs_url = None
        redoc_url = None

    app = FastAPI(
        title="LinkGarden API",
        version="0.1.0",
        lifespan=_lifespan,
        openapi_url="/api/v1/openapi.json",
        docs_url=docs_url,
        redoc_url=redoc_url,
    )

    # Quiet uvicorn's default access logger; structlog covers it via the
    # request-context middleware.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    register_handlers(app)
    app.add_middleware(RequestContextMiddleware)

    if settings.APP_ENV == "dev" and settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["x-request-id"],
        )

    # 1. Mount the version-stable monitor path FIRST so the legacy shim's
    #    `/api/{path:path}` catch-all can't accidentally swallow it.
    app.include_router(health_router, prefix="/api")

    # 2. Versioned router.
    app.include_router(_build_v1_router())

    # 3. Static covers mount. Production sets the same path under nginx;
    #    in dev and prod the URL prefix is identical so frontend code does
    #    not need an environment switch.
    covers_dir = settings.covers_dir
    covers_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        settings.COVERS_PUBLIC_PREFIX,
        StaticFiles(directory=covers_dir),
        name="covers",
    )

    # 4. Legacy 308 shim registered last.
    _register_legacy_shim(app)

    return app


__all__ = ["create_app"]
