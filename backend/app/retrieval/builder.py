"""Turning a repository checkout into search indexes.

Runs as the last stage of the indexing job:

    chunks  →  BM25 index (always)  +  dense vectors (when embeddings are available)

Dense indexing is the slow part (it runs a neural model over every chunk), so it
reports progress and can be cancelled. If the embedding model cannot be loaded — no
network on a first run, for example — the build still finishes: BM25 works, and the
manifest records why the dense index is missing.
"""

import json
import logging
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.retrieval.bm25 import BM25Index, BM25Params
from app.retrieval.chunking import Chunk
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.errors import EmbeddingUnavailableError
from app.retrieval.index_store import CHUNK_IDS_FILENAME, RepositoryIndexStore, build_manifest
from app.retrieval.tokenizer import TOKENIZER_VERSION, tokenize, tokenize_path
from app.retrieval.vector_store import create_vector_store

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]


@dataclass
class RetrievalBuild:
    directory: Path
    chunk_rows: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def chunk_tokens(chunk: Chunk) -> list[str]:
    """Tokens BM25 indexes: the chunk text plus its path and symbol name."""
    return tokenize(chunk.index_text()) + tokenize_path(chunk.file_path)


def build_retrieval_index(
    *,
    repository_id: uuid.UUID,
    commit_sha: str | None,
    chunks: Sequence[Chunk],
    settings: Settings,
    embeddings: EmbeddingProvider,
    index_store: RepositoryIndexStore,
    on_progress: ProgressCallback | None = None,
) -> RetrievalBuild:
    directory = index_store.create_temp_dir(repository_id)
    tokenised = [chunk_tokens(chunk) for chunk in chunks]
    bm25 = BM25Index.build(tokenised, BM25Params(k1=settings.bm25_k1, b=settings.bm25_b))
    bm25.save(directory)
    (directory / CHUNK_IDS_FILENAME).write_text(
        json.dumps([str(chunk.chunk_id) for chunk in chunks]), encoding="utf-8"
    )

    dense = _build_dense(
        chunks=chunks,
        settings=settings,
        embeddings=embeddings,
        directory=directory,
        on_progress=on_progress,
    )
    manifest = build_manifest(
        repository_id=repository_id,
        commit_sha=commit_sha,
        chunk_count=len(chunks),
        bm25={
            "k1": settings.bm25_k1,
            "b": settings.bm25_b,
            "tokenizer_version": TOKENIZER_VERSION,
            "terms": bm25.term_count,
            "average_length": round(bm25.average_length, 2),
        },
        dense=dense,
    )
    index_store.write_manifest(directory, manifest)

    return RetrievalBuild(
        directory=directory,
        chunk_rows=[
            _chunk_row(chunk, tokens) for chunk, tokens in zip(chunks, tokenised, strict=True)
        ],
        summary={
            "chunks": len(chunks),
            "chunker_version": manifest["chunker_version"],
            "chunk_types": _counts(chunk.chunk_type for chunk in chunks),
            "languages": _counts(chunk.language for chunk in chunks),
            "bm25": manifest["bm25"],
            "dense": dense,
        },
    )


def _build_dense(
    *,
    chunks: Sequence[Chunk],
    settings: Settings,
    embeddings: EmbeddingProvider,
    directory: Path,
    on_progress: ProgressCallback | None,
) -> dict[str, Any]:
    if not settings.dense_retrieval_enabled:
        return {"status": "disabled", "reason": "DENSE_RETRIEVAL_ENABLED is false"}
    if not chunks:
        return {"status": "empty", "provider": embeddings.name, "model": embeddings.model_id}

    selected = list(chunks[: settings.max_embedded_chunks])
    skipped = len(chunks) - len(selected)
    try:
        vectors = embeddings.embed_documents(
            [chunk.index_text() for chunk in selected],
            batch_size=settings.embedding_batch_size,
            on_progress=on_progress,
        )
        store = create_vector_store(settings, vectors.shape[1])
        store.add([str(chunk.chunk_id) for chunk in selected], vectors)
        store.save(directory)
    except EmbeddingUnavailableError as exc:
        logger.warning("dense index skipped", extra={"reason": exc.message})
        return {
            "status": "unavailable",
            "reason": exc.message,
            "provider": embeddings.name,
            "model": embeddings.model_id,
        }
    return {
        "status": "ready",
        "provider": embeddings.name,
        "model": embeddings.model_id,
        "dimension": int(vectors.shape[1]),
        "vectors": len(selected),
        "skipped": skipped,
        "store": store.name,
    }


def _chunk_row(chunk: Chunk, tokens: Sequence[str]) -> dict[str, Any]:
    return {
        "id": chunk.chunk_id,
        "file_path": chunk.file_path,
        "language": chunk.language,
        "chunk_type": chunk.chunk_type,
        "symbol_id": chunk.symbol_id,
        "symbol_name": chunk.symbol_name,
        "symbol_type": chunk.symbol_type,
        "qualified_name": chunk.qualified_name,
        "parent_symbol": chunk.parent_symbol,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "content": chunk.content,
        "token_count": len(tokens),
        "chunk_metadata": chunk.metadata,
    }


def _counts(values: Iterable[str]) -> dict[str, int]:
    return dict(Counter(values).most_common())
