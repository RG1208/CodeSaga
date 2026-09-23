"""Embedding providers.

`EmbeddingProvider` is the only thing the rest of CodeSage knows about embeddings, so
the model is configuration, never a hard-coded import:

* `FastEmbedProvider` runs BGE models locally through ONNX Runtime (`EMBEDDING_MODEL`,
  default `BAAI/bge-small-en-v1.5`). Models are downloaded once into `EMBEDDING_CACHE_DIR`.
* `HashingEmbeddingProvider` needs no model at all: it hashes code tokens into a fixed
  vector. Deterministic and offline, which is what the test suite uses.

A sentence-transformers (PyTorch) or API-backed provider can be added by implementing
the same three methods; nothing else changes.
"""

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from app.core.config import Settings
from app.retrieval.errors import EmbeddingUnavailableError
from app.retrieval.tokenizer import tokenize

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]


def _normalise(vectors: np.ndarray) -> np.ndarray:
    """Unit-length rows, so an inner product is the cosine similarity."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


class EmbeddingProvider(ABC):
    name: str
    model_id: str
    dimension: int

    @abstractmethod
    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        batch_size: int | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> np.ndarray:
        """(len(texts), dimension) float32, L2-normalised."""

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray:
        """(dimension,) float32, L2-normalised."""

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model_id, "dimension": self.dimension}


class HashingEmbeddingProvider(EmbeddingProvider):
    """Feature hashing over code tokens: no model, no download, fully deterministic.

    Similarity is lexical rather than semantic, so it is a baseline and a test double —
    not a replacement for a real embedding model.
    """

    name = "hashing"

    def __init__(self, dimension: int = 256, model_id: str = "hashing-v1") -> None:
        self.dimension = dimension
        self.model_id = model_id

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            position = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[position] += sign
        return vector

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        batch_size: int | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vectors = np.vstack([self._vector(text) for text in texts])
        if on_progress is not None:
            on_progress(len(texts), len(texts))
        return _normalise(vectors)

    def embed_query(self, text: str) -> np.ndarray:
        return _normalise(self._vector(text).reshape(1, -1))[0]


class FastEmbedProvider(EmbeddingProvider):
    """Local BGE embeddings via fastembed (ONNX Runtime). The model loads lazily."""

    name = "fastembed"

    def __init__(self, settings: Settings) -> None:
        self.model_id = settings.embedding_model
        self.settings = settings
        self._model: Any = None
        self._lock = threading.Lock()
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._load()
        return int(self._dimension or 0)

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from fastembed import TextEmbedding

                logger.info("loading embedding model", extra={"model": self.model_id})
                model = TextEmbedding(
                    model_name=self.model_id,
                    cache_dir=str(self.settings.embedding_cache_dir),
                    threads=self.settings.embedding_threads,
                )
                description = next(
                    item
                    for item in TextEmbedding.list_supported_models()
                    if item["model"] == self.model_id
                )
                self._dimension = int(description["dim"])
                self._model = model
            except Exception as exc:  # unsupported name, download failure, missing package
                raise EmbeddingUnavailableError(
                    f"Could not load embedding model '{self.model_id}': {exc}"
                ) from exc
        return self._model

    def _truncate(self, text: str) -> str:
        # The model ignores anything past its context window; cutting here saves time.
        return text[: self.settings.embedding_max_chars]

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        batch_size: int | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        model = self._load()
        size = batch_size or self.settings.embedding_batch_size
        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), size):
            batch = [self._truncate(text) for text in texts[start : start + size]]
            vectors.extend(model.embed(batch, batch_size=size))
            if on_progress is not None:
                on_progress(min(start + size, len(texts)), len(texts))
        return _normalise(np.vstack(vectors))

    def embed_query(self, text: str) -> np.ndarray:
        model = self._load()
        prefixed = f"{self.settings.embedding_query_prefix}{text}"
        vector = next(iter(model.embed([self._truncate(prefixed)])))
        return _normalise(np.asarray(vector, dtype=np.float32).reshape(1, -1))[0]

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "query_prefix": self.settings.embedding_query_prefix}


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "hashing":
        return HashingEmbeddingProvider()
    return FastEmbedProvider(settings)
