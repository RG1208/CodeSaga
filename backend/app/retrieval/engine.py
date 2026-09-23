"""The retrieval strategies.

Every strategy is a `Retriever` with one method, so each can be evaluated on its own
and they compose: `hybrid_rerank` is simply a reranker wrapped around `hybrid`.

    bm25          BM25Retriever
    dense         DenseRetriever
    hybrid        HybridRetriever(bm25, dense, fusion)
    hybrid_rerank RerankingRetriever(HybridRetriever(...), cross-encoder)
"""

import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core.config import Settings
from app.retrieval.bm25 import BM25Index
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.errors import IndexUnavailableError
from app.retrieval.fusion import FusionConfig, ScoredChunk, fuse
from app.retrieval.rerankers import Reranker
from app.retrieval.tokenizer import tokenize
from app.retrieval.vector_store import VectorStore

# chunk id → text to show the reranker (the service reads it from the database)
DocumentLookup = Callable[[Sequence[str]], dict[str, str]]


class RetrievalStrategy(StrEnum):
    BM25 = "bm25"
    DENSE = "dense"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


@dataclass
class RetrievalIndex:
    """The artifacts one repository's search needs, loaded from disk."""

    repository_id: uuid.UUID
    chunk_ids: list[str]  # BM25 document position → chunk id
    bm25: BM25Index
    vectors: VectorStore | None
    manifest: dict[str, Any]

    @property
    def has_dense(self) -> bool:
        return self.vectors is not None and self.vectors.size > 0


@dataclass
class SearchOutcome:
    items: list[ScoredChunk]
    strategy: RetrievalStrategy
    timings: dict[str, float]
    reranker: str | None = None
    fusion: FusionConfig | None = None
    candidates: int = 0


@dataclass(frozen=True)
class SearchOptions:
    """Per-request retrieval settings; defaults come from configuration."""

    fusion: FusionConfig = field(default_factory=FusionConfig)
    candidates: int = 50
    rerank_candidates: int = 20

    @classmethod
    def from_settings(cls, settings: Settings, **overrides: Any) -> "SearchOptions":
        fusion = FusionConfig(
            method=overrides.get("fusion_method") or settings.hybrid_fusion,
            bm25_weight=_first(overrides.get("bm25_weight"), settings.hybrid_bm25_weight),
            dense_weight=_first(overrides.get("dense_weight"), settings.hybrid_dense_weight),
            rrf_k=_first(overrides.get("rrf_k"), settings.hybrid_rrf_k),
        )
        return cls(
            fusion=fusion,
            candidates=_first(overrides.get("candidates"), settings.hybrid_candidates),
            rerank_candidates=_first(
                overrides.get("rerank_candidates"), settings.rerank_candidates
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Flat, and named like the request's `options`, so a logged run can be replayed."""
        return {
            "fusion_method": self.fusion.method,
            "bm25_weight": self.fusion.bm25_weight,
            "dense_weight": self.fusion.dense_weight,
            "rrf_k": self.fusion.rrf_k,
            "candidates": self.candidates,
            "rerank_candidates": self.rerank_candidates,
        }


def _first(value: Any, fallback: Any) -> Any:
    return fallback if value is None else value


class _Timer:
    """Records how long each retrieval phase took (reported and logged for research)."""

    def __init__(self) -> None:
        self.timings: dict[str, float] = {}

    def measure(self, name: str, function: Callable[[], Any]) -> Any:
        started = time.perf_counter()
        try:
            return function()
        finally:
            self.timings[name] = round((time.perf_counter() - started) * 1000, 3)


class Retriever(ABC):
    name: str

    @abstractmethod
    def retrieve(self, query: str, top_k: int) -> list[ScoredChunk]: ...


class BM25Retriever(Retriever):
    name = "bm25"

    def __init__(self, index: RetrievalIndex, timer: _Timer | None = None) -> None:
        self.index = index
        self.timer = timer or _Timer()

    def retrieve(self, query: str, top_k: int) -> list[ScoredChunk]:
        tokens = self.timer.measure("tokenize_ms", lambda: tokenize(query))
        hits = self.timer.measure("bm25_ms", lambda: self.index.bm25.search(tokens, top_k))
        return [
            ScoredChunk(
                chunk_id=self.index.chunk_ids[position],
                score=score,
                rank=rank,
                components={"bm25": score, "bm25_rank": float(rank)},
            )
            for rank, (position, score) in enumerate(hits, start=1)
        ]


class DenseRetriever(Retriever):
    name = "dense"

    def __init__(
        self, index: RetrievalIndex, embeddings: EmbeddingProvider, timer: _Timer | None = None
    ) -> None:
        self.index = index
        self.embeddings = embeddings
        self.timer = timer or _Timer()

    def retrieve(self, query: str, top_k: int) -> list[ScoredChunk]:
        if not self.index.has_dense:
            raise IndexUnavailableError(
                "This repository has no dense index. Re-index it with embeddings enabled.",
                code="dense_index_unavailable",
            )
        vector = self.timer.measure("embed_query_ms", lambda: self.embeddings.embed_query(query))
        assert self.index.vectors is not None
        hits = self.timer.measure("dense_ms", lambda: self.index.vectors.search(vector, top_k))
        return [
            ScoredChunk(
                chunk_id=chunk_id,
                score=score,
                rank=rank,
                components={"dense": score, "dense_rank": float(rank)},
            )
            for rank, (chunk_id, score) in enumerate(hits, start=1)
        ]


class HybridRetriever(Retriever):
    name = "hybrid"

    def __init__(
        self,
        bm25: BM25Retriever,
        dense: DenseRetriever,
        options: SearchOptions,
        timer: _Timer | None = None,
    ) -> None:
        self.bm25 = bm25
        self.dense = dense
        self.options = options
        self.timer = timer or _Timer()

    def retrieve(self, query: str, top_k: int) -> list[ScoredChunk]:
        depth = max(self.options.candidates, top_k)
        lexical = self.bm25.retrieve(query, depth)
        semantic = self.dense.retrieve(query, depth)
        merged = self.timer.measure(
            "fusion_ms", lambda: fuse({"bm25": lexical, "dense": semantic}, self.options.fusion)
        )
        return merged[:top_k]


class RerankingRetriever(Retriever):
    """Re-scores the first stage's candidates with a cross-encoder."""

    name = "rerank"

    def __init__(
        self,
        base: Retriever,
        reranker: Reranker,
        documents: DocumentLookup,
        options: SearchOptions,
        timer: _Timer | None = None,
    ) -> None:
        self.base = base
        self.reranker = reranker
        self.documents = documents
        self.options = options
        self.timer = timer or _Timer()

    def retrieve(self, query: str, top_k: int) -> list[ScoredChunk]:
        depth = max(self.options.rerank_candidates, top_k)
        candidates = self.base.retrieve(query, depth)
        if not candidates:
            return []
        texts = self.documents([item.chunk_id for item in candidates])
        scores = self.timer.measure(
            "rerank_ms",
            lambda: self.reranker.rerank(
                query, [texts.get(item.chunk_id, "") for item in candidates]
            ),
        )
        for item, score in zip(candidates, scores, strict=True):
            item.components["rerank"] = float(score)
            item.components.setdefault("first_stage_score", item.score)
            item.components["first_stage_rank"] = float(item.rank)
            item.score = float(score)
        ordered = sorted(candidates, key=lambda item: (-item.score, item.chunk_id))
        for rank, item in enumerate(ordered, start=1):
            item.rank = rank
        return ordered[:top_k]


class RetrievalEngine:
    """Builds the retriever for a strategy and runs it against one repository's index."""

    def __init__(
        self,
        index: RetrievalIndex,
        embeddings: EmbeddingProvider,
        documents: DocumentLookup,
        settings: Settings,
    ) -> None:
        self.index = index
        self.embeddings = embeddings
        self.documents = documents
        self.settings = settings

    def build_retriever(
        self,
        strategy: RetrievalStrategy,
        options: SearchOptions,
        reranker: Reranker | None,
        timer: _Timer,
    ) -> Retriever:
        bm25 = BM25Retriever(self.index, timer)
        dense = DenseRetriever(self.index, self.embeddings, timer)
        base: Retriever
        if strategy is RetrievalStrategy.BM25:
            base = bm25
        elif strategy is RetrievalStrategy.DENSE:
            base = dense
        else:
            base = HybridRetriever(bm25, dense, options, timer)
        if reranker is not None:
            return RerankingRetriever(base, reranker, self.documents, options, timer)
        return base

    def search(
        self,
        query: str,
        *,
        strategy: RetrievalStrategy,
        top_k: int,
        options: SearchOptions,
        reranker: Reranker | None = None,
    ) -> SearchOutcome:
        timer = _Timer()
        retriever = self.build_retriever(strategy, options, reranker, timer)
        started = time.perf_counter()
        items = retriever.retrieve(query, top_k)
        timer.timings["total_ms"] = round((time.perf_counter() - started) * 1000, 3)
        return SearchOutcome(
            items=items,
            strategy=strategy,
            timings=timer.timings,
            reranker=reranker.name if reranker else None,
            fusion=options.fusion
            if strategy in (RetrievalStrategy.HYBRID, RetrievalStrategy.HYBRID_RERANK)
            else None,
            candidates=options.candidates if strategy.value.startswith("hybrid") else top_k,
        )
