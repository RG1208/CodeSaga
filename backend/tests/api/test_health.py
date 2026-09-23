from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import __version__
from app.db.session import get_db


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "codesage-backend"
    assert body["version"] == __version__
    assert body["environment"] == "test"
    assert "timestamp" in body


def test_health_sets_request_id_header(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert len(response.headers["X-Request-ID"]) == 32


def test_health_echoes_valid_caller_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-abc-123"})

    assert response.headers["X-Request-ID"] == "trace-abc-123"


def test_health_replaces_unsafe_caller_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\twith spaces"})

    assert response.headers["X-Request-ID"] != "bad id\twith spaces"


def test_readiness_ok_when_database_reachable(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_readiness_503_when_database_unreachable(app: FastAPI, client: TestClient) -> None:
    broken_engine = create_engine("sqlite:////nonexistent-dir/codesage.db")

    def _broken_db() -> Iterator[Session]:
        with Session(broken_engine) as session:
            yield session

    app.dependency_overrides[get_db] = _broken_db
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "error"}}


def test_openapi_schema_is_versioned(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert "/api/v1/health" in response.json()["paths"]
