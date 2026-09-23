"""API contract for source-code analysis (files, symbols, imports, dependencies)."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.analysis.results import Confidence, ParseStatus, RelationshipType, SymbolKind
from app.schemas.common import ORMSchema


class CodeFileSummary(BaseModel):
    """One file in the repository explorer (every indexed text file)."""

    path: str
    language: str | None = Field(description="Language detected by file extension.")
    size_bytes: int
    line_count: int
    analyzed: bool = Field(description="True if the file was parsed into symbols.")
    parser: str | None = Field(
        default=None, description="Analyzer used: python, javascript, typescript, tsx."
    )
    parse_status: ParseStatus | None = None
    symbol_count: int = 0
    import_count: int = 0


class FileContent(BaseModel):
    path: str
    language: str | None
    size_bytes: int
    line_count: int
    content: str


class ParameterRead(BaseModel):
    name: str
    type: str | None = None
    default: str | None = None
    kind: str = "positional"
    optional: bool = False


class CodeSymbolRead(ORMSchema):
    # Read `metadata` from the ORM attribute `symbol_metadata`, but also accept it by name.
    model_config = ConfigDict(from_attributes=True, validate_by_name=True, validate_by_alias=True)

    id: uuid.UUID
    file_id: uuid.UUID
    parent_symbol_id: uuid.UUID | None
    name: str
    qualified_name: str
    kind: SymbolKind
    start_line: int
    end_line: int
    signature: str | None
    docstring: str | None
    return_type: str | None
    is_exported: bool
    is_async: bool
    parameters: list[ParameterRead]
    decorators: list[str]
    metadata: dict[str, Any] = Field(validation_alias="symbol_metadata")


class SymbolSearchResult(CodeSymbolRead):
    file_path: str


class CodeImportRead(ORMSchema):
    id: uuid.UUID
    module: str
    kind: str
    names: list[dict[str, str]]
    start_line: int
    end_line: int
    is_type_only: bool
    resolution_status: str = Field(description="resolved | external | unresolved")
    resolved_path: str | None
    metadata: dict[str, Any] = Field(validation_alias="import_metadata")


class FileDependency(BaseModel):
    """A file at the other end of an import edge."""

    relationship_id: uuid.UUID
    path: str
    confidence: Confidence
    weight: int
    specifiers: list[str]


class CodeFileDetail(BaseModel):
    path: str
    language: str
    size_bytes: int
    line_count: int
    content_sha256: str
    parse_status: ParseStatus
    symbol_count: int
    import_count: int
    metadata: dict[str, Any]
    symbols: list[CodeSymbolRead]
    imports: list[CodeImportRead]
    depends_on: list[FileDependency] = Field(description="Files this file imports.")
    imported_by: list[FileDependency] = Field(description="Files that import this file.")


class SymbolReference(BaseModel):
    id: uuid.UUID
    name: str
    qualified_name: str
    kind: SymbolKind
    start_line: int
    end_line: int


class RelationshipRead(BaseModel):
    id: uuid.UUID
    relationship_type: RelationshipType
    confidence: Confidence
    weight: int
    source_path: str
    target_path: str
    source_symbol: SymbolReference | None
    target_symbol: SymbolReference | None
    metadata: dict[str, Any]
