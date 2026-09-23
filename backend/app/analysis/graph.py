"""Build the dependency graph from per-file analysis results.

Edges:
* imports  (file → file)      confirmed when the import resolved to exactly one file,
                               inferred when several files could match.
* calls    (symbol → symbol)  always inferred: matched by name through local
* renders  (component → component)   definitions, imports, `self`/`this`, or
* inherits (class → class)            namespace/module access.

Static analysis cannot see dynamic dispatch, monkey-patching, dependency injection or
values passed around at runtime, so unresolved calls are simply left out rather than
guessed.
"""

import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.analysis.resolver import ImportResolution
from app.analysis.results import (
    Confidence,
    ExtractedSymbol,
    FileAnalysis,
    ParseStatus,
    RelationshipType,
    SymbolKind,
)

_MAX_LISTED = 10
_MAX_REEXPORT_DEPTH = 4
_GENERIC_SUFFIX = re.compile(r"[\[<].*$")


@dataclass
class AnalyzedFile:
    id: uuid.UUID
    path: str
    language: str
    analysis: FileAnalysis
    symbol_ids: list[uuid.UUID]  # index = ExtractedSymbol.key
    parse_status: ParseStatus = ParseStatus.PARSED
    resolutions: list[ImportResolution] = field(default_factory=list)  # aligned with imports


@dataclass
class Relationship:
    type: RelationshipType
    confidence: Confidence
    source_file_id: uuid.UUID
    target_file_id: uuid.UUID
    source_symbol_id: uuid.UUID | None = None
    target_symbol_id: uuid.UUID | None = None
    weight: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Binding:
    """A local name introduced by an import."""

    file: AnalyzedFile
    name: str | None  # None: the module/namespace object itself


def _add_unique(values: list, value: Any, limit: int = _MAX_LISTED) -> None:
    if value not in values and len(values) < limit:
        values.append(value)


class DependencyGraphBuilder:
    def __init__(self, files: list[AnalyzedFile]) -> None:
        self.files = files
        self.by_path = {file.path: file for file in files}
        self._top_level: dict[uuid.UUID, dict[str, int]] = {}
        self._members: dict[tuple[uuid.UUID, int], dict[str, int]] = {}
        self._exports: dict[uuid.UUID, dict[str, str]] = {}
        self._bindings: dict[uuid.UUID, dict[str, _Binding]] = {}
        for file in files:
            self._index_file(file)

    def build(self) -> list[Relationship]:
        return self._file_imports() + self._symbol_relationships()

    # -- indexes ---------------------------------------------------------------

    def _index_file(self, file: AnalyzedFile) -> None:
        symbols = file.analysis.symbols
        top_level: dict[str, int] = {}
        for symbol in symbols:
            if symbol.parent_key is None:
                top_level[symbol.name] = symbol.key
            else:
                self._members.setdefault((file.id, symbol.parent_key), {})[symbol.name] = symbol.key
        self._top_level[file.id] = top_level

        exports: dict[str, str] = {}
        for exported in file.analysis.exports:
            if exported.local_name and exported.kind not in ("re_export", "namespace"):
                exports[exported.name] = exported.local_name
        self._exports[file.id] = exports

    def _bindings_for(self, file: AnalyzedFile) -> dict[str, _Binding]:
        if file.id in self._bindings:
            return self._bindings[file.id]
        bindings: dict[str, _Binding] = {}
        for imported, resolution in zip(file.analysis.imports, file.resolutions, strict=False):
            module_file = self.by_path.get(resolution.target.path) if resolution.target else None
            if file.language == "python":
                for name in imported.names:
                    if imported.kind == "import":
                        if module_file is not None:
                            bindings[name.local_name] = _Binding(module_file, None)
                    elif name.name in resolution.name_targets:
                        submodule = self.by_path.get(resolution.name_targets[name.name].path)
                        if submodule is not None:
                            bindings[name.local_name] = _Binding(submodule, None)
                    elif module_file is not None and name.name != "*":
                        bindings[name.local_name] = _Binding(module_file, name.name)
            elif imported.kind in ("import", "require") and module_file is not None:
                for name in imported.names:
                    bindings[name.local_name] = _Binding(
                        module_file, None if name.name == "*" else name.name
                    )
        self._bindings[file.id] = bindings
        return bindings

    def _lookup_export(
        self, file: AnalyzedFile, name: str, depth: int = 0
    ) -> tuple[AnalyzedFile, int] | None:
        """Find the symbol that module `file` makes available as `name`."""
        top_level = self._top_level[file.id]
        if file.language == "python":
            key = top_level.get(name)
            return (file, key) if key is not None else None

        if name == "default":
            local = self._exports[file.id].get("default")
            if local is not None and local in top_level:
                return file, top_level[local]
            for symbol in file.analysis.symbols:
                if symbol.metadata.get("default_export"):
                    return file, symbol.key
        else:
            local = self._exports[file.id].get(name, name)
            key = top_level.get(local)
            if key is not None and file.analysis.symbols[key].is_exported:
                return file, key

        if depth >= _MAX_REEXPORT_DEPTH:
            return None
        for imported, resolution in zip(file.analysis.imports, file.resolutions, strict=False):
            if imported.kind != "re_export" or resolution.target is None:
                continue
            target = self.by_path.get(resolution.target.path)
            if target is None:
                continue
            for re_exported in imported.names:
                if re_exported.name == "*" and re_exported.alias is None:
                    # `export * from "./x"` forwards every named export (never the default).
                    lookup_name = name if name != "default" else None
                elif re_exported.name != "*" and re_exported.local_name == name:
                    lookup_name = re_exported.name  # `export { a as b } from "./x"`
                else:
                    lookup_name = None
                if lookup_name and (found := self._lookup_export(target, lookup_name, depth + 1)):
                    return found
        return None

    # -- file imports ------------------------------------------------------------

    def _file_imports(self) -> list[Relationship]:
        edges: dict[tuple[uuid.UUID, uuid.UUID], Relationship] = {}
        for file in self.files:
            for imported, resolution in zip(file.analysis.imports, file.resolutions, strict=False):
                for target in resolution.all_targets():
                    target_file = self.by_path.get(target.path)
                    if target_file is None or target_file.id == file.id:
                        continue
                    edge = edges.get((file.id, target_file.id))
                    if edge is None:
                        edge = Relationship(
                            type=RelationshipType.IMPORTS,
                            confidence=target.confidence,
                            source_file_id=file.id,
                            target_file_id=target_file.id,
                            metadata={"specifiers": [], "lines": [], "kinds": [], "strategies": []},
                        )
                        edges[(file.id, target_file.id)] = edge
                    edge.weight += 1
                    if target.confidence is Confidence.CONFIRMED:
                        edge.confidence = Confidence.CONFIRMED
                    _add_unique(edge.metadata["specifiers"], imported.module)
                    _add_unique(edge.metadata["lines"], imported.start_line, limit=20)
                    _add_unique(edge.metadata["kinds"], imported.kind)
                    _add_unique(edge.metadata["strategies"], target.strategy)
                    if target.candidates:
                        edge.metadata["candidates"] = target.candidates
        return list(edges.values())

    # -- calls, renders, inheritance ------------------------------------------------

    def _symbol_relationships(self) -> list[Relationship]:
        edges: dict[tuple[RelationshipType, uuid.UUID, uuid.UUID], Relationship] = {}

        def add(
            kind: RelationshipType,
            file: AnalyzedFile,
            source_key: int,
            target: tuple[AnalyzedFile, int, str],
            line: int,
            expression: str,
        ) -> None:
            target_file, target_key, strategy = target
            if target_file.id == file.id and target_key == source_key:
                return  # recursion adds nothing to a dependency graph
            source_id = file.symbol_ids[source_key]
            target_id = target_file.symbol_ids[target_key]
            edge = edges.get((kind, source_id, target_id))
            if edge is None:
                edge = Relationship(
                    type=kind,
                    confidence=Confidence.INFERRED,
                    source_file_id=file.id,
                    target_file_id=target_file.id,
                    source_symbol_id=source_id,
                    target_symbol_id=target_id,
                    metadata={"resolution": strategy, "expressions": [], "lines": []},
                )
                edges[(kind, source_id, target_id)] = edge
            edge.weight += 1
            _add_unique(edge.metadata["expressions"], expression, limit=5)
            _add_unique(edge.metadata["lines"], line)

        for file in self.files:
            symbols = file.analysis.symbols
            for call in file.analysis.calls:
                if call.caller_key is None:
                    continue
                target = self._resolve_reference(file, symbols[call.caller_key], call.callee)
                if target is not None:
                    kind = (
                        RelationshipType.RENDERS
                        if call.kind == "render"
                        else RelationshipType.CALLS
                    )
                    add(kind, file, call.caller_key, target, call.line, call.callee)
            for symbol in symbols:
                for base in symbol.metadata.get("bases", []):
                    reference = _GENERIC_SUFFIX.sub("", base).strip()
                    target = self._resolve_reference(file, None, reference)
                    if target is not None and target[0].analysis.symbols[target[1]].kind in (
                        SymbolKind.CLASS,
                        SymbolKind.COMPONENT,
                    ):
                        add(
                            RelationshipType.INHERITS,
                            file,
                            symbol.key,
                            target,
                            symbol.start_line,
                            base,
                        )
        return list(edges.values())

    def _resolve_reference(
        self, file: AnalyzedFile, caller: ExtractedSymbol | None, expression: str
    ) -> tuple[AnalyzedFile, int, str] | None:
        parts = expression.split(".")
        symbols = file.analysis.symbols
        top_level = self._top_level[file.id]
        bindings = self._bindings_for(file)

        if parts[0] in ("self", "this", "cls") and len(parts) == 2 and caller is not None:
            class_key = self._enclosing_class(symbols, caller)
            if class_key is None:
                return None
            return self._class_member(file, class_key, parts[1], "self")

        if len(parts) == 1:
            name = parts[0]
            if name in bindings:
                binding = bindings[name]
                if binding.name is None:
                    return None  # calling a module object is not a symbol reference
                found = self._lookup_export(binding.file, binding.name)
                return (found[0], found[1], "import") if found else None
            if name in top_level:
                return file, top_level[name], "same_file"
            return None

        # Dotted: module.function, namespace.Component, ImportedClass.method, LocalClass.method
        for split in range(len(parts) - 1, 0, -1):
            prefix, rest = ".".join(parts[:split]), parts[split:]
            binding = bindings.get(prefix)
            if binding is None:
                continue
            if binding.name is None:  # a module or namespace: rest[0] is exported by it
                found = self._lookup_export(binding.file, rest[0])
                return self._member_of(found, rest[1:], "namespace")
            found = self._lookup_export(binding.file, binding.name)  # an imported class
            return self._member_of(found, rest, "import")

        if parts[0] in top_level:
            return self._member_of((file, top_level[parts[0]]), parts[1:], "same_file")
        return None

    def _class_member(
        self, file: AnalyzedFile, class_key: int, name: str, strategy: str, depth: int = 0
    ) -> tuple[AnalyzedFile, int, str] | None:
        """A method of a class, looking through base classes we can resolve."""
        key = self._members.get((file.id, class_key), {}).get(name)
        if key is not None:
            return file, key, strategy if depth == 0 else f"{strategy}_inherited"
        if depth >= _MAX_REEXPORT_DEPTH:
            return None
        for base in file.analysis.symbols[class_key].metadata.get("bases", []):
            base_class = self._resolve_reference(file, None, _GENERIC_SUFFIX.sub("", base).strip())
            if base_class is not None:
                found = self._class_member(base_class[0], base_class[1], name, strategy, depth + 1)
                if found is not None:
                    return found
        return None

    def _member_of(
        self, found: tuple[AnalyzedFile, int] | None, members: list[str], strategy: str
    ) -> tuple[AnalyzedFile, int, str] | None:
        if found is None or len(members) > 1:
            return None
        target_file, key = found
        if not members:
            return target_file, key, strategy
        member = self._members.get((target_file.id, key), {}).get(members[0])
        return (target_file, member, strategy) if member is not None else None

    @staticmethod
    def _enclosing_class(symbols: list[ExtractedSymbol], symbol: ExtractedSymbol) -> int | None:
        current: ExtractedSymbol | None = symbol
        while current is not None:
            if current.kind is SymbolKind.CLASS or (
                current.kind is SymbolKind.COMPONENT and "bases" in current.metadata
            ):
                return current.key
            current = symbols[current.parent_key] if current.parent_key is not None else None
        return None


def summarize(
    files: list[AnalyzedFile], relationships: list[Relationship], skipped: int
) -> dict[str, Any]:
    """Repository-level statistics stored with the repository metadata."""
    symbol_kinds: Counter[str] = Counter()
    imports: Counter[str] = Counter()
    packages: Counter[str] = Counter()
    for file in files:
        symbol_kinds.update(symbol.kind.value for symbol in file.analysis.symbols)
        imports.update(resolution.status for resolution in file.resolutions)
        packages.update(
            {r.package for r in file.resolutions if r.status == "external" and r.package}
        )

    relationship_counts: dict[str, dict[str, int]] = {}
    importers: Counter[uuid.UUID] = Counter()
    for relationship in relationships:
        bucket = relationship_counts.setdefault(
            relationship.type.value, {"confirmed": 0, "inferred": 0}
        )
        bucket[relationship.confidence.value] += 1
        if relationship.type is RelationshipType.IMPORTS:
            importers[relationship.target_file_id] += 1

    paths = {file.id: file.path for file in files}
    return {
        "files_by_language": dict(Counter(file.language for file in files).most_common()),
        "parse_status": dict(Counter(file.parse_status.value for file in files)),
        "symbols_by_kind": dict(symbol_kinds.most_common()),
        "imports": dict(imports),
        "relationships": relationship_counts,
        "api_calls": sum(len(file.analysis.api_calls) for file in files),
        "most_imported": [
            {"path": paths[file_id], "importers": count}
            for file_id, count in importers.most_common(_MAX_LISTED)
        ],
        "external_packages": [
            {"name": name, "files": count} for name, count in packages.most_common(15)
        ],
        "skipped_files": skipped,
    }
