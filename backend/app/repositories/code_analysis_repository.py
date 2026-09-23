import uuid

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.analysis.repository import RepositoryAnalysis
from app.models.code import CodeFile, CodeImport, CodeRelationship, CodeSymbol

_BATCH_SIZE = 1000


class CodeAnalysisRepository:
    """Bulk replacement of a repository's analysis rows (runs inside the caller's transaction)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_for_repository(
        self, repository_id: uuid.UUID, analysis: RepositoryAnalysis
    ) -> None:
        self.delete_for_repository(repository_id)
        # Insert order respects foreign keys: files → symbols (parents first) → imports → edges.
        for model, rows in (
            (CodeFile, analysis.files),
            (CodeSymbol, analysis.symbols),
            (CodeImport, analysis.imports),
            (CodeRelationship, analysis.relationships),
        ):
            for start in range(0, len(rows), _BATCH_SIZE):
                batch = [
                    {"repository_id": repository_id, **row}
                    for row in rows[start : start + _BATCH_SIZE]
                ]
                self.session.execute(insert(model), batch)

    def delete_for_repository(self, repository_id: uuid.UUID) -> None:
        for model in (CodeRelationship, CodeImport, CodeSymbol, CodeFile):
            self.session.execute(delete(model).where(model.repository_id == repository_id))
