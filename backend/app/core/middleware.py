"""HTTP middleware: request IDs, access logging and last-resort error handling."""

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.exceptions import REQUEST_ID_HEADER, unhandled_error_response
from app.core.logging import request_id_ctx

logger = logging.getLogger("app.request")

# Accept a caller-supplied request ID only if it looks sane (prevents log injection).
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

# Health probes are polled constantly (the frontend status pill checks every 30s);
# log them at DEBUG so they don't drown out real traffic.
_QUIET_PATH_SUFFIXES = ("/health", "/health/ready")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request ID, log one line per request, and catch unhandled errors.

    Unhandled exceptions are converted to a JSON 500 here (rather than by
    Starlette's outermost error middleware) so the response still passes back
    through CORSMiddleware and the browser can read it.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()

        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception(
                    "unhandled error", extra={"method": request.method, "path": request.url.path}
                )
                response = unhandled_error_response(request)

            response.headers[REQUEST_ID_HEADER] = request_id
            quiet = request.url.path.endswith(_QUIET_PATH_SUFFIXES) and response.status_code < 400
            logger.log(
                logging.DEBUG if quiet else logging.INFO,
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            return response
        finally:
            request_id_ctx.reset(token)
