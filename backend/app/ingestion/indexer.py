"""The ingestion pipeline that runs in the background for one IndexingJob.

    QUEUED → CLONING → ANALYZING → INDEXING → PARSING → EMBEDDING → COMPLETED
                   ↘          ↘          ↘         ↘           ↘ FAILED

Everything happens in a temporary directory; only when every stage succeeds is
the new checkout moved into place and the file index and code analysis replaced in
one database transaction. A failed re-index therefore leaves the previous successful
index (checkout, commit SHA, metadata, file rows, symbols, dependency graph) untouched.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.analysis.registry import default_registry
from app.analysis.repository import RepositoryAnalysis, analyze_repository
from app.ingestion.errors import (
    IngestionCancelledError,
    IngestionError,
    RepositoryLimitExceededError,
)
from app.ingestion.git import CommitInfo
from app.ingestion.scanner import (
    IndexedFile,
    ScanResult,
    index_file,
    read_text_file,
    scan_repository,
)
from app.ingestion.sources import parse_github_url, validate_local_repository_path
from app.ingestion.storage import directory_size_bytes
from app.jobs.base import JobContext
from app.models.indexing_job import IndexingJob, JobStatus
from app.models.repository import RepositorySourceType, RepositoryStatus
from app.repositories import (
    CodeAnalysisRepository,
    CodeChunkRepository,
    IndexingJobRepository,
    RepositoryFileRepository,
)
from app.retrieval.builder import RetrievalBuild, build_retrieval_index
from app.retrieval.chunking import Chunk, ChunkingConfig, CodeChunker, symbol_records
from app.schemas.repository import LanguageStat, LastCommit, RepositoryMetadata

logger = logging.getLogger(__name__)

_PROGRESS_INTERVAL_SECONDS = 1.0
_UNEXPECTED_FAILURE_MESSAGE = "Unexpected error while indexing. See the server logs for details."
INTERRUPTED_MESSAGE = IngestionCancelledError().message


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _Source:
    """Plain values copied out of the ORM object before the long-running work starts."""

    repository_id: uuid.UUID
    source_type: RepositorySourceType
    url: str
    branch: str


class RepositoryIndexer:
    def __init__(self, context: JobContext) -> None:
        self.context = context
        self.settings = context.settings

    def run(self, job_id: uuid.UUID) -> None:
        source = self._start(job_id)
        if source is None:
            return

        checkout: Path | None = None
        retrieval: RetrievalBuild | None = None
        try:
            checkout = self.context.storage.create_temp_dir(source.repository_id)
            commit_sha = self._clone(source, checkout)

            self._update(job_id, stage=RepositoryStatus.ANALYZING, commit_sha=commit_sha)
            scan = scan_repository(
                checkout,
                max_files=self.settings.max_repository_files,
                max_file_bytes=self.settings.max_indexed_file_size_kb * 1024,
            )
            last_commit = self.context.git.last_commit(checkout)
            self._check_cancelled()

            self._update(
                job_id,
                stage=RepositoryStatus.INDEXING,
                files_total=len(scan.indexable_files),
            )
            indexed = self._index_files(job_id, checkout, scan)

            code_analysis = self._analyze_code(job_id, checkout, indexed, scan)

            retrieval = self._build_search_index(
                job_id, source.repository_id, commit_sha, checkout, indexed, code_analysis
            )

            final_path = self.context.storage.install(source.repository_id, checkout)
            checkout = None
            metadata = _build_metadata(scan, indexed, last_commit, code_analysis, retrieval)
            self._complete(
                job_id, final_path, commit_sha, indexed, metadata, code_analysis, retrieval
            )
            logger.info(
                "repository indexed",
                extra={
                    "repository_id": str(source.repository_id),
                    "commit_sha": commit_sha,
                    "indexed_files": len(indexed),
                    "symbols": len(code_analysis.symbols),
                    "relationships": len(code_analysis.relationships),
                    "chunks": len(retrieval.chunk_rows) if retrieval else 0,
                },
            )
        except Exception as exc:
            if checkout is not None:
                self._discard(checkout)
            if retrieval is not None:
                self._discard_index(retrieval.directory)
            self._fail(job_id, exc)

    # -- stages ------------------------------------------------------------

    def _start(self, job_id: uuid.UUID) -> _Source | None:
        with self.context.session_factory() as session:
            job = session.get(IndexingJob, job_id)
            if job is None or job.status != JobStatus.QUEUED:
                # Already handled (e.g. a message delivered twice) or deleted.
                logger.warning("indexing job skipped", extra={"job_id": str(job_id)})
                return None
            repository = job.repository
            job.status = JobStatus.RUNNING
            job.started_at = _now()
            job.stage = repository.status = RepositoryStatus.CLONING
            repository.status_message = None
            session.commit()
            return _Source(repository.id, repository.source_type, repository.url, job.branch)

    def _clone(self, source: _Source, checkout: Path) -> str:
        # Re-validate the stored source: settings may have changed since it was added.
        if source.source_type is RepositorySourceType.GITHUB:
            clone_source = parse_github_url(source.url).clone_url
        else:
            if not self.settings.local_repositories_enabled:
                raise IngestionError(
                    "Local repositories are disabled in this environment.",
                    code="local_repositories_disabled",
                )
            clone_source = str(
                validate_local_repository_path(source.url, self.settings.local_repository_roots)
            )

        commit_sha = self.context.git.clone(
            clone_source, source.branch, checkout, cancel_event=self.context.cancel_event
        )
        max_bytes = self.settings.max_repository_size_mb * 1024 * 1024
        if directory_size_bytes(checkout) > max_bytes:
            raise RepositoryLimitExceededError(
                f"Repository is larger than the {self.settings.max_repository_size_mb} MB limit."
            )
        return commit_sha

    def _index_files(
        self, job_id: uuid.UUID, checkout: Path, scan: ScanResult
    ) -> list[IndexedFile]:
        indexed: list[IndexedFile] = []
        last_report = time.monotonic()
        for position, scanned in enumerate(scan.indexable_files, start=1):
            if result := index_file(checkout, scanned):
                indexed.append(result)
            if time.monotonic() - last_report >= _PROGRESS_INTERVAL_SECONDS:
                self._check_cancelled()
                self._update(job_id, files_processed=position)
                last_report = time.monotonic()
        return indexed

    def _analyze_code(
        self, job_id: uuid.UUID, checkout: Path, indexed: list[IndexedFile], scan: ScanResult
    ) -> RepositoryAnalysis:
        """PARSING: extract symbols and imports and build the dependency graph."""
        paths = [item.path for item in indexed]
        registry = default_registry()
        parseable = sum(1 for path in paths if registry.analyzer_for(path) is not None)
        self._update(
            job_id, stage=RepositoryStatus.PARSING, files_total=parseable, files_processed=0
        )
        last_report = time.monotonic()

        def on_progress(done: int, _total: int) -> None:
            nonlocal last_report
            if time.monotonic() - last_report >= _PROGRESS_INTERVAL_SECONDS:
                self._update(job_id, files_processed=done)  # also raises if cancelled
                last_report = time.monotonic()

        return analyze_repository(
            checkout,
            paths,
            max_file_bytes=self.settings.max_parsed_file_size_kb * 1024,
            known_paths=scan.all_paths,
            registry=registry,
            on_progress=on_progress,
        )

    def _build_search_index(
        self,
        job_id: uuid.UUID,
        repository_id: uuid.UUID,
        commit_sha: str,
        checkout: Path,
        indexed: list[IndexedFile],
        code_analysis: RepositoryAnalysis,
    ) -> RetrievalBuild | None:
        """EMBEDDING: chunk the repository and build the BM25 and dense indexes."""
        if not self.settings.retrieval_enabled:
            return None
        chunks = self._chunk_repository(repository_id, checkout, indexed, code_analysis)
        self._update(
            job_id, stage=RepositoryStatus.EMBEDDING, files_total=len(chunks), files_processed=0
        )
        last_report = time.monotonic()

        def on_progress(done: int, _total: int) -> None:
            nonlocal last_report
            if time.monotonic() - last_report >= _PROGRESS_INTERVAL_SECONDS:
                self._update(job_id, files_processed=done)  # also raises if cancelled
                last_report = time.monotonic()

        return build_retrieval_index(
            repository_id=repository_id,
            commit_sha=commit_sha,
            chunks=chunks,
            settings=self.settings,
            embeddings=self.context.embeddings,
            index_store=self.context.index_store,
            on_progress=on_progress,
        )

    def _chunk_repository(
        self,
        repository_id: uuid.UUID,
        checkout: Path,
        indexed: list[IndexedFile],
        code_analysis: RepositoryAnalysis,
    ) -> list[Chunk]:
        """Structure-aware chunks for parsed files, then documentation and other text."""
        chunker = CodeChunker(
            repository_id,
            ChunkingConfig(
                max_lines=self.settings.chunk_max_lines,
                max_chars=self.settings.chunk_max_chars,
                overlap_lines=self.settings.chunk_overlap_lines,
                min_lines=self.settings.chunk_min_lines,
            ),
        )
        symbols_by_file: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for symbol in code_analysis.symbols:
            symbols_by_file.setdefault(symbol["file_id"], []).append(symbol)

        chunks: list[Chunk] = []
        analysed: set[str] = set()
        for file_row in code_analysis.files:
            content = read_text_file(
                checkout, file_row["path"], max_bytes=self.settings.max_parsed_file_size_kb * 1024
            )
            if content is None:
                continue
            analysed.add(file_row["path"])
            chunks.extend(
                chunker.chunk_source_file(
                    file_row["path"],
                    file_row["language"],
                    content.decode("utf-8", errors="replace"),
                    symbol_records(symbols_by_file.get(file_row["id"], [])),
                )
            )

        for item in indexed:
            if item.path in analysed or not CodeChunker.should_chunk(item.path, item.language):
                continue
            content = read_text_file(
                checkout, item.path, max_bytes=self.settings.max_indexed_file_size_kb * 1024
            )
            if content is None:
                continue
            chunks.extend(
                chunker.chunk_text_file(
                    item.path, item.language or "Text", content.decode("utf-8", errors="replace")
                )
            )
        return chunks

    def _repository_id(self, job_id: uuid.UUID) -> uuid.UUID:
        with self.context.session_factory() as session:
            return self._get_job(session, job_id).repository_id

    def _complete(
        self,
        job_id: uuid.UUID,
        final_path: Path,
        commit_sha: str,
        indexed: list[IndexedFile],
        metadata: RepositoryMetadata,
        code_analysis: RepositoryAnalysis,
        retrieval: RetrievalBuild | None,
    ) -> None:
        if retrieval is not None:
            self.context.index_store.install(self._repository_id(job_id), retrieval.directory)
        with self.context.session_factory() as session:
            job = self._get_job(session, job_id)
            repository = job.repository
            RepositoryFileRepository(session).replace_for_repository(
                repository.id,
                (
                    {
                        "path": item.path,
                        "language": item.language,
                        "size_bytes": item.size_bytes,
                        "line_count": item.line_count,
                        "content_sha256": item.content_sha256,
                    }
                    for item in indexed
                ),
            )
            CodeAnalysisRepository(session).replace_for_repository(repository.id, code_analysis)
            CodeChunkRepository(session).replace_for_repository(
                repository.id, retrieval.chunk_rows if retrieval else []
            )
            finished = _now()
            repository.commit_sha = commit_sha
            repository.local_path = str(final_path)
            repository.repo_metadata = metadata.model_dump(mode="json")
            repository.last_indexed_at = finished
            repository.status = RepositoryStatus.COMPLETED
            repository.status_message = None
            job.status = JobStatus.SUCCEEDED
            job.stage = RepositoryStatus.COMPLETED
            job.files_processed = job.files_total or 0
            job.finished_at = finished
            session.commit()

    def _fail(self, job_id: uuid.UUID, exc: Exception) -> None:
        if isinstance(exc, IngestionError):
            message = exc.message
            logger.info("indexing failed", extra={"job_id": str(job_id), "reason": exc.code})
        else:
            message = _UNEXPECTED_FAILURE_MESSAGE
            logger.exception("indexing crashed", extra={"job_id": str(job_id)})
        try:
            with self.context.session_factory() as session:
                job = session.get(IndexingJob, job_id)
                if job is None:
                    return
                job.status = JobStatus.FAILED
                job.error_message = message
                job.finished_at = _now()
                job.repository.status = RepositoryStatus.FAILED
                job.repository.status_message = message
                session.commit()
        except Exception:
            logger.exception("could not record indexing failure", extra={"job_id": str(job_id)})

    # -- helpers -----------------------------------------------------------

    def _update(
        self,
        job_id: uuid.UUID,
        *,
        stage: RepositoryStatus | None = None,
        commit_sha: str | None = None,
        files_total: int | None = None,
        files_processed: int | None = None,
    ) -> None:
        self._check_cancelled()
        with self.context.session_factory() as session:
            job = self._get_job(session, job_id)
            if stage is not None:
                job.stage = job.repository.status = stage
            if commit_sha is not None:
                job.commit_sha = commit_sha
            if files_total is not None:
                job.files_total = files_total
            if files_processed is not None:
                job.files_processed = files_processed
            session.commit()

    @staticmethod
    def _get_job(session: Session, job_id: uuid.UUID) -> IndexingJob:
        job = session.get(IndexingJob, job_id)
        if job is None:
            raise IngestionError("The indexing job no longer exists.", code="job_missing")
        return job

    def _check_cancelled(self) -> None:
        if self.context.cancel_event.is_set():
            raise IngestionCancelledError()

    def _discard(self, checkout: Path) -> None:
        try:
            self.context.storage.discard(checkout)
        except Exception:
            logger.exception("could not remove temporary checkout", extra={"path": str(checkout)})

    def _discard_index(self, directory: Path) -> None:
        try:
            self.context.index_store.discard(directory)
        except Exception:
            logger.exception("could not remove temporary index", extra={"path": str(directory)})


def _build_metadata(
    scan: ScanResult,
    indexed: list[IndexedFile],
    last_commit: CommitInfo,
    code_analysis: RepositoryAnalysis,
    retrieval: RetrievalBuild | None,
) -> RepositoryMetadata:
    skipped = dict(scan.skipped)
    binary_or_unreadable = len(scan.indexable_files) - len(indexed)
    if binary_or_unreadable:
        skipped["binary_or_unreadable"] = binary_or_unreadable
    return RepositoryMetadata(
        total_files=scan.total_files,
        total_size_bytes=scan.total_size_bytes,
        indexed_files=len(indexed),
        skipped_files=skipped,
        primary_language=scan.primary_language,
        languages=[LanguageStat(**item) for item in scan.language_breakdown()],
        manifests=scan.manifests,
        readme_path=scan.readme_path,
        license_path=scan.license_path,
        last_commit=LastCommit(
            sha=last_commit.sha,
            author_name=last_commit.author_name,
            authored_at=last_commit.authored_at,
            subject=last_commit.subject,
        ),
        analysis=code_analysis.summary,
        retrieval=retrieval.summary if retrieval else None,
    )


def recover_interrupted_jobs(context: JobContext) -> int:
    """Mark jobs left queued/running by a previous process as failed.

    With the in-process thread queue, a job cannot survive a restart, so anything
    still active at startup was interrupted. Returns the number of jobs recovered.
    """
    with context.session_factory() as session:
        jobs = IndexingJobRepository(session).list_active()
        for job in jobs:
            job.status = JobStatus.FAILED
            job.error_message = INTERRUPTED_MESSAGE
            job.finished_at = _now()
            if job.repository.status in RepositoryStatus.active():
                job.repository.status = RepositoryStatus.FAILED
                job.repository.status_message = INTERRUPTED_MESSAGE
        session.commit()
    context.storage.clear_temp()
    context.index_store.clear_temp()
    if jobs:
        logger.warning("recovered interrupted indexing jobs", extra={"count": len(jobs)})
    return len(jobs)
