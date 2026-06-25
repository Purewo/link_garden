"""Application error hierarchy + envelope + exception handlers.

Failure responses follow the envelope::

    {"ok": false, "error": <human>, "code": <machine>, "detail": <optional>}

Success bodies are bare resources (no ``{ok: true, data}`` wrapper) so the
generated OpenAPI types stay flat. ``/api/health`` and explicit ack endpoints
return ``{ok: true}`` directly.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Final, Literal

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)


class ErrorEnvelope(BaseModel):
    """Wire shape of every failure response."""

    model_config = ConfigDict(extra="forbid")

    ok: Literal[False] = False
    error: str
    code: str
    detail: list[dict[str, Any]] | None = None


class OkResponse(BaseModel):
    """Shape of the bare-acknowledgement success response."""

    model_config = ConfigDict(extra="forbid")

    ok: Literal[True] = True


class AppError(Exception):
    """Base application error. Subclasses pin their HTTP status."""

    http_status: ClassVar[int] = 500
    default_code: ClassVar[str] = "internal_error"

    def __init__(
        self,
        code: str | None = None,
        message: str | None = None,
        *,
        detail: list[dict[str, Any]] | None = None,
    ) -> None:
        self.code = code or self.default_code
        self.message = message or self.code
        self.detail = detail
        super().__init__(self.message)


class BadRequest(AppError):
    http_status = status.HTTP_400_BAD_REQUEST
    default_code = "invalid_payload"


class Unauthorized(AppError):
    http_status = status.HTTP_401_UNAUTHORIZED
    default_code = "unauthenticated"


class Forbidden(AppError):
    http_status = status.HTTP_403_FORBIDDEN
    default_code = "forbidden"


class NotFound(AppError):
    http_status = status.HTTP_404_NOT_FOUND
    default_code = "not_found"


class Conflict(AppError):
    http_status = status.HTTP_409_CONFLICT
    default_code = "conflict"


class PayloadTooLarge(AppError):
    http_status = 413
    default_code = "payload_too_large"


class UnsupportedMediaType(AppError):
    http_status = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    default_code = "unsupported_media_type"


class Unprocessable(AppError):
    http_status = 422
    default_code = "unprocessable"


# Common HTTP-status -> machine code map for StarletteHTTPException fallback.
_STATUS_TO_CODE: Final[dict[int, str]] = {
    400: "http_400",
    401: "unauthenticated",
    403: "forbidden",
    404: "http_404",
    405: "http_405",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_failed",
    500: "internal_error",
}


def _request_context(request: Request) -> dict[str, str]:
    return {
        "method": request.method,
        "path": request.url.path,
    }


def _envelope_response(
    *, http_status: int, error: str, code: str, detail: list[dict[str, Any]] | None = None
) -> JSONResponse:
    payload: dict[str, Any] = {"ok": False, "error": error, "code": code}
    if detail is not None:
        payload["detail"] = detail
    return JSONResponse(status_code=http_status, content=payload)


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning(
        "app_error",
        code=exc.code,
        message=exc.message,
        **_request_context(request),
    )
    return _envelope_response(
        http_status=exc.http_status,
        error=exc.message,
        code=exc.code,
        detail=exc.detail,
    )


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code: str
    message: str
    if isinstance(exc.detail, dict):
        # Allow upstream code to pass a structured detail dict carrying its own
        # code/message; otherwise fall back to the status-derived defaults.
        code = str(exc.detail.get("code") or _STATUS_TO_CODE.get(exc.status_code, "error"))
        message = str(exc.detail.get("error") or exc.detail.get("message") or code)
    else:
        code = _STATUS_TO_CODE.get(exc.status_code, f"http_{exc.status_code}")
        message = str(exc.detail) if exc.detail else code

    logger.info(
        "http_exception",
        status_code=exc.status_code,
        code=code,
        **_request_context(request),
    )
    return _envelope_response(http_status=exc.status_code, error=message, code=code)


async def _validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(part) for part in first.get("loc", ()))
    msg = first.get("msg") or "validation failed"
    human = f"{loc}: {msg}" if loc else msg

    logger.info(
        "validation_failed",
        code="validation_failed",
        errors=len(errors),
        **_request_context(request),
    )
    return _envelope_response(
        http_status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error=human,
        code="validation_failed",
        # ``exc.errors()`` may include non-JSON ``ctx`` payloads; cast through
        # ``list[dict[str, Any]]`` to keep mypy/pyright honest.
        detail=[dict(err) for err in errors],
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "internal_error",
        code="internal_error",
        error=str(exc),
        exc_info=True,
        **_request_context(request),
    )
    return _envelope_response(
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error="internal server error",
        code="internal_error",
    )


def register_handlers(app: FastAPI) -> None:
    """Wire the four exception handlers onto ``app``."""

    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError, _validation_exception_handler  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, _unhandled_exception_handler)


# Re-export the stdlib logger threshold so structlog mirrors the same level.
_logging_initialised = False


def _ensure_stdlib_logging() -> None:
    """Configure stdlib logging once; structlog renders through it.

    Kept private + idempotent so multiple imports during tests don't stack
    handlers.
    """

    global _logging_initialised
    if _logging_initialised:
        return
    logging.basicConfig(level=logging.INFO)
    _logging_initialised = True


_ensure_stdlib_logging()


__all__ = [
    "AppError",
    "BadRequest",
    "Conflict",
    "ErrorEnvelope",
    "Forbidden",
    "NotFound",
    "OkResponse",
    "PayloadTooLarge",
    "Unauthorized",
    "Unprocessable",
    "UnsupportedMediaType",
    "register_handlers",
]
