import uuid

from fastapi import APIRouter, status

from app.api.deps import PaginationDep, ProjectServiceDep
from app.schemas.common import ErrorResponse, Page
from app.schemas.project import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=Page[ProjectRead])
def list_projects(service: ProjectServiceDep, pagination: PaginationDep) -> Page[ProjectRead]:
    projects, total = service.list_projects(offset=pagination.offset, limit=pagination.limit)
    return Page(
        items=[ProjectRead.model_validate(project) for project in projects],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_project(payload: ProjectCreate, service: ProjectServiceDep) -> ProjectRead:
    return ProjectRead.model_validate(service.create_project(payload))


@router.get("/{project_id}", response_model=ProjectRead, responses={404: {"model": ErrorResponse}})
def get_project(project_id: uuid.UUID, service: ProjectServiceDep) -> ProjectRead:
    return ProjectRead.model_validate(service.get_project(project_id))
