import logging
import time
import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    UnprocessableError,
)
from app.models.repository import Repository
from app.repositories import CodeChunkRepository, RepositoryRepository, RetrievalLogRepository
from app.retrieval.chunking import chunk_header
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.engine import RetrievalEngine, RetrievalIndex, RetrievalStrategy, SearchOptions
from app.retrieval.errors import (
    EmbeddingUnavailableError,
    IndexUnavailableError,
    RerankerUnavailableError,
    RetrievalError,
)
from app.retrieval.index_store import RepositoryIndexStore
from app.retrieval.rerankers import Reranker, RerankerRegistry
from app.schemas.search import (
    ChunkResult,
    SearchIndexInfo,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)

logger = logging.getLogger(__name__)

_RERANKED_STRATEGIES = frozenset({RetrievalStrategy.HYBRID_RERANK})


def to_app_error(exc: RetrievalError) -> AppError:
    """Retrieval (domain) errors become HTTP errors here, not in the retrieval package."""
    if isinstance(exc, IndexUnavailableError):
        return ConflictError(exc.message, code=exc.code)
    if isinstance(exc, EmbeddingUnavailableError):
        return ServiceUnavailableError(exc.message, code=exc.code)
    if isinstance(exc, RerankerUnavailableError):
        if exc.code == "unknown_reranker":
            return UnprocessableError(exc.message, code=exc.code)
        return ServiceUnavailableError(exc.message, code=exc.code)
    return UnprocessableError(exc.message, code=exc.code)


class SearchService:
    """Runs a retrieval request against one repository's index and records it.

    No answer generation: this phase returns the chunks and their scores.
    """

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        index_store: RepositoryIndexStore,
        embeddings: EmbeddingProvider,
        rerankers: RerankerRegistry,
    ) -> None:
        self.session = session
        self.settings = settings
        self.index_store = index_store
        self.embeddings = embeddings
        self.rerankers = rerankers
        self.repositories = RepositoryRepository(session)
        self.chunks = CodeChunkRepository(session)
        self.logs = RetrievalLogRepository(session)

    def search(self, repository_id: uuid.UUID, request: SearchRequest) -> SearchResponse:
        repository = self._repository(repository_id)
        started = time.perf_counter()
        try:
            index = self.index_store.load(
                repository.id,
                commit_sha=repository.commit_sha,
                embeddings=self.embeddings,
                settings=self.settings,
            )
            reranker = self._reranker(request)
            options = SearchOptions.from_settings(
                self.settings, **request.options.model_dump(exclude_none=True)
            )
            engine = RetrievalEngine(index, self.embeddings, self._documents, self.settings)
            outcome = engine.search(
                request.query,
                strategy=request.retrieval_strategy,
                top_k=request.top_k,
                options=options,
                reranker=reranker,
            )
        except RetrievalError as exc:
            raise to_app_error(exc) from exc

        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        results = self._hydrate(outcome.items, include_content=request.include_content)
        response = SearchResponse(
            query=request.query,
            retrieval_strategy=outcome.strategy,
            reranker=outcome.reranker,
            top_k=request.top_k,
            result_count=len(results),
            latency_ms=latency_ms,
            timings=outcome.timings,
            options=options.to_dict(),
            index=self._index_info(index),
            results=results,
        )
        if request.log if request.log is not None else self.settings.retrieval_logging_enabled:
            response.log_id = self._record(repository, request, response)
        logger.info(
            "retrieval search",
            extra={
                "repository_id": str(repository.id),
                "strategy": outcome.strategy.value,
                "top_k": request.top_k,
                "results": len(results),
                "latency_ms": latency_ms,
            },
        )
        return response

    # -- pieces ------------------------------------------------------------------

    def _repository(self, repository_id: uuid.UUID) -> Repository:
        repository = self.repositories.get(repository_id)
        if repository is None:
            raise NotFoundError(f"Repository {repository_id} not found.")
        if repository.local_path is None:
            raise ConflictError(
                "This repository has not been indexed yet.", code="repository_not_indexed"
            )
        return repository

    def _reranker(self, request: SearchRequest) -> Reranker | None:
        name = request.reranker
        if name is None and request.retrieval_strategy in _RERANKED_STRATEGIES:
            name = self.rerankers.default
            if name is None:
                raise RerankerUnavailableError(
                    "No reranker is configured (set RERANKER_PROVIDER).",
                    code="reranker_unavailable",
                )
        return self.rerankers.get(name) if name else None

    def _documents(self, chunk_ids: Sequence[str]) -> dict[str, str]:
        """Text for the reranker: the same header + content the index was built from."""
        rows = self.chunks.get_many([uuid.UUID(chunk_id) for chunk_id in chunk_ids])
        documents: dict[str, str] = {}
        for chunk in rows.values():
            header = chunk_header(
                chunk.file_path,
                chunk.language,
                chunk.chunk_type,
                chunk.symbol_type,
                chunk.qualified_name or chunk.symbol_name,
            )
            documents[str(chunk.id)] = f"{header}\n{chunk.content}"
        return documents

    def _hydrate(self, items: Sequence, *, include_content: bool) -> list[SearchResultItem]:  # type: ignore[type-arg]
        rows = self.chunks.get_many([uuid.UUID(item.chunk_id) for item in items])
        results: list[SearchResultItem] = []
        for item in items:
            chunk = rows.get(uuid.UUID(item.chunk_id))
            if chunk is None:
                # The index and the database disagree; skip rather than invent a result.
                logger.warning(
                    "retrieved chunk missing from database", extra={"chunk_id": item.chunk_id}
                )
                continue
            result = ChunkResult.model_validate(chunk)
            if not include_content:
                result.content = None
            results.append(
                SearchResultItem(
                    rank=len(results) + 1,
                    score=round(float(item.score), 6),
                    scores={key: round(float(value), 6) for key, value in item.components.items()},
                    chunk=result,
                )
            )
        return results

    @staticmethod
    def _index_info(index: RetrievalIndex) -> SearchIndexInfo:
        dense = index.manifest.get("dense") or {}
        return SearchIndexInfo(
            commit_sha=index.manifest.get("commit_sha"),
            chunk_count=index.manifest.get("chunk_count", len(index.chunk_ids)),
            bm25_terms=index.bm25.term_count,
            dense_available=index.has_dense,
            embedding_model=dense.get("model"),
            embedding_provider=dense.get("provider"),
            chunker_version=index.manifest.get("chunker_version"),
            built_at=index.manifest.get("built_at"),
        )

    def _record(
        self, repository: Repository, request: SearchRequest, response: SearchResponse
    ) -> uuid.UUID:
        """Store the query, the strategy, the ranked chunk ids, scores and latency."""
        log = self.logs.record(
            repository_id=repository.id,
            repository_name=repository.name,
            commit_sha=repository.commit_sha,
            query=request.query,
            strategy=response.retrieval_strategy.value,
            reranker=response.reranker,
            top_k=request.top_k,
            options=response.options,
            index_info=response.index.model_dump(mode="json"),
            result_chunk_ids=[str(item.chunk.chunk_id) for item in response.results],
            results=[
                {
                    "chunk_id": str(item.chunk.chunk_id),
                    "rank": item.rank,
                    "score": item.score,
                    "scores": item.scores,
                    "file_path": item.chunk.file_path,
                    "start_line": item.chunk.start_line,
                    "end_line": item.chunk.end_line,
                    "symbol": item.chunk.qualified_name,
                }
                for item in response.results
            ],
            result_count=len(response.results),
            latency_ms=response.latency_ms,
            timings=response.timings,
        )
        self.session.commit()
        return log.id
