"""Vector storage for dense retrieval.

`VectorStore` hides the backend so the engine only asks "given this query vector, which
chunks are closest?". FAISS is the local default; a pgvector (or Qdrant/Chroma) store
can implement the same four methods later — the index directory simply stays empty and
`search` queries the database instead.
"""

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from app.core.config import Settings

VECTOR_INDEX_FILENAME = "dense.faiss"
VECTOR_IDS_FILENAME = "dense_ids.json"


class VectorStore(ABC):
    name: str
    dimension: int

    @abstractmethod
    def add(self, ids: Sequence[str], vectors: np.ndarray) -> None: ...

    @abstractmethod
    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        """Closest ids with their similarity, best first."""

    @abstractmethod
    def save(self, directory: Path) -> None: ...

    @property
    @abstractmethod
    def size(self) -> int: ...


class FaissVectorStore(VectorStore):
    """Exact inner-product search (`IndexFlatIP`) over L2-normalised vectors = cosine.

    Exact search keeps results reproducible for research; an approximate index (HNSW/IVF)
    can be swapped in here if a repository ever grows beyond what exact search handles.
    """

    name = "faiss"

    def __init__(self, dimension: int) -> None:
        import faiss

        self.dimension = dimension
        self._index = faiss.IndexFlatIP(dimension)
        self._ids: list[str] = []

    def add(self, ids: Sequence[str], vectors: np.ndarray) -> None:
        if len(ids) != vectors.shape[0]:
            raise ValueError("ids and vectors must have the same length")
        if vectors.shape[0] == 0:
            return
        if vectors.shape[1] != self.dimension:
            raise ValueError(
                f"expected {self.dimension}-dimensional vectors, got {vectors.shape[1]}"
            )
        self._index.add(np.ascontiguousarray(vectors, dtype=np.float32))
        self._ids.extend(ids)

    def search(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        if not self._ids:
            return []
        query = np.ascontiguousarray(np.asarray(vector, dtype=np.float32).reshape(1, -1))
        scores, positions = self._index.search(query, min(top_k, len(self._ids)))
        return [
            (self._ids[position], float(score))
            for position, score in zip(positions[0], scores[0], strict=True)
            if position >= 0
        ]

    def save(self, directory: Path) -> None:
        import faiss

        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(directory / VECTOR_INDEX_FILENAME))
        (directory / VECTOR_IDS_FILENAME).write_text(json.dumps(self._ids), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "FaissVectorStore":
        import faiss

        index = faiss.read_index(str(directory / VECTOR_INDEX_FILENAME))
        store = cls.__new__(cls)
        store.name = "faiss"
        store.dimension = index.d
        store._index = index
        store._ids = json.loads((directory / VECTOR_IDS_FILENAME).read_text(encoding="utf-8"))
        return store

    @property
    def size(self) -> int:
        return len(self._ids)


def create_vector_store(settings: Settings, dimension: int) -> VectorStore:
    return FaissVectorStore(dimension)


def load_vector_store(settings: Settings, directory: Path) -> VectorStore | None:
    if not (directory / VECTOR_INDEX_FILENAME).exists():
        return None
    return FaissVectorStore.load(directory)
