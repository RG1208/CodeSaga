"""HTTP behaviour of POST /api/v1/repositories/{id}/search.

The deterministic fixture repository is served through the fake git client, indexed
through the real pipeline (inline jobs), then searched over HTTP. Embeddings are the
offline hashing provider and the reranker is `KeywordReranker`, so nothing is downloaded.
"""

import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Repository, RepositoryStatus
from app.models.retrieval import CodeChunk, RetrievalLog
from app.retrieval.rerankers import RerankerRegistry
from tests.fakes import FakeGitClient
from tests.retrieval.helpers import fixture_root

STRATEGIES = ["bm25", "dense", "hybrid", "hybrid_rerank"]


def _fixture_files() -> dict[str, bytes]:
    root = fixture_root()
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def repo_id(client: TestClient, fake_git: FakeGitClient) -> str:
    fake_git.files = _fixture_files()
    created = client.post(
        "/api/v1/repositories", json={"url": "https://github.com/demo/support-desk"}
    ).json()
    job = client.post(f"/api/v1/repositories/{created['id']}/index").json()
    assert job["status"] == "succeeded", job
    return created["id"]


def search(client: TestClient, repo_id: str, **payload: object):  # type: ignore[no-untyped-def]
    return client.post(f"/api/v1/repositories/{repo_id}/search", json=payload)


def search_ok(client: TestClient, repo_id: str, **payload: object) -> dict:
    response = search(client, repo_id, **payload)
    assert response.status_code == 200, response.text
    return response.json()


def files_in(body: dict) -> list[str]:
    return [item["chunk"]["file_path"] for item in body["results"]]


# --- indexing produced a searchable index ------------------------------------------


def test_indexing_stores_chunks_and_reports_them(
    client: TestClient, repo_id: str, db_session: Session
) -> None:
    body = client.get(f"/api/v1/repositories/{repo_id}").json()
    retrieval = body["metadata"]["retrieval"]
    stored = db_session.scalars(
        select(CodeChunk).where(CodeChunk.repository_id == uuid.UUID(repo_id))
    ).all()

    assert body["status"] == "completed"
    assert retrieval["chunks"] == len(stored) > 30
    assert retrieval["bm25"]["terms"] > 100
    assert retrieval["dense"]["status"] == "ready"
    assert retrieval["dense"]["provider"] == "hashing"
    assert {chunk.chunk_type for chunk in stored} >= {"symbol", "module"}


# --- the four strategies -----------------------------------------------------------


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_every_strategy_answers_over_http(client: TestClient, repo_id: str, strategy: str) -> None:
    body = search_ok(
        client, repo_id, query="how are passwords hashed", top_k=5, retrieval_strategy=strategy
    )

    assert body["retrieval_strategy"] == strategy
    assert body["result_count"] == len(body["results"]) == 5
    assert [item["rank"] for item in body["results"]] == [1, 2, 3, 4, 5]
    assert "app/auth/passwords.py" in files_in(body)
    assert body["latency_ms"] > 0
    assert body["timings"]
    assert body["index"]["chunk_count"] > 0
    assert body["index"]["dense_available"] is True


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_result_metadata_is_complete(client: TestClient, repo_id: str, strategy: str) -> None:
    body = search_ok(
        client, repo_id, query="refund a customer payment", top_k=3, retrieval_strategy=strategy
    )

    for item in body["results"]:
        chunk = item["chunk"]
        assert uuid.UUID(chunk["chunk_id"])
        assert chunk["repository_id"] == repo_id
        assert chunk["file_path"] and chunk["language"] and chunk["chunk_type"]
        assert 1 <= chunk["start_line"] <= chunk["end_line"]
        assert chunk["token_count"] > 0
        assert chunk["content"]
        assert set(chunk) == {
            "chunk_id",
            "repository_id",
            "file_path",
            "language",
            "chunk_type",
            "symbol_name",
            "symbol_type",
            "qualified_name",
            "parent_symbol",
            "start_line",
            "end_line",
            "token_count",
            "content",
        }
        assert item["score"] == pytest.approx(item["score"])
        assert item["scores"]


def test_line_numbers_point_at_the_real_source(client: TestClient, repo_id: str) -> None:
    body = search_ok(
        client,
        repo_id,
        query="verify a json web token signature",
        top_k=1,
        retrieval_strategy="bm25",
    )
    chunk = body["results"][0]["chunk"]
    source = (fixture_root() / chunk["file_path"]).read_text(encoding="utf-8").splitlines()

    assert chunk["file_path"] == "app/auth/tokens.py"
    assert chunk["symbol_name"] == "decode_token"
    assert chunk["content"].splitlines() == source[chunk["start_line"] - 1 : chunk["end_line"]]

    # The same file is served by the file-content endpoint, so a UI can open it there.
    served = client.get(
        f"/api/v1/repositories/{repo_id}/files/content", params={"path": chunk["file_path"]}
    ).json()
    assert served["content"].splitlines()[chunk["start_line"] - 1].startswith("def decode_token")


def test_scores_name_the_retrievers_that_produced_them(client: TestClient, repo_id: str) -> None:
    bm25 = search_ok(client, repo_id, query="pbkdf2 hash", top_k=3, retrieval_strategy="bm25")
    dense = search_ok(client, repo_id, query="pbkdf2 hash", top_k=3, retrieval_strategy="dense")
    hybrid = search_ok(client, repo_id, query="pbkdf2 hash", top_k=3, retrieval_strategy="hybrid")
    reranked = search_ok(
        client, repo_id, query="pbkdf2 hash", top_k=3, retrieval_strategy="hybrid_rerank"
    )

    assert set(bm25["results"][0]["scores"]) == {"bm25", "bm25_rank"}
    assert set(dense["results"][0]["scores"]) == {"dense", "dense_rank"}
    assert {"bm25", "dense"} & set().union(*(item["scores"] for item in hybrid["results"]))
    assert "rerank" in reranked["results"][0]["scores"]
    assert reranked["reranker"] == "keyword"
    assert bm25["reranker"] is None


def test_documentation_and_typescript_are_searchable(client: TestClient, repo_id: str) -> None:
    docs = search_ok(client, repo_id, query="support desk architecture", top_k=5)
    frontend = search_ok(client, repo_id, query="login form component", top_k=5)

    assert any(path.endswith(".md") for path in files_in(docs))
    assert "web/src/components/LoginForm.tsx" in files_in(frontend)
    languages = {item["chunk"]["language"] for item in frontend["results"]}
    assert languages & {"tsx", "typescript"}


# --- request options ---------------------------------------------------------------


def test_top_k_and_defaults(client: TestClient, repo_id: str) -> None:
    default = search_ok(client, repo_id, query="password")
    small = search_ok(client, repo_id, query="password", top_k=2)

    assert default["top_k"] == 10 and default["retrieval_strategy"] == "hybrid"
    assert len(small["results"]) == 2


def test_content_can_be_omitted(client: TestClient, repo_id: str) -> None:
    body = search_ok(client, repo_id, query="password", top_k=2, include_content=False)

    assert all(item["chunk"]["content"] is None for item in body["results"])
    assert all(item["chunk"]["file_path"] for item in body["results"])


def test_options_are_echoed_and_applied(client: TestClient, repo_id: str) -> None:
    body = search_ok(
        client,
        repo_id,
        query="password",
        top_k=3,
        retrieval_strategy="hybrid",
        options={"fusion_method": "weighted", "bm25_weight": 1.0, "dense_weight": 0.0},
    )
    bm25 = search_ok(client, repo_id, query="password", top_k=3, retrieval_strategy="bm25")

    assert body["options"]["fusion_method"] == "weighted"
    assert body["options"]["bm25_weight"] == 1.0
    # Fusion with all the weight on BM25 reproduces the lexical ranking.
    assert files_in(body) == files_in(bm25)


def test_rerank_candidate_depth_is_configurable(client: TestClient, repo_id: str) -> None:
    body = search_ok(
        client,
        repo_id,
        query="password",
        top_k=3,
        retrieval_strategy="hybrid_rerank",
        options={"rerank_candidates": 5},
    )

    assert body["options"]["rerank_candidates"] == 5
    assert len(body["results"]) == 3


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"query": "x"}, "query too short"),
        ({"query": "  "}, "blank query"),
        ({"query": "password", "top_k": 0}, "top_k below 1"),
        ({"query": "password", "top_k": 500}, "top_k above the cap"),
        ({"query": "password", "retrieval_strategy": "magic"}, "unknown strategy"),
        ({"query": "password", "options": {"bm25_weight": -1}}, "negative weight"),
        ({"query": "password", "options": {"nonsense": 1}}, "unknown option"),
        ({}, "missing query"),
    ],
)
def test_invalid_requests_are_rejected(
    client: TestClient, repo_id: str, payload: dict, detail: str
) -> None:
    response = search(client, repo_id, **payload)

    assert response.status_code == 422, detail
    assert response.json()["error"]["code"] == "validation_error"


# --- research logging --------------------------------------------------------------


def test_searches_are_logged_for_research(
    client: TestClient, repo_id: str, db_session: Session
) -> None:
    body = search_ok(
        client, repo_id, query="hash a user password", top_k=3, retrieval_strategy="hybrid"
    )
    log = db_session.get(RetrievalLog, uuid.UUID(body["log_id"]))

    assert log is not None
    assert log.repository_id == uuid.UUID(repo_id)
    assert log.query == "hash a user password"
    assert log.strategy == "hybrid"
    assert log.top_k == 3
    assert log.result_count == 3
    assert log.latency_ms > 0
    assert log.result_chunk_ids == [item["chunk"]["chunk_id"] for item in body["results"]]
    assert [entry["file_path"] for entry in log.results] == files_in(body)
    assert [entry["rank"] for entry in log.results] == [1, 2, 3]
    assert log.results[0]["scores"] == body["results"][0]["scores"]
    assert log.options["fusion_method"] and log.index_info["chunk_count"] > 0
    assert log.timings


def test_logging_can_be_switched_off_per_request(
    client: TestClient, repo_id: str, db_session: Session
) -> None:
    body = search_ok(client, repo_id, query="password", log=False)

    assert body["log_id"] is None
    assert db_session.scalars(select(RetrievalLog)).all() == []


def test_logging_can_be_switched_off_by_configuration(
    client: TestClient, repo_id: str, db_session: Session, app
) -> None:  # type: ignore[no-untyped-def]
    app.state.settings.retrieval_logging_enabled = False
    try:
        off = search_ok(client, repo_id, query="password")
        on = search_ok(client, repo_id, query="password", log=True)
    finally:
        app.state.settings.retrieval_logging_enabled = True

    assert off["log_id"] is None
    assert on["log_id"] is not None
    assert len(db_session.scalars(select(RetrievalLog)).all()) == 1


def test_logged_searches_survive_repository_deletion(
    client: TestClient, repo_id: str, db_session: Session
) -> None:
    """Research data outlives the repository it was collected from."""
    body = search_ok(client, repo_id, query="password")

    assert client.delete(f"/api/v1/repositories/{repo_id}").status_code == 204

    log = db_session.get(RetrievalLog, uuid.UUID(body["log_id"]))
    assert log is not None
    db_session.refresh(log)
    assert log.repository_id is None  # detached, not deleted
    assert log.repository_name and log.query == "password"


# --- failure paths -----------------------------------------------------------------


def test_unknown_repository(client: TestClient) -> None:
    response = search(client, str(uuid.uuid4()), query="password")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_repository_that_has_never_been_indexed(client: TestClient) -> None:
    created = client.post(
        "/api/v1/repositories", json={"url": "https://github.com/demo/not-indexed"}
    ).json()

    response = search(client, created["id"], query="password")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "repository_not_indexed"


def test_index_left_behind_by_an_older_commit(
    client: TestClient, repo_id: str, db_session: Session
) -> None:
    repository = db_session.get(Repository, uuid.UUID(repo_id))
    assert repository is not None
    repository.commit_sha = "c" * 40
    db_session.commit()

    response = search(client, repo_id, query="password")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "index_out_of_date"


def test_missing_index_directory(client: TestClient, repo_id: str, settings) -> None:  # type: ignore[no-untyped-def]
    import shutil

    shutil.rmtree(Path(settings.index_storage_dir) / repo_id)

    response = search(client, repo_id, query="password")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "index_not_built"


def test_unknown_reranker(client: TestClient, repo_id: str) -> None:
    response = search(client, repo_id, query="password", reranker="does-not-exist")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_reranker"
    assert "keyword" in response.json()["error"]["message"]


def test_reranking_without_a_configured_reranker(
    client: TestClient, repo_id: str, app, job_context
) -> None:  # type: ignore[no-untyped-def]
    """No reranker installed (no model available) is a 503, not a silent fallback."""
    app.state.job_context = replace(job_context, rerankers=RerankerRegistry())

    response = search(client, repo_id, query="password", retrieval_strategy="hybrid_rerank")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "reranker_unavailable"


def test_deleting_a_repository_removes_its_index(
    client: TestClient, repo_id: str, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    index_dir = Path(settings.index_storage_dir) / repo_id
    assert index_dir.is_dir()

    assert client.delete(f"/api/v1/repositories/{repo_id}").status_code == 204

    assert not index_dir.exists()
    assert (
        db_session.scalars(
            select(CodeChunk).where(CodeChunk.repository_id == uuid.UUID(repo_id))
        ).all()
        == []
    )


def test_search_after_reindexing_uses_the_new_index(client: TestClient, repo_id: str) -> None:
    before = search_ok(client, repo_id, query="hash a user password", top_k=3)

    job = client.post(f"/api/v1/repositories/{repo_id}/index").json()
    assert job["status"] == "succeeded"

    after = search_ok(client, repo_id, query="hash a user password", top_k=3)
    assert files_in(after) == files_in(before)
    assert client.get(f"/api/v1/repositories/{repo_id}").json()["status"] == (
        RepositoryStatus.COMPLETED.value
    )
