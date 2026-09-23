"""Structured logging.

Every log line is emitted as a single JSON object (or a readable console line
in development) that includes the current request ID, so logs from one HTTP
request can be correlated. Extra context is passed with `extra=`:

    logger.info("repository created", extra={"repository_id": str(repo.id)})
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

_HANDLER_NAME = "codesage"

# Attributes present on every LogRecord; anything else was supplied via `extra=`.
_STANDARD_RECORD_ATTRS = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None)).keys()
) | {"message", "asctime", "color_message"}  # color_message: uvicorn's ANSI duplicate


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {
        key: value
        for key, value in vars(record).items()
        if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """Render log records as one-line JSON documents."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if request_id := request_id_ctx.get():
            payload["request_id"] = request_id
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-friendly single-line format for local development."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        parts = [f"{timestamp} {record.levelname:<8} {record.name}: {record.getMessage()}"]
        if request_id := request_id_ctx.get():
            parts.append(f"request_id={request_id}")
        parts.extend(f"{key}={value}" for key, value in _extra_fields(record).items())
        line = " ".join(parts)
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(level: str = "INFO", log_format: str = "json") -> None:
    """Route all application and server logs through a single stdout handler.

    Safe to call more than once: our previous handler is replaced, not duplicated.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(JsonFormatter() if log_format == "json" else ConsoleFormatter())

    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == _HANDLER_NAME]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # Let uvicorn's own loggers flow through our handler instead of theirs.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # Request logging is done by RequestContextMiddleware, so silence the
    # duplicate (and unstructured) uvicorn access log.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False

    # SQL echo is controlled by DATABASE_ECHO, not by the root log level.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
