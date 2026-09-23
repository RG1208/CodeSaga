from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import ConflictError
from tests.conftest import FRONTEND_ORIGIN


def _assert_error_envelope(body: dict, code: str) -> None:
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert body["error"]["request_id"]


def test_unknown_route_returns_404_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    _assert_error_envelope(response.json(), "not_found")


def test_wrong_method_returns_405_envelope(client: TestClient) -> None:
    response = client.delete("/api/v1/health")

    assert response.status_code == 405
    _assert_error_envelope(response.json(), "method_not_allowed")


def test_invalid_query_param_returns_422_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/projects", params={"limit": 0})

    assert response.status_code == 422
    body = response.json()
    _assert_error_envelope(body, "validation_error")
    assert body["error"]["details"][0]["loc"] == ["query", "limit"]


def test_app_error_uses_its_status_and_code(app: FastAPI, client: TestClient) -> None:
    @app.get("/test/conflict")
    def _conflict() -> None:
        raise ConflictError("Already there.", details={"field": "name"})

    response = client.get("/test/conflict")

    assert response.status_code == 409
    body = response.json()
    _assert_error_envelope(body, "conflict")
    assert body["error"]["message"] == "Already there."
    assert body["error"]["details"] == {"field": "name"}


def test_unhandled_exception_returns_generic_500_with_cors(
    app: FastAPI, client: TestClient
) -> None:
    @app.get("/test/boom")
    def _boom() -> None:
        raise RuntimeError("secret internal detail")

    response = client.get("/test/boom", headers={"Origin": FRONTEND_ORIGIN})

    assert response.status_code == 500
    body = response.json()
    _assert_error_envelope(body, "internal_error")
    assert "secret" not in response.text
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert response.headers["X-Request-ID"] == body["error"]["request_id"]
