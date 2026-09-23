"""Rerankers.

A retriever compares a query against every chunk independently (a vector or a bag of
terms). A **cross-encoder** reads the query and one chunk *together* and scores the
pair, which is far more accurate — and far too slow to run over a whole repository. So
it only re-scores the top candidates from the first stage.

`Reranker` is the interface; `CrossEncoderReranker` runs a local ONNX model through
fastembed. A hosted reranker (Cohere, Voyage…) would implement the same method.
"""

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from app.core.config import Settings
from app.retrieval.errors import RerankerUnavailableError

logger = logging.getLogger(__name__)


class Reranker(ABC):
    name: str
    model_id: str

    @abstractmethod
    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """A relevance score per document, in the order given."""

    def describe(self) -> dict[str, Any]:
        return {"reranker": self.name, "model": self.model_id}


class CrossEncoderReranker(Reranker):
    name = "cross_encoder"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_id = settings.reranker_model
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is None:
                try:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    logger.info("loading reranker model", extra={"model": self.model_id})
                    self._model = TextCrossEncoder(
                        model_name=self.model_id,
                        cache_dir=str(self.settings.embedding_cache_dir),
                        threads=self.settings.embedding_threads,
                    )
                except Exception as exc:
                    raise RerankerUnavailableError(
                        f"Could not load reranker model '{self.model_id}': {exc}"
                    ) from exc
        return self._model

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        model = self._load()
        # Cross-encoders read query and document as one sequence; long chunks are cut.
        truncated = [document[: self.settings.rerank_max_chars] for document in documents]
        return [float(score) for score in model.rerank(query, truncated)]


class RerankerRegistry:
    """Named rerankers, so a request can pick one (`"reranker": "cross_encoder"`)."""

    def __init__(self, rerankers: dict[str, Reranker] | None = None) -> None:
        self._rerankers: dict[str, Reranker] = dict(rerankers or {})

    def register(self, reranker: Reranker) -> None:
        self._rerankers[reranker.name] = reranker

    def get(self, name: str | None) -> Reranker:
        if name is None:
            raise RerankerUnavailableError("No reranker is configured.")
        reranker = self._rerankers.get(name)
        if reranker is None:
            available = ", ".join(sorted(self._rerankers)) or "none"
            raise RerankerUnavailableError(
                f"Unknown reranker '{name}'. Available: {available}.", code="unknown_reranker"
            )
        return reranker

    @property
    def names(self) -> list[str]:
        return sorted(self._rerankers)

    @property
    def default(self) -> str | None:
        return self.names[0] if self._rerankers else None


def create_reranker_registry(settings: Settings) -> RerankerRegistry:
    registry = RerankerRegistry()
    if settings.reranker_provider == "cross_encoder":
        registry.register(CrossEncoderReranker(settings))
    return registry
