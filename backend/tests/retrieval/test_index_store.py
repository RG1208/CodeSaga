"""Index directories: manifest, staleness checks, installation and caching."""

import json
import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from app.retrieval.embeddings import HashingEmbeddingProvider
from app.retrieval.errors import IndexUnavailableError
from app.retrieval.index_store import MANIFEST_FILENAME, RepositoryIndexStore
from tests.retrieval.helpers import build_fixture_index


@pytest.fixture
def fixture_index(tmp_path: Path):  # type: ignore[no-untyped-def]
    return build_fixture_index(tmp_path)


def test_index_files_are_written(fixture_index) -> None:  # type: ignore[no-untyped-def]
    directory = fixture_index.store.path_for(fixture_index.repository_id)

    assert sorted(item.name for item in directory.iterdir()) == [
        "bm25.npz",
        "bm25_vocabulary.json",
        "chunk_ids.json",
        "dense.faiss",
        "dense_ids.json",
        "manifest.json",
    ]


def test_manifest_records_how_the_index_was_built(fixture_index) -> None:  # type: ignore[no-untyped-def]
    manifest = fixture_index.store.read_manifest(fixture_index.repository_id)

    assert manifest["commit_sha"] == "fixture-commit"
    assert manifest["chunk_count"] == len(fixture_index.chunks)
    assert manifest["bm25"]["k1"] == 1.2 and manifest["bm25"]["terms"] > 100
    assert manifest["dense"] == {
        "status": "ready",
        "provider": "hashing",
        "model": "hashing-v1",
        "dimension": 256,
        "vectors": len(fixture_index.chunks),
        "skipped": 0,
        "store": "faiss",
    }
    assert manifest["built_at"]


def test_loaded_index_is_searchable(fixture_index) -> None:  # type: ignore[no-untyped-def]
    index = fixture_index.index

    assert len(index.chunk_ids) == len(fixture_index.chunks)
    assert index.bm25.document_count == len(fixture_index.chunks)
    assert index.has_dense


def test_missing_index(tmp_path: Path) -> None:
    store = RepositoryIndexStore(tmp_path / "indexes")

    with pytest.raises(IndexUnavailableError) as caught:
        store.load(
            uuid.uuid4(),
            commit_sha="abc",
            embeddings=HashingEmbeddingProvider(),
            settings=Settings(_env_file=None),
        )
    assert caught.value.code == "index_not_built"


def test_index_from_another_commit_is_refused(fixture_index) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(IndexUnavailableError) as caught:
        fixture_index.store.load(
            fixture_index.repository_id,
            commit_sha="a-newer-commit",
            embeddings=fixture_index.embeddings,
            settings=fixture_index.settings,
        )
    assert caught.value.code == "index_out_of_date"


def test_dense_index_built_with_another_model_is_ignored(fixture_index) -> None:  # type: ignore[no-untyped-def]
    other_model = HashingEmbeddingProvider(model_id="some-other-model")

    index = fixture_index.store.load(
        fixture_index.repository_id,
        commit_sha="fixture-commit",
        embeddings=other_model,
        settings=fixture_index.settings,
    )

    # BM25 still works; dense is dropped rather than compared across models.
    assert index.bm25.document_count > 0
    assert not index.has_dense


def test_unreadable_index(fixture_index) -> None:  # type: ignore[no-untyped-def]
    directory = fixture_index.store.path_for(fixture_index.repository_id)
    (directory / "chunk_ids.json").write_text("not json", encoding="utf-8")
    # A fresh store, so the already-loaded index is not served from the cache.
    store = RepositoryIndexStore(fixture_index.store.root)

    with pytest.raises(IndexUnavailableError) as caught:
        store.load(
            fixture_index.repository_id,
            commit_sha="fixture-commit",
            embeddings=fixture_index.embeddings,
            settings=fixture_index.settings,
        )
    assert caught.value.code == "index_unreadable"


def test_repeated_loads_are_cached(fixture_index) -> None:  # type: ignore[no-untyped-def]
    def load():  # type: ignore[no-untyped-def]
        return fixture_index.store.load(
            fixture_index.repository_id,
            commit_sha="fixture-commit",
            embeddings=fixture_index.embeddings,
            settings=fixture_index.settings,
        )

    assert load() is load()


def test_installing_a_new_index_invalidates_the_cache(fixture_index, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    before = fixture_index.index
    replacement = fixture_index.store.create_temp_dir(fixture_index.repository_id)
    for name in ("chunk_ids.json", "bm25.npz", "bm25_vocabulary.json"):
        (replacement / name).write_bytes(
            (fixture_index.store.path_for(fixture_index.repository_id) / name).read_bytes()
        )
    manifest = fixture_index.store.read_manifest(fixture_index.repository_id) or {}
    manifest["built_at"] = "2030-01-01T00:00:00+00:00"
    manifest["dense"] = {"status": "disabled"}
    (replacement / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")

    fixture_index.store.install(fixture_index.repository_id, replacement)
    after = fixture_index.store.load(
        fixture_index.repository_id,
        commit_sha="fixture-commit",
        embeddings=fixture_index.embeddings,
        settings=fixture_index.settings,
    )

    assert after is not before
    assert not after.has_dense


def test_remove_and_temp_cleanup(fixture_index) -> None:  # type: ignore[no-untyped-def]
    leftover = fixture_index.store.create_temp_dir(fixture_index.repository_id)

    assert fixture_index.store.remove(fixture_index.repository_id) is True
    assert not fixture_index.store.path_for(fixture_index.repository_id).exists()
    assert fixture_index.store.remove(fixture_index.repository_id) is False
    assert leftover.exists()
    fixture_index.store.clear_temp()
    assert not leftover.exists()


def test_index_directories_stay_inside_the_root(tmp_path: Path) -> None:
    from app.ingestion.errors import UnsafePathError

    store = RepositoryIndexStore(tmp_path / "indexes")

    with pytest.raises(UnsafePathError):
        store.install(uuid.uuid4(), tmp_path / "elsewhere")
