import uuid
from collections.abc import Sequence

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session

from app.models.code import CodeFile, CodeImport
from app.models.repository_file import RepositoryFile


class CodeFileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_with_index(
        self,
        repository_id: uuid.UUID,
        *,
        analyzed_only: bool = False,
        path_prefix: str | None = None,
        offset: int = 0,
        limit: int = 5000,
    ) -> tuple[Sequence[tuple[RepositoryFile, CodeFile | None]], int]:
        """All indexed files, each paired with its analysis row when it was parsed."""
        statement: Select = (
            select(RepositoryFile, CodeFile)
            .outerjoin(
                CodeFile,
                and_(
                    CodeFile.repository_id == RepositoryFile.repository_id,
                    CodeFile.path == RepositoryFile.path,
                ),
            )
            .where(RepositoryFile.repository_id == repository_id)
        )
        if analyzed_only:
            statement = statement.where(CodeFile.id.is_not(None))
        if path_prefix:
            statement = statement.where(
                RepositoryFile.path.startswith(path_prefix, autoescape=True)
            )
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = self.session.execute(
            statement.order_by(RepositoryFile.path).offset(offset).limit(limit)
        ).all()
        return [(row[0], row[1]) for row in rows], total

    def get_indexed_file(self, repository_id: uuid.UUID, path: str) -> RepositoryFile | None:
        return self.session.scalar(
            select(RepositoryFile).where(
                RepositoryFile.repository_id == repository_id, RepositoryFile.path == path
            )
        )

    def get_by_path(self, repository_id: uuid.UUID, path: str) -> CodeFile | None:
        return self.session.scalar(
            select(CodeFile).where(CodeFile.repository_id == repository_id, CodeFile.path == path)
        )

    def paths_by_id(self, file_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not file_ids:
            return {}
        rows = self.session.execute(
            select(CodeFile.id, CodeFile.path).where(CodeFile.id.in_(file_ids))
        )
        return dict(rows.tuples().all())

    def imports_for_file(self, file_id: uuid.UUID) -> Sequence[CodeImport]:
        return self.session.scalars(
            select(CodeImport)
            .where(CodeImport.file_id == file_id)
            .order_by(CodeImport.start_line, CodeImport.module)
        ).all()
