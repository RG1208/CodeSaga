"""API contract for code retrieval (Phase 4)."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.engine import RetrievalStrategy
from app.schemas.common import ORMSchema


class RetrievalOptions(BaseModel):
    """Per-request overrides of the configured retrieval settings.

    Everything a retrieval experiment needs to vary is here, so strategies can be
    compared without restarting the server.
    """

    model_config = ConfigDict(extra="forbid")

    fusion_method: Literal["rrf", "weighted"] | None = Field(
        default=None, description="How BM25 and dense results are combined."
    )
    bm25_weight: float | None = Field(default=None, ge=0, le=10)
    dense_weight: float | None = Field(default=None, ge=0, le=10)
    rrf_k: int | None = Field(default=None, ge=1, le=1000, description="Reciprocal-rank constant.")
    candidates: int | None = Field(
        default=None, ge=1, le=500, description="How deep each retriever goes before fusion."
    )
    rerank_candidates: int | None = Field(
        default=None, ge=1, le=200, description="How many candidates the reranker re-scores."
    )


class SearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=1000, examples=["how are passwords hashed"])
    top_k: int = Field(default=10, ge=1, le=50)
    retrieval_strategy: RetrievalStrategy = Field(
        default=RetrievalStrategy.HYBRID,
        description=(
            "bm25 (lexical), dense (embeddings), hybrid (both), "
            "hybrid_rerank (both, re-scored by a cross-encoder)."
        ),
    )
    reranker: str | None = Field(
        default=None, description="Reranker name; defaults to the configured one for hybrid_rerank."
    )
    options: RetrievalOptions = Field(default_factory=RetrievalOptions)
    include_content: bool = Field(default=True, description="Return the chunk text.")
    log: bool | None = Field(
        default=None, description="Record this search for research. Defaults to configuration."
    )


class ChunkResult(ORMSchema):
    """Source metadata for one retrieved chunk: enough to cite and open it."""

    chunk_id: uuid.UUID = Field(validation_alias="id")
    repository_id: uuid.UUID
    file_path: str
    language: str
    chunk_type: str
    symbol_name: str | None
    symbol_type: str | None
    qualified_name: str | None
    parent_symbol: str | None
    start_line: int
    end_line: int
    token_count: int
    content: str | None = None


class SearchResultItem(BaseModel):
    rank: int
    score: float = Field(description="Score of the strategy that produced the final ranking.")
    scores: dict[str, float] = Field(
        description="Per-retriever detail, e.g. bm25, bm25_rank, dense, dense_rank, rerank."
    )
    chunk: ChunkResult


class SearchIndexInfo(BaseModel):
    commit_sha: str | None
    chunk_count: int
    bm25_terms: int
    dense_available: bool
    embedding_model: str | None = None
    embedding_provider: str | None = None
    chunker_version: int | None = None
    built_at: str | None = None


class SearchResponse(BaseModel):
    query: str
    retrieval_strategy: RetrievalStrategy
    reranker: str | None
    top_k: int
    result_count: int
    latency_ms: float
    timings: dict[str, float] = Field(
        description="Milliseconds per phase (tokenize, bm25, dense, fusion, rerank)."
    )
    options: dict[str, Any]
    index: SearchIndexInfo
    results: list[SearchResultItem]
    log_id: uuid.UUID | None = Field(
        default=None, description="Research log row, when logging is on."
    )
