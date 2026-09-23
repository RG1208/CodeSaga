import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import PaginationDep, RepositoryServiceDep
from app.models.repository import RepositoryStatus
from app.schemas.common import ErrorResponse, Page
from app.schemas.repository import (
    IndexingJobRead,
    RepositoryCreate,
    RepositoryDetail,
    RepositoryRead,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])

_NOT_FOUND = {404: {"model": ErrorResponse}}
_CONFLICT = {409: {"model": ErrorResponse}}


@router.get("", response_model=Page[RepositoryRead])
def list_repositories(
    service: RepositoryServiceDep,
    pagination: PaginationDep,
    project_id: Annotated[uuid.UUID | None, Query(description="Filter by project.")] = None,
    status_filter: Annotated[
        RepositoryStatus | None, Query(alias="status", description="Filter by status.")
    ] = None,
) -> Page[RepositoryRead]:
    repositories, total = service.list_repositories(
        project_id=project_id,
        status=status_filter,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page(
        items=[RepositoryRead.model_validate(repository) for repository in repositories],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post(
    "",
    response_model=RepositoryRead,
    status_code=status.HTTP_201_CREATED,
    responses={
        **_NOT_FOUND,
        **_CONFLICT,
        403: {"model": ErrorResponse, "description": "Local repositories are disabled."},
        422: {"model": ErrorResponse, "description": "Invalid URL/path, or not accessible."},
        502: {"model": ErrorResponse, "description": "GitHub could not be reached."},
    },
)
def add_repository(payload: RepositoryCreate, service: RepositoryServiceDep) -> RepositoryRead:
    """Validate a GitHub URL or local path and register it (status `pending`).

    The repository's existence and branch are checked with `git ls-remote`; nothing
    is cloned until indexing is started.
    """
    return RepositoryRead.model_validate(service.create_repository(payload))


@router.get("/{repository_id}", response_model=RepositoryDetail, responses=_NOT_FOUND)
def get_repository(repository_id: uuid.UUID, service: RepositoryServiceDep) -> RepositoryDetail:
    """Repository metadata plus its latest indexing job (for progress)."""
    repository = service.get_repository(repository_id)
    detail = RepositoryDetail.model_validate(repository)
    latest_job = service.get_latest_job(repository.id)
    detail.latest_job = IndexingJobRead.model_validate(latest_job) if latest_job else None
    return detail


@router.post(
    "/{repository_id}/index",
    response_model=IndexingJobRead,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_NOT_FOUND, **_CONFLICT},
)
def start_indexing(repository_id: uuid.UUID, service: RepositoryServiceDep) -> IndexingJobRead:
    """Queue a clone → analyze → index run. Poll `GET /repositories/{id}` for progress."""
    return IndexingJobRead.model_validate(service.start_indexing(repository_id))


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={**_NOT_FOUND, **_CONFLICT},
)
def delete_repository(repository_id: uuid.UUID, service: RepositoryServiceDep) -> Response:
    """Delete the repository, its index and its checkout on disk."""
    service.delete_repository(repository_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
