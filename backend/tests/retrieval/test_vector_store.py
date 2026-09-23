"""FAISS vector store behind the `VectorStore` interface."""

from pathlib import Path

import numpy as np
import pytest

from app.core.config import Settings
from app.retrieval.vector_store import FaissVectorStore, create_vector_store, load_vector_store


def unit(values: list[float]) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


@pytest.fixture
def store() -> FaissVectorStore:
    store = FaissVectorStore(3)
    store.add(
        ["a", "b", "c"],
        np.vstack([unit([1, 0, 0]), unit([0.9, 0.1, 0]), unit([0, 0, 1])]),
    )
    return store


def test_search_orders_by_cosine_similarity(store: FaissVectorStore) -> None:
    hits = store.search(unit([1, 0, 0]), 3)

    assert [chunk_id for chunk_id, _ in hits] == ["a", "b", "c"]
    assert hits[0][1] == pytest.approx(1.0, abs=1e-5)
    assert hits[2][1] == pytest.approx(0.0, abs=1e-5)


def test_top_k_and_size(store: FaissVectorStore) -> None:
    assert len(store.search(unit([1, 0, 0]), 2)) == 2
    assert len(store.search(unit([1, 0, 0]), 99)) == 3  # never more than what is stored
    assert store.size == 3


def test_empty_store() -> None:
    assert FaissVectorStore(3).search(unit([1, 0, 0]), 5) == []


def test_mismatched_inputs_are_rejected() -> None:
    store = FaissVectorStore(3)

    with pytest.raises(ValueError, match="same length"):
        store.add(["a"], np.zeros((2, 3), dtype=np.float32))
    with pytest.raises(ValueError, match="3-dimensional"):
        store.add(["a"], np.zeros((1, 5), dtype=np.float32))


def test_save_and_load_round_trip(store: FaissVectorStore, tmp_path: Path) -> None:
    store.save(tmp_path)
    loaded = load_vector_store(Settings(_env_file=None), tmp_path)

    assert loaded is not None
    assert loaded.size == 3
    assert loaded.dimension == 3
    assert loaded.search(unit([1, 0, 0]), 3) == store.search(unit([1, 0, 0]), 3)


def test_load_without_an_index_returns_none(tmp_path: Path) -> None:
    assert load_vector_store(Settings(_env_file=None), tmp_path) is None


def test_factory(tmp_path: Path) -> None:
    store = create_vector_store(Settings(_env_file=None), 8)

    assert isinstance(store, FaissVectorStore)
    assert (store.name, store.dimension) == ("faiss", 8)
