"""HTTP behaviour of /api/v1/repositories (GitHub is faked; nothing touches the network)."""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.ingestion.errors import GitCommandError, GitErrorKind
from app.models import IndexingJob, JobStatus, Repository, RepositoryStatus
from tests.fakes import DEVELOP_SHA, MAIN_SHA, FakeGitClient

GITHUB_URL = "https://github.com/pallets/markupsafe"


def _add(client: TestClient, **overrides: object):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/repositories", json={"url": GITHUB_URL, **overrides})


def _add_ok(client: TestClient, **overrides: object) -> dict:
    response = _add(client, **overrides)
    assert response.status_code == 201, response.text
    return response.json()


# --- POST /repositories ------------------------------------------------------


def test_add_github_repository_extracts_metadata(
    client: TestClient, fake_git: FakeGitClient
) -> None:
    body = _add_ok(client, url="https://github.com/Pallets/MarkupSafe.git")

    assert body["name"] == "MarkupSafe"
    assert body["owner"] == "Pallets"
    assert body["url"] == "https://github.com/pallets/markupsafe"
    assert body["source_type"] == "github"
    assert body["default_branch"] == "main"
    assert body["branch"] == "main"
    assert body["status"] == "pending"
    assert body["commit_sha"] is None
    assert body["local_path"] is None
    assert body["metadata"] is None
    assert ("resolve_remote", "https://github.com/Pallets/MarkupSafe.git", "") in fake_git.calls


def test_add_repository_with_selected_branch(client: TestClient) -> None:
    body = _add_ok(client, branch="develop")

    assert (body["default_branch"], body["branch"]) == ("main", "develop")


def test_add_repository_uses_default_project_when_none_given(client: TestClient) -> None:
    first = _add_ok(client)
    second = _add_ok(client, url="https://github.com/pallets/click")

    assert first["project_id"] == second["project_id"]
    project = client.get(f"/api/v1/projects/{first['project_id']}").json()
    assert project["name"] == "Default"


def test_add_repository_to_explicit_project(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "Mine"}).json()["id"]

    assert _add_ok(client, project_id=project_id)["project_id"] == project_id


def test_add_repository_to_missing_project_returns_404(client: TestClient) -> None:
    response = _add(client, project_id=str(uuid.uuid4()))

    assert response.status_code == 404


def test_custom_display_name(client: TestClient) -> None:
    assert _add_ok(client, name="Safe markup")["name"] == "Safe markup"


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "http://github.com/pallets/markupsafe",
        "git@github.com:pallets/markupsafe.git",
        "https://gitlab.com/pallets/markupsafe",
        "https://github.com/pallets",
        "https://github.com/pallets/markupsafe/tree/main",
        "https://user:pass@github.com/pallets/markupsafe",
        "ext::sh -c touch% /tmp/pwned",
    ],
)
def test_invalid_github_urls_are_rejected_without_calling_git(
    client: TestClient, fake_git: FakeGitClient, url: str
) -> None:
    response = _add(client, url=url)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_repository_source"
    assert fake_git.calls == []


@pytest.mark.parametrize("branch", ["--upload-pack=evil", "a..b", "has space", "$(id)"])
def test_invalid_branch_names_are_rejected(
    client: TestClient, fake_git: FakeGitClient, branch: str
) -> None:
    response = _add(client, branch=branch)

    assert response.status_code == 422
    assert fake_git.calls == []


def test_unknown_branch_returns_422(client: TestClient) -> None:
    response = _add(client, branch="does-not-exist")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "branch_not_found"


def test_private_or_missing_repository_returns_422(
    client: TestClient, fake_git: FakeGitClient
) -> None:
    fake_git.resolve_error = GitCommandError("Repository not found.", GitErrorKind.NOT_FOUND)

    response = _add(client)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "repository_not_found"


def test_github_unreachable_returns_502(client: TestClient, fake_git: FakeGitClient) -> None:
    fake_git.resolve_error = GitCommandError("Could not reach GitHub.", GitErrorKind.NETWORK)

    response = _add(client)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "network_error"


def test_duplicate_repository_returns_409(client: TestClient) -> None:
    _add_ok(client)

    response = _add(client, url="https://github.com/PALLETS/markupsafe.git")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "repository_exists"


def test_missing_url_returns_422(client: TestClient) -> None:
    response = client.post("/api/v1/repositories", json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# --- local repositories -------------------------------------------------------


@pytest.fixture
def local_repo(local_repos_root: Path) -> Path:
    path = local_repos_root / "my-service"
    (path / ".git").mkdir(parents=True)
    return path


def test_add_local_repository_in_development(client: TestClient, local_repo: Path) -> None:
    body = _add_ok(client, source_type="local", url=str(local_repo))

    assert body["source_type"] == "local"
    assert body["name"] == "my-service"
    assert body["owner"] is None
    assert body["url"] == str(local_repo.resolve())


def test_local_repository_outside_allowed_roots_is_rejected(
    client: TestClient, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    (outside / ".git").mkdir(parents=True)

    response = _add(client, source_type="local", url=str(outside))

    assert response.status_code == 422
    assert "allowed directory" in response.json()["error"]["message"]


def test_local_path_traversal_is_rejected(client: TestClient, local_repos_root: Path) -> None:
    response = _add(client, source_type="local", url=f"{local_repos_root}/../../etc")

    assert response.status_code == 422


def test_local_repositories_are_forbidden_outside_development(
    client: TestClient, settings: Settings, local_repo: Path
) -> None:
    settings.app_env = "production"

    response = _add(client, source_type="local", url=str(local_repo))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "local_repositories_disabled"


# --- GET /repositories ------------------------------------------------------------


def test_list_repositories_with_filters(client: TestClient) -> None:
    project_id = client.post("/api/v1/projects", json={"name": "Other"}).json()["id"]
    indexed = _add_ok(client)
    _add_ok(client, url="https://github.com/pallets/click", project_id=project_id)
    client.post(f"/api/v1/repositories/{indexed['id']}/index")

    everything = client.get("/api/v1/repositories").json()
    by_project = client.get("/api/v1/repositories", params={"project_id": project_id}).json()
    completed = client.get("/api/v1/repositories", params={"status": "completed"}).json()

    assert everything["total"] == 2
    assert [item["name"] for item in by_project["items"]] == ["click"]
    assert [item["id"] for item in completed["items"]] == [indexed["id"]]


def test_list_rejects_unknown_status(client: TestClient) -> None:
    assert client.get("/api/v1/repositories", params={"status": "bogus"}).status_code == 422


# --- GET /repositories/{id} -----------------------------------------------------


def test_get_repository_detail(client: TestClient) -> None:
    created = _add_ok(client)

    body = client.get(f"/api/v1/repositories/{created['id']}").json()

    assert body["id"] == created["id"]
    assert body["latest_job"] is None


def test_get_missing_repository_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/repositories/{uuid.uuid4()}")

    assert response.status_code == 404


# --- POST /repositories/{id}/index --------------------------------------------------


def test_start_indexing_runs_pipeline(client: TestClient, settings: Settings) -> None:
    created = _add_ok(client, branch="develop")

    response = client.post(f"/api/v1/repositories/{created['id']}/index")

    assert response.status_code == 202
    job = response.json()
    assert job["repository_id"] == created["id"]
    assert job["branch"] == "develop"
    # The test queue runs jobs inline, so the job has already finished.
    assert job["status"] == "succeeded"

    detail = client.get(f"/api/v1/repositories/{created['id']}").json()
    assert detail["status"] == "completed"
    assert detail["commit_sha"] == DEVELOP_SHA
    assert detail["local_path"] == str(settings.repository_storage_dir / created["id"])
    assert detail["last_indexed_at"] is not None
    assert detail["metadata"]["primary_language"] == "Python"
    assert detail["metadata"]["indexed_files"] == 6
    assert detail["latest_job"]["id"] == job["id"]
    assert detail["latest_job"]["files_processed"] == detail["latest_job"]["files_total"]


def test_reindexing_creates_a_new_job(client: TestClient) -> None:
    created = _add_ok(client)
    first = client.post(f"/api/v1/repositories/{created['id']}/index").json()

    second = client.post(f"/api/v1/repositories/{created['id']}/index").json()

    assert second["id"] != first["id"]
    detail = client.get(f"/api/v1/repositories/{created['id']}").json()
    assert detail["latest_job"]["id"] == second["id"]
    assert detail["commit_sha"] == MAIN_SHA


def test_failed_indexing_is_reported(client: TestClient, fake_git: FakeGitClient) -> None:
    created = _add_ok(client)
    fake_git.clone_error = GitCommandError("Could not reach GitHub.", GitErrorKind.NETWORK)

    job = client.post(f"/api/v1/repositories/{created['id']}/index").json()

    assert job["status"] == "failed"
    assert job["error_message"] == "Could not reach GitHub."
    detail = client.get(f"/api/v1/repositories/{created['id']}").json()
    assert detail["status"] == "failed"
    assert detail["status_message"] == "Could not reach GitHub."


def test_start_indexing_while_active_returns_409(client: TestClient, db_session: Session) -> None:
    created = _add_ok(client)
    repository_id = uuid.UUID(created["id"])
    db_session.add(
        IndexingJob(repository_id=repository_id, branch="main", status=JobStatus.RUNNING)
    )
    db_session.get_one(Repository, repository_id).status = RepositoryStatus.CLONING
    db_session.commit()

    response = client.post(f"/api/v1/repositories/{created['id']}/index")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "indexing_in_progress"


def test_start_indexing_missing_repository_returns_404(client: TestClient) -> None:
    assert client.post(f"/api/v1/repositories/{uuid.uuid4()}/index").status_code == 404


# --- DELETE /repositories/{id} ------------------------------------------------------


def test_delete_repository_removes_record_and_checkout(
    client: TestClient, settings: Settings
) -> None:
    created = _add_ok(client)
    client.post(f"/api/v1/repositories/{created['id']}/index")
    checkout = settings.repository_storage_dir / created["id"]
    assert checkout.exists()

    response = client.delete(f"/api/v1/repositories/{created['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert not checkout.exists()
    assert client.get(f"/api/v1/repositories/{created['id']}").status_code == 404


def test_delete_never_indexed_repository(client: TestClient) -> None:
    created = _add_ok(client)

    assert client.delete(f"/api/v1/repositories/{created['id']}").status_code == 204


def test_delete_while_indexing_returns_409(client: TestClient, db_session: Session) -> None:
    created = _add_ok(client)
    db_session.add(
        IndexingJob(repository_id=uuid.UUID(created["id"]), branch="main", status=JobStatus.QUEUED)
    )
    db_session.commit()

    response = client.delete(f"/api/v1/repositories/{created['id']}")

    assert response.status_code == 409
    assert client.get(f"/api/v1/repositories/{created['id']}").status_code == 200


def test_delete_missing_repository_returns_404(client: TestClient) -> None:
    assert client.delete(f"/api/v1/repositories/{uuid.uuid4()}").status_code == 404
