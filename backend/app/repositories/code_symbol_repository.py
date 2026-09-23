import uuid
from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.analysis.results import SymbolKind
from app.models.code import CodeFile, CodeSymbol


class CodeSymbolRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_file(self, file_id: uuid.UUID) -> Sequence[CodeSymbol]:
        return self.session.scalars(
            select(CodeSymbol)
            .where(CodeSymbol.file_id == file_id)
            .order_by(CodeSymbol.start_line, CodeSymbol.end_line.desc())
        ).all()

    def search(
        self,
        repository_id: uuid.UUID,
        *,
        query: str | None = None,
        kind: SymbolKind | None = None,
        path_prefix: str | None = None,
        exported_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[tuple[CodeSymbol, str]], int]:
        """Symbols with their file path; `query` matches (qualified) names, case-insensitively."""
        statement: Select = (
            select(CodeSymbol, CodeFile.path)
            .join(CodeFile, CodeFile.id == CodeSymbol.file_id)
            .where(CodeSymbol.repository_id == repository_id)
        )
        if query:
            escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            statement = statement.where(
                or_(
                    func.lower(CodeSymbol.name).like(pattern, escape="\\"),
                    func.lower(CodeSymbol.qualified_name).like(pattern, escape="\\"),
                )
            )
        if kind is not None:
            statement = statement.where(CodeSymbol.kind == kind)
        if path_prefix:
            statement = statement.where(CodeFile.path.startswith(path_prefix, autoescape=True))
        if exported_only:
            statement = statement.where(CodeSymbol.is_exported.is_(True))

        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        # Exact name matches first, then shorter names, then alphabetical.
        order = [CodeSymbol.name, CodeFile.path, CodeSymbol.start_line]
        if query:
            order = [
                (func.lower(CodeSymbol.name) != query.lower()),
                func.length(CodeSymbol.name),
                *order,
            ]
        rows = self.session.execute(statement.order_by(*order).offset(offset).limit(limit)).all()
        return [(row[0], row[1]) for row in rows], total

    def get(self, repository_id: uuid.UUID, symbol_id: uuid.UUID) -> CodeSymbol | None:
        return self.session.scalar(
            select(CodeSymbol).where(
                CodeSymbol.repository_id == repository_id, CodeSymbol.id == symbol_id
            )
        )

    def by_ids(self, symbol_ids: set[uuid.UUID]) -> dict[uuid.UUID, CodeSymbol]:
        if not symbol_ids:
            return {}
        return {
            symbol.id: symbol
            for symbol in self.session.scalars(
                select(CodeSymbol).where(CodeSymbol.id.in_(symbol_ids))
            )
        }
