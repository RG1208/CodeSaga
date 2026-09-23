from sqlalchemy import select

from app.models.project import Project
from app.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    model = Project

    def get_by_name(self, name: str) -> Project | None:
        return self.session.scalar(select(Project).where(Project.name == name))

    def get_or_create_by_name(self, name: str, *, description: str | None = None) -> Project:
        return self.get_by_name(name) or self.add(Project(name=name, description=description))
