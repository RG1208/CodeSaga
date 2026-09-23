"""Where search indexes live on disk, and how they are loaded.

One directory per repository, written to a temporary location and renamed into place
when a build succeeds (the same swap the repository checkout uses), so a failed
re-index never leaves a half-written index:

    <INDEX_STORAGE_DIR>/<repository-uuid>/
        manifest.json       what was built, from which commit, with which model
        chunk_ids.json      BM25 document position → chunk id
        bm25.npz            postings, term frequencies, document lengths
        bm25_vocabulary.json
        dense.faiss         vectors (absent when dense indexing is off or failed)
        dense_ids.json

`manifest.json` records the commit the index was built from. If the repository has moved
on, or the configured embedding model no longer matches, search says so instead of
returning results from a stale index.
"""

import json
import logging
import threading
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.ingestion.storage import ensure_within
from app.retrieval.bm25 import BM25Index
from app.retrieval.chunking import CHUNKER_VERSION
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.engine import RetrievalIndex
from app.retrieval.errors import IndexUnavailableError
from app.retrieval.vector_store import load_vector_store

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "manifest.json"
CHUNK_IDS_FILENAME = "chunk_ids.json"
_TEMP_DIR_NAME = ".tmp"
_CACHE_SIZE = 4


class RepositoryIndexStore:
    """Creates, installs, removes and loads per-repository index directories."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._cache: OrderedDict[tuple[uuid.UUID, str], RetrievalIndex] = OrderedDict()
        self._lock = threading.Lock()

    # -- directories ---------------------------------------------------------------

    @property
    def temp_root(self) -> Path:
        return self.root / _TEMP_DIR_NAME

    def path_for(self, repository_id: uuid.UUID) -> Path:
        return ensure_within(self.root, self.root / str(repository_id))

    def create_temp_dir(self, repository_id: uuid.UUID) -> Path:
        self.temp_root.mkdir(parents=True, exist_ok=True)
        directory = ensure_within(
            self.temp_root, self.temp_root / f"{repository_id}-{uuid.uuid4().hex}"
        )
        directory.mkdir(parents=True)
        return directory

    def install(self, repository_id: uuid.UUID, directory: Path) -> Path:
        """Move a finished index into place, replacing the previous one."""
        source = ensure_within(self.temp_root, directory)
        destination = self.path_for(repository_id)
        if destination.exists():
            self._remove_tree(destination)
        source.rename(destination)
        self._invalidate(repository_id)
        return destination

    def remove(self, repository_id: uuid.UUID) -> bool:
        self._invalidate(repository_id)
        path = self.path_for(repository_id)
        if not path.exists():
            return False
        self._remove_tree(path)
        return True

    def discard(self, directory: Path) -> None:
        target = ensure_within(self.temp_root, directory)
        if target.exists():
            self._remove_tree(target)

    def clear_temp(self) -> None:
        if self.temp_root.exists():
            self._remove_tree(self.temp_root)

    @staticmethod
    def _remove_tree(path: Path) -> None:
        import shutil

        shutil.rmtree(path, ignore_errors=True)

    # -- manifest ------------------------------------------------------------------

    def write_manifest(self, directory: Path, manifest: dict[str, Any]) -> None:
        (directory / MANIFEST_FILENAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def read_manifest(self, repository_id: uuid.UUID) -> dict[str, Any] | None:
        path = self.path_for(repository_id) / MANIFEST_FILENAME
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            logger.warning("unreadable index manifest", extra={"repository_id": str(repository_id)})
            return None

    # -- loading -------------------------------------------------------------------

    def load(
        self,
        repository_id: uuid.UUID,
        *,
        commit_sha: str | None,
        embeddings: EmbeddingProvider,
        settings: Settings,
    ) -> RetrievalIndex:
        """Load (and cache) a repository's index, refusing stale or mismatched ones."""
        manifest = self.read_manifest(repository_id)
        if manifest is None:
            raise IndexUnavailableError(
                "This repository has no search index yet. Index it first.", code="index_not_built"
            )
        if commit_sha and manifest.get("commit_sha") and manifest["commit_sha"] != commit_sha:
            raise IndexUnavailableError(
                "The search index was built from an older commit. Re-index the repository.",
                code="index_out_of_date",
            )

        # The cached index depends on the embedding model, because a dense index built
        # with another model is dropped on load.
        key = (repository_id, f"{manifest.get('built_at')}|{embeddings.name}|{embeddings.model_id}")
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached

        index = self._load_from_disk(repository_id, manifest, embeddings, settings)
        with self._lock:
            self._cache[key] = index
            self._cache.move_to_end(key)
            while len(self._cache) > _CACHE_SIZE:
                self._cache.popitem(last=False)
        return index

    def _load_from_disk(
        self,
        repository_id: uuid.UUID,
        manifest: dict[str, Any],
        embeddings: EmbeddingProvider,
        settings: Settings,
    ) -> RetrievalIndex:
        directory = self.path_for(repository_id)
        try:
            chunk_ids = json.loads((directory / CHUNK_IDS_FILENAME).read_text(encoding="utf-8"))
            bm25 = BM25Index.load(directory)
        except (OSError, ValueError) as exc:
            raise IndexUnavailableError(
                "The search index is unreadable. Re-index the repository.", code="index_unreadable"
            ) from exc

        vectors = None
        dense = manifest.get("dense") or {}
        if dense.get("status") == "ready":
            # A dense index only means something for the model that produced it.
            if (
                dense.get("model") != embeddings.model_id
                or dense.get("provider") != embeddings.name
            ):
                logger.info(
                    "dense index built with a different embedding model",
                    extra={
                        "index_model": dense.get("model"),
                        "configured_model": embeddings.model_id,
                    },
                )
            else:
                vectors = load_vector_store(settings, directory)
        logger.debug(
            "retrieval index loaded",
            extra={"repository_id": str(repository_id), "chunks": len(chunk_ids)},
        )
        return RetrievalIndex(
            repository_id=repository_id,
            chunk_ids=chunk_ids,
            bm25=bm25,
            vectors=vectors,
            manifest=manifest,
        )

    def _invalidate(self, repository_id: uuid.UUID) -> None:
        with self._lock:
            for key in [key for key in self._cache if key[0] == repository_id]:
                del self._cache[key]


def build_manifest(
    *,
    repository_id: uuid.UUID,
    commit_sha: str | None,
    chunk_count: int,
    bm25: dict[str, Any],
    dense: dict[str, Any],
) -> dict[str, Any]:
    return {
        "repository_id": str(repository_id),
        "commit_sha": commit_sha,
        "chunk_count": chunk_count,
        "chunker_version": CHUNKER_VERSION,
        "bm25": bm25,
        "dense": dense,
        "built_at": datetime.now(UTC).isoformat(),
    }
