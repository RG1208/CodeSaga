"""Shared FastAPI dependencies.

Endpoints declare what they need (a settings object, a service) and FastAPI
builds it per request. Tests swap these out via `app.dependency_overrides`
or by passing their own job context/queue to `create_app`.
"""

from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db
from app.jobs.base import JobContext, JobQueue
from app.services.code_service import CodeService
from app.services.project_service import ProjectService
from app.services.repository_service import RepositoryService
from app.services.search_service import SearchService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_job_context(request: Request) -> JobContext:
    return request.app.state.job_context


def get_job_queue(request: Request) -> JobQueue:
    return request.app.state.job_queue


def get_project_service(db: Annotated[Session, Depends(get_db)]) -> ProjectService:
    return ProjectService(db)


def get_repository_service(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[JobContext, Depends(get_job_context)],
    queue: Annotated[JobQueue, Depends(get_job_queue)],
) -> RepositoryService:
    return RepositoryService(
        db,
        settings=context.settings,
        git=context.git,
        storage=context.storage,
        index_store=context.index_store,
        jobs=queue,
    )


def get_code_service(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[JobContext, Depends(get_job_context)],
) -> CodeService:
    return CodeService(db, settings=context.settings, storage=context.storage)


def get_search_service(
    db: Annotated[Session, Depends(get_db)],
    context: Annotated[JobContext, Depends(get_job_context)],
) -> SearchService:
    return SearchService(
        db,
        settings=context.settings,
        index_store=context.index_store,
        embeddings=context.embeddings,
        rerankers=context.rerankers,
    )


class Pagination:
    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100, description="Page size.")] = 20,
        offset: Annotated[int, Query(ge=0, description="Items to skip.")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
PaginationDep = Annotated[Pagination, Depends()]
ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
RepositoryServiceDep = Annotated[RepositoryService, Depends(get_repository_service)]
CodeServiceDep = Annotated[CodeService, Depends(get_code_service)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
