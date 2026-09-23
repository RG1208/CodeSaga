import uuid
from collections.abc import Sequence
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from app.analysis.results import Confidence, RelationshipType, SymbolKind
from app.core.config import Settings
from app.core.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.ingestion.errors import UnsafePathError
from app.ingestion.scanner import count_lines, read_text_file
from app.ingestion.storage import RepositoryStorage, ensure_within
from app.models.code import CodeFile, CodeRelationship, CodeSymbol
from app.models.repository import Repository
from app.repositories import (
    CodeFileRepository,
    CodeRelationshipRepository,
    CodeSymbolRepository,
    RepositoryRepository,
)
from app.schemas.code import (
    CodeFileDetail,
    CodeFileSummary,
    CodeImportRead,
    CodeSymbolRead,
    FileContent,
    FileDependency,
    RelationshipRead,
    SymbolReference,
    SymbolSearchResult,
)


def validate_relative_path(path: str) -> str:
    """Reject anything that is not a plain relative path before touching the database or disk."""
    if not path or len(path) > 1024 or "\x00" in path or "\\" in path:
        raise UnprocessableError("Invalid file path.", code="invalid_path")
    parts = PurePosixPath(path).parts
    if path.startswith("/") or any(part in ("..", ".") for part in parts):
        raise UnprocessableError(
            "File paths must be relative to the repository root.", code="invalid_path"
        )
    return path


class CodeService:
    """Read-only access to a repository's source files, symbols and dependency graph."""

    def __init__(self, session: Session, *, settings: Settings, storage: RepositoryStorage) -> None:
        self.settings = settings
        self.storage = storage
        self.repositories = RepositoryRepository(session)
        self.files = CodeFileRepository(session)
        self.symbols = CodeSymbolRepository(session)
        self.relationships = CodeRelationshipRepository(session)

    # -- files ---------------------------------------------------------------------

    def list_files(
        self,
        repository_id: uuid.UUID,
        *,
        analyzed_only: bool,
        path_prefix: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[CodeFileSummary], int]:
        self._repository(repository_id)
        rows, total = self.files.list_with_index(
            repository_id,
            analyzed_only=analyzed_only,
            path_prefix=path_prefix,
            offset=offset,
            limit=limit,
        )
        items = [
            CodeFileSummary(
                path=indexed.path,
                language=indexed.language,
                size_bytes=indexed.size_bytes,
                line_count=indexed.line_count,
                analyzed=code is not None,
                parser=code.language if code else None,
                parse_status=code.parse_status if code else None,
                symbol_count=code.symbol_count if code else 0,
                import_count=code.import_count if code else 0,
            )
            for indexed, code in rows
        ]
        return items, total

    def file_content(self, repository_id: uuid.UUID, path: str) -> FileContent:
        repository = self._repository(repository_id)
        path = validate_relative_path(path)
        if repository.local_path is None:
            raise ConflictError(
                "This repository has not been indexed yet.", code="repository_not_indexed"
            )
        indexed = self.files.get_indexed_file(repository_id, path)
        if indexed is None:
            raise NotFoundError(
                f"File '{path}' is not in the repository index.", code="file_not_found"
            )

        # The checkout location is derived from the repository id, never from stored text.
        checkout = self.storage.path_for(repository.id)
        try:
            ensure_within(checkout, checkout / path)
        except UnsafePathError as exc:
            raise NotFoundError(
                f"File '{path}' is not in the repository index.", code="file_not_found"
            ) from exc
        content = read_text_file(
            checkout, path, max_bytes=self.settings.max_indexed_file_size_kb * 1024
        )
        if content is None:
            raise UnprocessableError(
                "This file cannot be displayed (binary, too large or missing).",
                code="file_not_viewable",
            )
        return FileContent(
            path=path,
            language=indexed.language,
            size_bytes=len(content),
            line_count=count_lines(content),
            content=content.decode("utf-8", errors="replace"),
        )

    def file_detail(self, repository_id: uuid.UUID, path: str) -> CodeFileDetail:
        code_file = self._code_file(repository_id, path)
        edges = self.relationships.file_edges(code_file.id)
        paths = self.files.paths_by_id(
            {edge.source_file_id for edge in edges} | {edge.target_file_id for edge in edges}
        )

        def dependency(edge: CodeRelationship, other_file_id: uuid.UUID) -> FileDependency:
            return FileDependency(
                relationship_id=edge.id,
                path=paths.get(other_file_id, "?"),
                confidence=edge.confidence,
                weight=edge.weight,
                specifiers=edge.relationship_metadata.get("specifiers", []),
            )

        return CodeFileDetail(
            path=code_file.path,
            language=code_file.language,
            size_bytes=code_file.size_bytes,
            line_count=code_file.line_count,
            content_sha256=code_file.content_sha256,
            parse_status=code_file.parse_status,
            symbol_count=code_file.symbol_count,
            import_count=code_file.import_count,
            metadata=code_file.file_metadata,
            symbols=[
                CodeSymbolRead.model_validate(symbol)
                for symbol in self.symbols.list_for_file(code_file.id)
            ],
            imports=[
                CodeImportRead.model_validate(item)
                for item in self.files.imports_for_file(code_file.id)
            ],
            depends_on=sorted(
                (
                    dependency(edge, edge.target_file_id)
                    for edge in edges
                    if edge.source_file_id == code_file.id
                ),
                key=lambda item: item.path,
            ),
            imported_by=sorted(
                (
                    dependency(edge, edge.source_file_id)
                    for edge in edges
                    if edge.target_file_id == code_file.id
                ),
                key=lambda item: item.path,
            ),
        )

    def file_symbols(self, repository_id: uuid.UUID, path: str) -> list[CodeSymbolRead]:
        code_file = self._code_file(repository_id, path)
        return [
            CodeSymbolRead.model_validate(symbol)
            for symbol in self.symbols.list_for_file(code_file.id)
        ]

    # -- symbols and relationships -----------------------------------------------------

    def search_symbols(
        self,
        repository_id: uuid.UUID,
        *,
        query: str | None,
        kind: SymbolKind | None,
        path_prefix: str | None,
        exported_only: bool,
        offset: int,
        limit: int,
    ) -> tuple[list[SymbolSearchResult], int]:
        self._repository(repository_id)
        rows, total = self.symbols.search(
            repository_id,
            query=query.strip() if query else None,
            kind=kind,
            path_prefix=path_prefix,
            exported_only=exported_only,
            offset=offset,
            limit=limit,
        )
        items = [
            SymbolSearchResult(**CodeSymbolRead.model_validate(symbol).model_dump(), file_path=path)
            for symbol, path in rows
        ]
        return items, total

    def list_relationships(
        self,
        repository_id: uuid.UUID,
        *,
        relationship_type: RelationshipType | None,
        confidence: Confidence | None,
        path: str | None,
        symbol_id: uuid.UUID | None,
        direction: str,
        offset: int,
        limit: int,
    ) -> tuple[list[RelationshipRead], int]:
        self._repository(repository_id)
        file_id = self._code_file(repository_id, path).id if path else None
        if symbol_id is not None and self.symbols.get(repository_id, symbol_id) is None:
            raise NotFoundError(f"Symbol {symbol_id} not found.", code="symbol_not_found")
        edges, total = self.relationships.search(
            repository_id,
            relationship_type=relationship_type,
            confidence=confidence,
            file_id=file_id,
            symbol_id=symbol_id,
            direction=direction,
            offset=offset,
            limit=limit,
        )
        return self._relationship_reads(edges), total

    # -- helpers ---------------------------------------------------------------------------

    def _relationship_reads(self, edges: Sequence[CodeRelationship]) -> list[RelationshipRead]:
        paths = self.files.paths_by_id(
            {e.source_file_id for e in edges} | {e.target_file_id for e in edges}
        )
        symbol_ids = {e.source_symbol_id for e in edges if e.source_symbol_id} | {
            e.target_symbol_id for e in edges if e.target_symbol_id
        }
        symbols = self.symbols.by_ids(symbol_ids)

        def reference(symbol_id: uuid.UUID | None) -> SymbolReference | None:
            symbol: CodeSymbol | None = symbols.get(symbol_id) if symbol_id else None
            if symbol is None:
                return None
            return SymbolReference(
                id=symbol.id,
                name=symbol.name,
                qualified_name=symbol.qualified_name,
                kind=symbol.kind,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
            )

        return [
            RelationshipRead(
                id=edge.id,
                relationship_type=edge.relationship_type,
                confidence=edge.confidence,
                weight=edge.weight,
                source_path=paths.get(edge.source_file_id, "?"),
                target_path=paths.get(edge.target_file_id, "?"),
                source_symbol=reference(edge.source_symbol_id),
                target_symbol=reference(edge.target_symbol_id),
                metadata=edge.relationship_metadata,
            )
            for edge in edges
        ]

    def _repository(self, repository_id: uuid.UUID) -> Repository:
        repository = self.repositories.get(repository_id)
        if repository is None:
            raise NotFoundError(f"Repository {repository_id} not found.")
        return repository

    def _code_file(self, repository_id: uuid.UUID, path: str) -> CodeFile:
        self._repository(repository_id)
        path = validate_relative_path(path)
        code_file = self.files.get_by_path(repository_id, path)
        if code_file is not None:
            return code_file
        if self.files.get_indexed_file(repository_id, path) is not None:
            raise NotFoundError(
                f"'{path}' is indexed but was not parsed (unsupported language or too large).",
                code="file_not_analyzed",
            )
        raise NotFoundError(f"File '{path}' is not in the repository index.", code="file_not_found")
