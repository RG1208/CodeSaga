"""What an analyzer extracts from one source file (no database, no Tree-sitter types)."""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class SymbolKind(StrEnum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    COMPONENT = "component"  # a React component (function or class)
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"
    ENUM = "enum"
    VARIABLE = "variable"  # exported top-level constants (JS/TS)


class ParseStatus(StrEnum):
    PARSED = "parsed"
    PARTIAL = "partial"  # the file has syntax errors; extraction is best effort
    FAILED = "failed"


class RelationshipType(StrEnum):
    IMPORTS = "imports"  # file → file
    CALLS = "calls"  # symbol → symbol
    INHERITS = "inherits"  # class → class
    RENDERS = "renders"  # React component → component (JSX)


class Confidence(StrEnum):
    """How much a relationship can be trusted.

    CONFIRMED: read directly from syntax and resolved to exactly one file.
    INFERRED:  depends on matching names, which static analysis cannot prove
               (shadowing, dynamic dispatch, ambiguous module paths).
    """

    CONFIRMED = "confirmed"
    INFERRED = "inferred"


@dataclass
class Parameter:
    name: str
    type: str | None = None
    default: str | None = None
    # positional | positional_only | keyword_only | var_positional | var_keyword
    # | rest | destructured
    kind: str = "positional"
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value not in (None, False)}


@dataclass
class ExtractedSymbol:
    key: int  # position in the file's symbol list; parents always come first
    name: str
    kind: SymbolKind
    start_line: int  # 1-based, inclusive; includes decorators
    end_line: int
    parent_key: int | None = None
    qualified_name: str = ""
    signature: str | None = None
    docstring: str | None = None
    is_exported: bool = False
    is_async: bool = False
    parameters: list[Parameter] = field(default_factory=list)
    return_type: str | None = None
    decorators: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImportedName:
    name: str  # the name in the other module; "default" or "*" for JS default/namespace
    alias: str | None = None  # the local binding, when different or required

    @property
    def local_name(self) -> str:
        return self.alias or self.name

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, **({"alias": self.alias} if self.alias else {})}


@dataclass
class ExtractedImport:
    module: str  # exactly as written: "react", "./api", "app.core", "..models"
    # import | from | require | dynamic | side_effect | re_export
    kind: str
    start_line: int
    end_line: int
    names: list[ImportedName] = field(default_factory=list)
    level: int = 0  # Python relative-import dots
    is_type_only: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedCall:
    callee: str  # "helper", "self.save", "api.getUsers", "Card" (for JSX)
    line: int
    caller_key: int | None  # enclosing symbol; None at module level
    kind: str = "call"  # call | render


@dataclass
class ExportedName:
    name: str  # name visible to importers ("default" for default exports)
    local_name: str | None = None  # the symbol it refers to in this file
    kind: str = "named"  # named | default | re_export | namespace | commonjs | all | implicit
    source: str | None = None  # module for re-exports
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass
class ApiCall:
    client: str  # fetch | axios | ky | <object name>
    method: str  # GET, POST, …
    url: str  # literal URL; template parts appear as {expression}
    line: int
    caller_key: int | None

    def to_dict(self) -> dict[str, Any]:
        return {"client": self.client, "method": self.method, "url": self.url, "line": self.line}


@dataclass
class FileAnalysis:
    language: str
    symbols: list[ExtractedSymbol] = field(default_factory=list)
    imports: list[ExtractedImport] = field(default_factory=list)
    calls: list[ExtractedCall] = field(default_factory=list)
    exports: list[ExportedName] = field(default_factory=list)
    api_calls: list[ApiCall] = field(default_factory=list)
    docstring: str | None = None
    syntax_error_count: int = 0
    comment_lines: int = 0
    truncated: bool = False  # symbol limit reached

    @property
    def status(self) -> ParseStatus:
        return ParseStatus.PARTIAL if self.syntax_error_count else ParseStatus.PARSED
