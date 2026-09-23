from fastapi.testclient import TestClient

from tests.conftest import FRONTEND_ORIGIN


def test_preflight_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/repositories",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN


def test_preflight_rejects_unknown_origin(client: TestClient) -> None:
    response = client.options(
        "/api/v1/repositories",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_simple_request_exposes_request_id_header(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": FRONTEND_ORIGIN})

    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]
