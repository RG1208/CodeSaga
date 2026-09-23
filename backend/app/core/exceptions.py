"""Application errors and the handlers that turn them into HTTP responses.

Every error response has the same shape, which keeps the frontend simple:

    {"error": {"code": "not_found", "message": "...", "details": null, "request_id": "..."}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class AppError(Exception):
    """Base class for expected, client-visible errors raised by services."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(
        self, message: str | None = None, *, code: str | None = None, details: Any = None
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource already exists."


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"
    message = "This action is not allowed."


class UnprocessableError(AppError):
    """The request is well-formed but its content is not acceptable (e.g. a bad URL)."""

    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "unprocessable"
    message = "The request could not be processed."


class ServiceUnavailableError(AppError):
    """A local component needed for this request is not ready (e.g. an ML model)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "This feature is temporarily unavailable."


class UpstreamServiceError(AppError):
    """An external dependency (such as GitHub) failed or could not be reached."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"
    message = "An external service is unavailable."


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id,
            }
        },
        headers=response_headers,
    )


def unhandled_error_response(request: Request) -> JSONResponse:
    """Generic 500 response that never leaks internal details to the client."""
    return error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=AppError.code,
        message=AppError.message,
    )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


_HTTP_STATUS_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
}


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return error_response(
        request,
        status_code=exc.status_code,
        code=_HTTP_STATUS_CODES.get(exc.status_code, "http_error"),
        message=str(exc.detail),
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Keep only JSON-safe fields; `ctx` can contain raw exception objects.
    details = [
        {"loc": list(error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="validation_error",
        message="Request validation failed.",
        details=details,
    )


async def integrity_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Safety net for races that slip past service-level uniqueness checks.
    logger.warning("database integrity error", extra={"error": str(exc.__cause__ or exc)})
    return error_response(
        request,
        status_code=status.HTTP_409_CONFLICT,
        code=ConflictError.code,
        message="The request conflicts with existing data.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
