"""Domain exception types and their FastAPI handlers.

Every error response has the shape::

    {"detail": {"code": "<machine>", "message": "<human>"}}

with an HTTP status matching the exception class.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)


class AppError(Exception):
    code = "error"
    status = 400

    def __init__(self, message: str, *, code: str | None = None, status: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status


class DomainError(AppError):
    """Business-rule violation. 422 by default."""

    code = "domain_error"
    status = 422

    def __init__(self, code: str, message: str, *, status: int = 422):
        super().__init__(message, code=code, status=status)


class AuthError(AppError):
    """Not authenticated / not authorised. 401 by default, 403 when passed."""

    code = "not_authenticated"
    status = 401

    def __init__(
        self, message: str = "Not authenticated", *, status: int = 401, code: str | None = None
    ):
        super().__init__(
            message,
            code=code or ("forbidden" if status == 403 else "not_authenticated"),
            status=status,
        )


class NotFoundError(AppError):
    code = "not_found"
    status = 404

    def __init__(self, message: str = "Not found"):
        super().__init__(message, code="not_found", status=404)


class RateLimitError(AppError):
    code = "rate_limited"
    status = 429

    def __init__(self, message: str, *, retry_after: int):
        super().__init__(message, code="rate_limited", status=429)
        self.retry_after = retry_after


def _body(code: str, message: str) -> dict:
    return {"detail": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        headers = {}
        if isinstance(exc, RateLimitError):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(
            status_code=exc.status,
            content=_body(exc.code, exc.message),
            headers=headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        parts: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()) if p != "body")
            parts.append(f"{loc or 'body'}: {err.get('msg', 'invalid')}")
        return JSONResponse(
            status_code=422,
            content=_body("validation_error", "; ".join(parts) or "Invalid request"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_body("internal_error", "Internal server error"),
        )
