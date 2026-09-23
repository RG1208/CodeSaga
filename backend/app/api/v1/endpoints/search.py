"""Code retrieval endpoint (Phase 4): find relevant code, no answer generation yet."""

import uuid

from fastapi import APIRouter

from app.api.deps import SearchServiceDep
from app.schemas.common import ErrorResponse
from app.schemas.search import SearchRequest, SearchResponse

router = APIRouter(prefix="/repositories/{repository_id}", tags=["search"])


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Unknown repository."},
        409: {"model": ErrorResponse, "description": "Not indexed, or the index is out of date."},
        422: {"model": ErrorResponse, "description": "Invalid request or unknown reranker."},
        503: {
            "model": ErrorResponse,
            "description": "The embedding or reranker model is unavailable.",
        },
    },
)
def search_repository(
    repository_id: uuid.UUID, payload: SearchRequest, service: SearchServiceDep
) -> SearchResponse:
    """Retrieve the chunks most relevant to `query`.

    Strategies: `bm25` (lexical), `dense` (BGE embeddings), `hybrid` (fusion of both),
    `hybrid_rerank` (hybrid candidates re-scored by a cross-encoder). `options` overrides
    the configured fusion method, weights and candidate depths, so strategies can be
    compared directly. Each result carries its rank, scores and source metadata
    (file path and line range). Searches are recorded for research unless `log` is false.
    """
    return service.search(repository_id, payload)
