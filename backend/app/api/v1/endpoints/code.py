"""Source-code analysis endpoints: files, content, symbols and the dependency graph."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.analysis.results import Confidence, RelationshipType, SymbolKind
from app.api.deps import CodeServiceDep, PaginationDep
from app.schemas.code import (
    CodeFileDetail,
    CodeFileSummary,
    CodeSymbolRead,
    FileContent,
    RelationshipRead,
    SymbolSearchResult,
)
from app.schemas.common import ErrorResponse, Page

router = APIRouter(prefix="/repositories/{repository_id}", tags=["code"])

_NOT_FOUND = {404: {"model": ErrorResponse}}
PathQuery = Annotated[
    str,
    Query(min_length=1, max_length=1024, description="File path relative to the repository root."),
]


@router.get("/files", response_model=Page[CodeFileSummary], responses=_NOT_FOUND)
def list_files(
    repository_id: uuid.UUID,
    service: CodeServiceDep,
    analyzed: Annotated[bool, Query(description="Only files that were parsed.")] = False,
    path_prefix: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[
        int, Query(ge=1, le=20000, description="Large enough for a whole file tree.")
    ] = 5000,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CodeFileSummary]:
    """Every indexed text file, with analysis status and symbol counts for parsed ones."""
    items, total = service.list_files(
        repository_id, analyzed_only=analyzed, path_prefix=path_prefix, offset=offset, limit=limit
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/files/content",
    response_model=FileContent,
    responses={**_NOT_FOUND, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def get_file_content(
    repository_id: uuid.UUID, path: PathQuery, service: CodeServiceDep
) -> FileContent:
    """Source text of an indexed file, read from the repository checkout."""
    return service.file_content(repository_id, path)


@router.get("/files/detail", response_model=CodeFileDetail, responses=_NOT_FOUND)
def get_file_detail(
    repository_id: uuid.UUID, path: PathQuery, service: CodeServiceDep
) -> CodeFileDetail:
    """Symbols, imports, exports, API calls and file-level dependencies of one parsed file."""
    return service.file_detail(repository_id, path)


@router.get("/files/symbols", response_model=list[CodeSymbolRead], responses=_NOT_FOUND)
def get_file_symbols(
    repository_id: uuid.UUID, path: PathQuery, service: CodeServiceDep
) -> list[CodeSymbolRead]:
    """Symbols defined in one file, ordered by line (use `parent_symbol_id` to build the tree)."""
    return service.file_symbols(repository_id, path)


@router.get("/symbols", response_model=Page[SymbolSearchResult], responses=_NOT_FOUND)
def search_symbols(
    repository_id: uuid.UUID,
    service: CodeServiceDep,
    pagination: PaginationDep,
    q: Annotated[
        str | None, Query(max_length=200, description="Name contains (case-insensitive).")
    ] = None,
    kind: SymbolKind | None = None,
    path_prefix: Annotated[str | None, Query(max_length=1024)] = None,
    exported: Annotated[bool, Query(description="Only exported symbols.")] = False,
) -> Page[SymbolSearchResult]:
    items, total = service.search_symbols(
        repository_id,
        query=q,
        kind=kind,
        path_prefix=path_prefix,
        exported_only=exported,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.get("/dependencies", response_model=Page[RelationshipRead], responses=_NOT_FOUND)
def list_dependencies(
    repository_id: uuid.UUID,
    service: CodeServiceDep,
    pagination: PaginationDep,
    relationship_type: Annotated[
        RelationshipType | None,
        Query(alias="type", description="imports, calls, inherits or renders."),
    ] = None,
    confidence: Confidence | None = None,
    path: Annotated[
        str | None, Query(max_length=1024, description="Edges touching this file.")
    ] = None,
    symbol_id: Annotated[uuid.UUID | None, Query(description="Edges touching this symbol.")] = None,
    direction: Literal["outgoing", "incoming", "both"] = "both",
) -> Page[RelationshipRead]:
    """Dependency edges. `confirmed` edges come straight from resolved imports;
    `inferred` edges (calls, renders, inherits) are matched by name."""
    items, total = service.list_relationships(
        repository_id,
        relationship_type=relationship_type,
        confidence=confidence,
        path=path,
        symbol_id=symbol_id,
        direction=direction,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)
