#!/usr/bin/env python3
"""End-to-end smoke test for a running CodeSage stack.

Start the backend and frontend first (see README.md "Run the app").

Uses only the Python standard library, so it runs without installing anything:

    python tests/smoke/smoke_test.py

Override targets with API_URL (default http://localhost:8000) and FRONTEND_URL
(default http://localhost:3000). Exits non-zero if any check fails.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
STARTUP_TIMEOUT_SECONDS = int(os.getenv("SMOKE_STARTUP_TIMEOUT", "90"))


class Response:
    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.status = status
        self.headers = {key.lower(): value for key, value in headers.items()}
        self.body = body

    def json(self) -> Any:
        return json.loads(self.body)


def request(
    url: str, headers: dict[str, str] | None = None, payload: Any | None = None
) -> Response:
    data = None if payload is None else json.dumps(payload).encode()
    headers = dict(headers or {})
    if data is not None:
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return Response(resp.status, dict(resp.headers), resp.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, dict(error.headers), error.read())


def wait_for(url: str) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while True:
        try:
            if request(url).status < 500:
                return
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise SystemExit(f"Timed out after {STARTUP_TIMEOUT_SECONDS}s waiting for {url}")
        time.sleep(2)


def check_liveness() -> None:
    response = request(f"{API_URL}/api/v1/health")
    assert response.status == 200, response.status
    assert response.json()["status"] == "ok"
    assert response.headers.get("x-request-id"), "missing X-Request-ID header"


def check_readiness() -> None:
    response = request(f"{API_URL}/api/v1/health/ready")
    assert response.status == 200, f"{response.status} {response.body!r}"
    assert response.json()["checks"]["database"] == "ok"


def check_openapi() -> None:
    response = request(f"{API_URL}/api/v1/openapi.json")
    assert response.status == 200, response.status
    paths = response.json()["paths"]
    assert "/api/v1/repositories" in paths
    assert "/api/v1/repositories/{repository_id}/search" in paths


def check_list_endpoints() -> None:
    for resource in ("projects", "repositories"):
        response = request(f"{API_URL}/api/v1/{resource}")
        assert response.status == 200, f"{resource}: {response.status}"
        assert {"items", "total", "limit", "offset"} <= response.json().keys()


def check_error_envelope() -> None:
    response = request(f"{API_URL}/api/v1/repositories/00000000-0000-0000-0000-000000000000")
    assert response.status == 404, response.status
    assert response.json()["error"]["code"] == "not_found"


def check_search_endpoint() -> None:
    """The search route is wired up and validates input (no indexed repository needed)."""
    unknown = f"{API_URL}/api/v1/repositories/00000000-0000-0000-0000-000000000000/search"
    response = request(unknown, payload={"query": "hello world", "retrieval_strategy": "hybrid"})
    assert response.status == 404, f"{response.status} {response.body!r}"
    assert response.json()["error"]["code"] == "not_found"

    invalid = request(unknown, payload={"query": "x", "retrieval_strategy": "magic"})
    assert invalid.status == 422, invalid.status
    assert invalid.json()["error"]["code"] == "validation_error"


def check_cors() -> None:
    response = request(f"{API_URL}/api/v1/health", headers={"Origin": FRONTEND_ORIGIN})
    allowed = response.headers.get("access-control-allow-origin")
    assert allowed == FRONTEND_ORIGIN, f"access-control-allow-origin={allowed!r}"


def check_frontend_pages() -> None:
    for path in ("/dashboard", "/repositories"):
        response = request(f"{FRONTEND_URL}{path}")
        assert response.status == 200, f"{path}: {response.status}"
        assert b"CodeSage" in response.body, f"{path}: app shell not rendered"


CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("backend liveness", check_liveness),
    ("backend readiness (database)", check_readiness),
    ("OpenAPI schema", check_openapi),
    ("list endpoints", check_list_endpoints),
    ("error envelope", check_error_envelope),
    ("search endpoint", check_search_endpoint),
    ("CORS for frontend origin", check_cors),
    ("frontend pages", check_frontend_pages),
]


def main() -> int:
    print(f"Waiting for API at {API_URL} and frontend at {FRONTEND_URL} ...")
    wait_for(f"{API_URL}/api/v1/health")
    wait_for(f"{FRONTEND_URL}/dashboard")

    failures = 0
    for name, check in CHECKS:
        try:
            check()
            print(f"  PASS  {name}")
        except (AssertionError, OSError, ValueError, KeyError) as error:
            failures += 1
            print(f"  FAIL  {name}: {error}")

    print(f"\n{len(CHECKS) - failures}/{len(CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
