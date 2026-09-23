import uuid
from collections.abc import Sequence

from sqlalchemy import Select, select

from app.models.repository import Repository, RepositoryStatus
from app.repositories.base import BaseRepository


class RepositoryRepository(BaseRepository[Repository]):
    model = Repository

    def list_filtered(
        self,
        *,
        project_id: uuid.UUID | None = None,
        status: RepositoryStatus | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[Repository], int]:
        statement = self._filtered(project_id, status)
        return self._paginate(statement, offset=offset, limit=limit), self._count(statement)

    def get_by_project_and_url(self, project_id: uuid.UUID, url: str) -> Repository | None:
        return self.session.scalar(
            select(Repository).where(Repository.project_id == project_id, Repository.url == url)
        )

    def delete(self, repository: Repository) -> None:
        self.session.delete(repository)
        self.session.flush()

    @staticmethod
    def _filtered(
        project_id: uuid.UUID | None, status: RepositoryStatus | None
    ) -> Select[tuple[Repository]]:
        statement = select(Repository)
        if project_id is not None:
            statement = statement.where(Repository.project_id == project_id)
        if status is not None:
            statement = statement.where(Repository.status == status)
        return statement
