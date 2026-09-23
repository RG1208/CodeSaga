"""Analyze a whole checkout: parse every supported file, resolve imports, build the graph.

The result is plain dictionaries shaped like the database rows, with UUIDs assigned up
front so parents, imports and relationships can reference each other before anything
is written. The caller stores them in one transaction.
"""

import hashlib
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.analysis.graph import AnalyzedFile, DependencyGraphBuilder, Relationship, summarize
from app.analysis.registry import AnalyzerRegistry, default_registry
from app.analysis.resolver import ImportResolver
from app.analysis.results import FileAnalysis, ParseStatus
from app.ingestion.scanner import count_lines, read_text_file

logger = logging.getLogger(__name__)

ANALYZER_VERSION = 1
_MAX_CONFIG_BYTES = 256 * 1024
_MAX_LISTED_PER_FILE = 200


@dataclass
class RepositoryAnalysis:
    files: list[dict[str, Any]] = field(default_factory=list)
    symbols: list[dict[str, Any]] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def analyze_repository(
    root: Path,
    paths: Sequence[str],
    *,
    max_file_bytes: int,
    known_paths: Sequence[str] = (),
    registry: AnalyzerRegistry | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> RepositoryAnalysis:
    """`paths` are the repository's indexed text files (relative, POSIX style).

    `known_paths` lists other files that exist but are not parsed (images, large
    data files) so imports such as `import logo from "./logo.png"` still resolve.
    `on_progress(done, total)` is called after each file; it may raise to cancel.
    """
    registry = registry or default_registry()
    candidates = [path for path in sorted(paths) if registry.analyzer_for(path) is not None]
    analyzed: list[AnalyzedFile] = []
    contents: dict[uuid.UUID, bytes] = {}
    skipped = 0

    for position, path in enumerate(candidates, start=1):
        analyzer = registry.analyzer_for(path)
        assert analyzer is not None
        content = read_text_file(root, path, max_bytes=max_file_bytes)
        if content is None:
            skipped += 1  # too large, binary or unreadable
        else:
            file_id = uuid.uuid4()
            try:
                analysis = analyzer.analyze(content, path)
                status = analysis.status
            except Exception:
                logger.exception("parser failed", extra={"path": path})
                analysis, status = FileAnalysis(language=analyzer.language), ParseStatus.FAILED
            analyzed.append(
                AnalyzedFile(
                    id=file_id,
                    path=path,
                    language=analyzer.language,
                    analysis=analysis,
                    symbol_ids=[uuid.uuid4() for _ in analysis.symbols],
                    parse_status=status,
                )
            )
            contents[file_id] = content
        if on_progress is not None:
            on_progress(position, len(candidates))

    resolver = ImportResolver(
        {*paths, *known_paths},
        read_text=lambda path: _decode(read_text_file(root, path, max_bytes=_MAX_CONFIG_BYTES)),
    )
    for file in analyzed:
        file.resolutions = [
            resolver.resolve(file.path, file.language, imported)
            for imported in file.analysis.imports
        ]

    relationships = DependencyGraphBuilder(analyzed).build()
    result = RepositoryAnalysis(
        relationships=[_relationship_row(relationship) for relationship in relationships],
        summary={
            "analyzer_version": ANALYZER_VERSION,
            "files_analyzed": len(analyzed),
            **summarize(analyzed, relationships, skipped),
        },
    )
    by_path = {file.path: file for file in analyzed}
    for file in analyzed:
        result.files.append(_file_row(file, contents[file.id]))
        result.symbols.extend(_symbol_rows(file))
        result.imports.extend(_import_rows(file, by_path))
    return result


def _decode(content: bytes | None) -> str | None:
    return content.decode("utf-8", errors="replace") if content is not None else None


def _file_row(file: AnalyzedFile, content: bytes) -> dict[str, Any]:
    analysis = file.analysis
    metadata: dict[str, Any] = {
        "docstring": analysis.docstring,
        "exports": [exported.to_dict() for exported in analysis.exports[:_MAX_LISTED_PER_FILE]],
        "api_calls": [call.to_dict() for call in analysis.api_calls[:_MAX_LISTED_PER_FILE]],
        "syntax_errors": analysis.syntax_error_count,
        "comment_lines": analysis.comment_lines,
    }
    if analysis.truncated:
        metadata["truncated"] = True
    if file.parse_status is ParseStatus.FAILED:
        metadata["error"] = "The parser could not process this file."
    return {
        "id": file.id,
        "path": file.path,
        "language": file.language,
        "size_bytes": len(content),
        "line_count": count_lines(content),
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "parse_status": file.parse_status,
        "symbol_count": len(analysis.symbols),
        "import_count": len(analysis.imports),
        "file_metadata": {
            key: value for key, value in metadata.items() if value not in (None, [], 0)
        },
    }


def _symbol_rows(file: AnalyzedFile) -> list[dict[str, Any]]:
    rows = []
    for symbol in file.analysis.symbols:  # parents precede children
        rows.append(
            {
                "id": file.symbol_ids[symbol.key],
                "file_id": file.id,
                "parent_symbol_id": file.symbol_ids[symbol.parent_key]
                if symbol.parent_key is not None
                else None,
                "name": symbol.name[:512],
                "qualified_name": symbol.qualified_name[:2048],
                "kind": symbol.kind,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
                "signature": symbol.signature,
                "docstring": symbol.docstring,
                "return_type": symbol.return_type[:512] if symbol.return_type else None,
                "is_exported": symbol.is_exported,
                "is_async": symbol.is_async,
                "parameters": [parameter.to_dict() for parameter in symbol.parameters],
                "decorators": symbol.decorators,
                "symbol_metadata": symbol.metadata,
            }
        )
    return rows


def _import_rows(file: AnalyzedFile, by_path: dict[str, AnalyzedFile]) -> list[dict[str, Any]]:
    rows = []
    for imported, resolution in zip(file.analysis.imports, file.resolutions, strict=True):
        target = resolution.target
        metadata: dict[str, Any] = dict(imported.metadata)
        if imported.level:
            metadata["level"] = imported.level
        if resolution.package:
            metadata["package"] = resolution.package
        if target is not None:
            metadata["confidence"] = target.confidence.value
            metadata["strategy"] = target.strategy
            if target.candidates:
                metadata["candidates"] = target.candidates
        if resolution.name_targets:
            metadata["name_targets"] = {
                name: item.path for name, item in resolution.name_targets.items()
            }
        target_file = by_path.get(target.path) if target is not None else None
        rows.append(
            {
                "id": uuid.uuid4(),
                "file_id": file.id,
                "module": imported.module[:1024],
                "kind": imported.kind,
                "names": [name.to_dict() for name in imported.names],
                "start_line": imported.start_line,
                "end_line": imported.end_line,
                "is_type_only": imported.is_type_only,
                "resolution_status": resolution.status,
                "resolved_path": target.path if target is not None else None,
                "resolved_file_id": target_file.id if target_file is not None else None,
                "import_metadata": metadata,
            }
        )
    return rows


def _relationship_row(relationship: Relationship) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "relationship_type": relationship.type,
        "confidence": relationship.confidence,
        "source_file_id": relationship.source_file_id,
        "target_file_id": relationship.target_file_id,
        "source_symbol_id": relationship.source_symbol_id,
        "target_symbol_id": relationship.target_symbol_id,
        "weight": relationship.weight,
        "relationship_metadata": relationship.metadata,
    }
