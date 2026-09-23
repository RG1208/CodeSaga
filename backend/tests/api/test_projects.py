import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import User


def _create_project(client: TestClient, **overrides: object) -> dict:
    payload = {"name": "CodeSage", "description": "Main workspace", **overrides}
    response = client.post("/api/v1/projects", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_project(client: TestClient) -> None:
    project = _create_project(client, name="  Trimmed Name  ")

    assert project["name"] == "Trimmed Name"
    assert project["description"] == "Main workspace"
    assert project["owner_id"] is None
    uuid.UUID(project["id"])
    assert project["created_at"] and project["updated_at"]


def test_create_project_with_owner(client: TestClient, db_session: Session) -> None:
    user = User(email="owner@example.com", full_name="Owner")
    db_session.add(user)
    db_session.commit()

    project = _create_project(client, owner_id=str(user.id))

    assert project["owner_id"] == str(user.id)


def test_create_project_with_unknown_owner_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={"name": "X", "owner_id": str(uuid.uuid4())})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_create_duplicate_project_returns_409(client: TestClient) -> None:
    _create_project(client)

    response = client.post("/api/v1/projects", json={"name": "CodeSage"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_create_project_requires_name(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={"name": "   "})

    assert response.status_code == 422


def test_list_projects_paginates(client: TestClient) -> None:
    for index in range(3):
        _create_project(client, name=f"Project {index}")

    response = client.get("/api/v1/projects", params={"limit": 2, "offset": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 2
    assert body["offset"] == 0
    assert len(body["items"]) == 2


def test_get_project(client: TestClient) -> None:
    created = _create_project(client)

    response = client.get(f"/api/v1/projects/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_project_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/projects/{uuid.uuid4()}")

    assert response.status_code == 404


def test_get_project_with_malformed_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/v1/projects/not-a-uuid")

    assert response.status_code == 422
