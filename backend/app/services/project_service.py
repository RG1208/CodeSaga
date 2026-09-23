import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.project import Project
from app.repositories import ProjectRepository, UserRepository
from app.schemas.project import ProjectCreate

logger = logging.getLogger(__name__)


class ProjectService:
    """Business rules for projects. Owns the transaction (commit) boundary."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.users = UserRepository(session)

    def list_projects(self, *, offset: int, limit: int) -> tuple[Sequence[Project], int]:
        return self.projects.list(offset=offset, limit=limit), self.projects.count()

    def get_project(self, project_id: uuid.UUID) -> Project:
        project = self.projects.get(project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found.")
        return project

    def create_project(self, data: ProjectCreate) -> Project:
        if self.projects.get_by_name(data.name) is not None:
            raise ConflictError(f"A project named '{data.name}' already exists.")
        if data.owner_id is not None and self.users.get(data.owner_id) is None:
            raise NotFoundError(f"User {data.owner_id} not found.")

        project = self.projects.add(Project(**data.model_dump()))
        self.session.commit()
        self.session.refresh(project)
        logger.info("project created", extra={"project_id": str(project.id)})
        return project
