import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
    UpstreamServiceError,
)
from app.ingestion.errors import GitCommandError, GitErrorKind, IngestionError
from app.ingestion.git import GitClient
from app.ingestion.sources import (
    parse_github_url,
    validate_branch_name,
    validate_local_repository_path,
)
from app.ingestion.storage import RepositoryStorage
from app.jobs.base import JobQueue
from app.jobs.registry import INDEX_REPOSITORY_JOB
from app.models.indexing_job import IndexingJob, JobStatus
from app.models.project import Project
from app.models.repository import Repository, RepositorySourceType, RepositoryStatus
from app.repositories import IndexingJobRepository, ProjectRepository, RepositoryRepository
from app.retrieval.index_store import RepositoryIndexStore
from app.schemas.repository import RepositoryCreate

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_NAME = "Default"


def to_app_error(exc: IngestionError) -> AppError:
    """Translate an ingestion (domain) error into an HTTP-aware application error."""
    if isinstance(exc, GitCommandError):
        if exc.kind in (GitErrorKind.NETWORK, GitErrorKind.TIMEOUT):
            return UpstreamServiceError(exc.message, code=exc.code)
        if exc.kind is GitErrorKind.UNAVAILABLE:
            return AppError(exc.message, code=exc.code)
    return UnprocessableError(exc.message, code=exc.code)


class RepositoryService:
    """Registering repositories, starting indexing, and removing them.

    The heavy work (clone, analyse, index) never runs here: `start_indexing`
    records a job and hands it to the job queue.
    """

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        git: GitClient,
        storage: RepositoryStorage,
        index_store: RepositoryIndexStore,
        jobs: JobQueue,
    ) -> None:
        self.session = session
        self.settings = settings
        self.git = git
        self.storage = storage
        self.index_store = index_store
        self.job_queue = jobs
        self.repositories = RepositoryRepository(session)
        self.projects = ProjectRepository(session)
        self.jobs = IndexingJobRepository(session)

    # -- queries -----------------------------------------------------------

    def list_repositories(
        self,
        *,
        project_id: uuid.UUID | None,
        status: RepositoryStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[Sequence[Repository], int]:
        return self.repositories.list_filtered(
            project_id=project_id, status=status, offset=offset, limit=limit
        )

    def get_repository(self, repository_id: uuid.UUID) -> Repository:
        repository = self.repositories.get(repository_id)
        if repository is None:
            raise NotFoundError(f"Repository {repository_id} not found.")
        return repository

    def get_latest_job(self, repository_id: uuid.UUID) -> IndexingJob | None:
        return self.jobs.get_latest_for_repository(repository_id)

    # -- commands ----------------------------------------------------------

    def create_repository(self, data: RepositoryCreate) -> Repository:
        project = self._resolve_project(data.project_id)
        try:
            if data.source_type is RepositorySourceType.GITHUB:
                ref = parse_github_url(data.url)
                url, owner, default_name, git_source = (
                    ref.canonical_url,
                    ref.owner,
                    ref.name,
                    ref.clone_url,
                )
            else:
                if not self.settings.local_repositories_enabled:
                    raise ForbiddenError(
                        "Local repositories can only be added in development mode.",
                        code="local_repositories_disabled",
                    )
                path = validate_local_repository_path(
                    data.url, self.settings.local_repository_roots
                )
                url, owner, default_name, git_source = str(path), None, path.name, str(path)
            branch = validate_branch_name(data.branch) if data.branch else None

            if self.repositories.get_by_project_and_url(project.id, url) is not None:
                raise ConflictError(
                    "This repository is already registered in the project.",
                    code="repository_exists",
                )
            # Confirms the repository exists and is public, and resolves branch info.
            remote = self.git.resolve_remote(git_source, branch)
        except IngestionError as exc:
            raise to_app_error(exc) from exc

        repository = self.repositories.add(
            Repository(
                project_id=project.id,
                name=data.name or default_name,
                owner=owner,
                url=url,
                source_type=data.source_type,
                default_branch=remote.default_branch,
                branch=remote.branch,
                status=RepositoryStatus.PENDING,
            )
        )
        self.session.commit()
        self.session.refresh(repository)
        logger.info(
            "repository registered",
            extra={"repository_id": str(repository.id), "source_type": data.source_type.value},
        )
        return repository

    def start_indexing(self, repository_id: uuid.UUID) -> IndexingJob:
        repository = self.get_repository(repository_id)
        if self.jobs.get_active_for_repository(repository.id) is not None:
            raise ConflictError(
                "Indexing is already in progress for this repository.",
                code="indexing_in_progress",
            )

        job = self.jobs.add(
            IndexingJob(
                repository_id=repository.id,
                branch=repository.branch,
                status=JobStatus.QUEUED,
                stage=RepositoryStatus.QUEUED,
            )
        )
        repository.status = RepositoryStatus.QUEUED
        repository.status_message = None
        # Commit BEFORE enqueueing so the worker can always see the job row.
        self.session.commit()

        try:
            self.job_queue.enqueue(INDEX_REPOSITORY_JOB, {"job_id": str(job.id)})
        except Exception as exc:
            logger.exception("could not enqueue indexing job", extra={"job_id": str(job.id)})
            job.status = JobStatus.FAILED
            job.error_message = repository.status_message = "Could not start background job."
            repository.status = RepositoryStatus.FAILED
            self.session.commit()
            raise AppError("Could not start indexing. Try again later.") from exc

        # An inline queue may already have finished the job; return fresh state.
        self.session.refresh(job)
        return job

    def delete_repository(self, repository_id: uuid.UUID) -> None:
        repository = self.get_repository(repository_id)
        if self.jobs.get_active_for_repository(repository.id) is not None:
            raise ConflictError(
                "Cannot delete a repository while it is being indexed.",
                code="indexing_in_progress",
            )
        self.repositories.delete(repository)
        self.session.commit()

        for label, remove in (
            ("checkout", self.storage.remove),
            ("search index", self.index_store.remove),
        ):
            try:
                remove(repository_id)
            except Exception:
                # The database row is gone; orphaned files are harmless but worth logging.
                logger.exception(
                    f"could not remove repository {label}",
                    extra={"repository_id": str(repository_id)},
                )
        logger.info("repository deleted", extra={"repository_id": str(repository_id)})

    # -- helpers -----------------------------------------------------------

    def _resolve_project(self, project_id: uuid.UUID | None) -> Project:
        if project_id is None:
            return self.projects.get_or_create_by_name(
                DEFAULT_PROJECT_NAME, description="Repositories added without a project."
            )
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found.")
        return project
