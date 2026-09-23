import json
import logging

from app.core.logging import ConsoleFormatter, JsonFormatter, request_id_ctx


def _record(message: str = "hello", **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_structured_fields() -> None:
    payload = json.loads(JsonFormatter().format(_record(repository_id="abc", count=3)))

    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.test"
    assert payload["repository_id"] == "abc"
    assert payload["count"] == 3
    assert "timestamp" in payload


def test_formatters_include_request_id_from_context() -> None:
    token = request_id_ctx.set("req-123")
    try:
        json_line = json.loads(JsonFormatter().format(_record()))
        console_line = ConsoleFormatter().format(_record())
    finally:
        request_id_ctx.reset(token)

    assert json_line["request_id"] == "req-123"
    assert "request_id=req-123" in console_line


def test_json_formatter_includes_exception() -> None:
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )

    payload = json.loads(JsonFormatter().format(record))

    assert "ValueError: kaboom" in payload["exception"]
