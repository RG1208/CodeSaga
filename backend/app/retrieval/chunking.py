"""Code-aware chunking.

Retrieval works on chunks, and *where* code is split decides what a result means. A
fixed "every N characters" split cuts functions in half and produces chunks that start
mid-expression. CodeSage therefore uses the structure found in Phase 3:

* one chunk per function, method or small class (the whole definition, decorators included);
* a large class becomes a header chunk (signature, docstring, fields) plus one chunk per method;
* anything larger than `chunk_max_lines` is split into overlapping parts at blank lines;
* code that belongs to no symbol (imports, constants, `if __name__ == "__main__"`) becomes
  "module" chunks;
* Markdown is split at headings; other text files fall back to line windows.

Every chunk keeps the metadata needed to cite it: repository, file path, language,
symbol name and type, parent symbol, line range and a stable chunk id.
"""

import hashlib
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

CHUNKER_VERSION = 1
# Deterministic chunk ids: the same code chunk keeps its id across re-indexing, so
# research evaluations can refer to chunk ids over time.
CHUNK_NAMESPACE = uuid.UUID("2f4e1a2e-9d0b-4f0a-9a3b-6f8b2a1c4d55")

_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_CONTAINER_KINDS = frozenset({"class", "component", "interface", "enum"})
_MARKDOWN_EXTENSIONS = (".md", ".mdx", ".markdown", ".rst")
# Generated or data files: indexed for browsing, but not worth retrieving over.
_SKIPPED_NAMES = frozenset(
    {
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock",
        "Cargo.lock", "composer.lock", "Gemfile.lock", "go.sum",
    }
)  # fmt: skip
_SKIPPED_LANGUAGES = frozenset({"JSON", "CSV"})


def chunk_header(
    file_path: str, language: str, chunk_type: str, symbol_type: str | None, name: str | None
) -> str:
    """One line of context, used when building the index and when reranking, so a chunk
    is always described to the model in the same way."""
    kind = symbol_type or chunk_type
    return f"{file_path} ({language}) - {kind} {name}" if name else f"{file_path} ({language})"


@dataclass
class Chunk:
    chunk_id: uuid.UUID
    file_path: str
    language: str
    chunk_type: str  # symbol | symbol_part | module | section | window
    start_line: int  # 1-based, inclusive
    end_line: int
    content: str
    symbol_id: uuid.UUID | None = None
    symbol_name: str | None = None
    symbol_type: str | None = None  # SymbolKind value, "section" for Markdown headings…
    qualified_name: str | None = None
    parent_symbol: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    def header(self) -> str:
        """Context line prepended when indexing, so a chunk carries its own location."""
        return chunk_header(
            self.file_path,
            self.language,
            self.chunk_type,
            self.symbol_type,
            self.qualified_name or self.symbol_name,
        )

    def index_text(self) -> str:
        """What BM25 indexes and the embedding model sees."""
        return f"{self.header()}\n{self.content}"


@dataclass
class SymbolRecord:
    """The parts of a Phase 3 symbol the chunker needs."""

    id: uuid.UUID | None
    name: str
    kind: str
    qualified_name: str
    start_line: int
    end_line: int
    parent_name: str | None = None
    children: list["SymbolRecord"] = field(default_factory=list)


@dataclass(frozen=True)
class ChunkingConfig:
    max_lines: int = 60
    max_chars: int = 4000
    overlap_lines: int = 8
    min_lines: int = 2


class CodeChunker:
    def __init__(self, repository_id: uuid.UUID, config: ChunkingConfig | None = None) -> None:
        self.repository_id = repository_id
        self.config = config or ChunkingConfig()
        self._counts: dict[tuple[str, str], int] = {}

    # -- entry points --------------------------------------------------------------

    def chunk_source_file(
        self, path: str, language: str, content: str, symbols: Sequence[SymbolRecord]
    ) -> list[Chunk]:
        """A file parsed in Phase 3: split along its symbols."""
        lines = content.splitlines()
        if not lines:
            return []
        chunks: list[Chunk] = []
        covered: list[tuple[int, int]] = []
        present = {symbol.qualified_name for symbol in symbols}
        for symbol in sorted(symbols, key=lambda item: (item.start_line, -item.end_line)):
            if symbol.parent_name is not None and symbol.parent_name in present:
                continue  # nested symbols are chunked together with their parent
            chunks.extend(self._chunk_symbol(path, language, lines, symbol))
            covered.append((symbol.start_line, symbol.end_line))
        chunks.extend(self._module_chunks(path, language, lines, covered))
        return sorted(chunks, key=lambda chunk: (chunk.start_line, chunk.end_line))

    def chunk_text_file(self, path: str, language: str, content: str) -> list[Chunk]:
        """A file without parsed structure: Markdown sections, or plain line windows."""
        lines = content.splitlines()
        if not lines or not content.strip():
            return []
        if path.lower().endswith(_MARKDOWN_EXTENSIONS):
            return self._markdown_chunks(path, language, lines)
        return [
            self._make_chunk(path, language, lines, start, end, chunk_type="window")
            for start, end in self._windows(1, len(lines), lines)
        ]

    @staticmethod
    def should_chunk(path: str, language: str | None) -> bool:
        """Skip lock files and pure data formats; everything else is worth indexing."""
        name = path.rsplit("/", 1)[-1]
        if name in _SKIPPED_NAMES or language in _SKIPPED_LANGUAGES:
            return False
        return language is not None or path.lower().endswith(_MARKDOWN_EXTENSIONS)

    # -- symbols -------------------------------------------------------------------

    def _chunk_symbol(
        self, path: str, language: str, lines: list[str], symbol: SymbolRecord
    ) -> list[Chunk]:
        size = symbol.end_line - symbol.start_line + 1
        text_size = self._char_count(lines, symbol.start_line, symbol.end_line)
        fits = size <= self.config.max_lines and text_size <= self.config.max_chars

        if fits or not symbol.children:
            if fits:
                return [
                    self._symbol_chunk(
                        path, language, lines, symbol, symbol.start_line, symbol.end_line
                    )
                ]
            return self._split_symbol(path, language, lines, symbol)

        # A large container: header (signature, docstring, fields) + one chunk per member.
        chunks: list[Chunk] = []
        children = sorted(symbol.children, key=lambda item: item.start_line)
        header_end = min(children[0].start_line - 1, symbol.end_line)
        if header_end >= symbol.start_line:
            chunks.append(
                self._symbol_chunk(
                    path,
                    language,
                    lines,
                    symbol,
                    symbol.start_line,
                    header_end,
                    chunk_type="symbol_header",
                )
            )
        previous_end = header_end
        for child in children:
            if child.start_line > previous_end + 1:  # code between members
                chunks.extend(
                    self._make_chunk(
                        path, language, lines, start, end, chunk_type="module", parent=symbol
                    )
                    for start, end in self._windows(previous_end + 1, child.start_line - 1, lines)
                )
            chunks.extend(self._chunk_symbol(path, language, lines, child))
            previous_end = max(previous_end, child.end_line)
        if previous_end < symbol.end_line:
            chunks.extend(
                self._make_chunk(
                    path, language, lines, start, end, chunk_type="module", parent=symbol
                )
                for start, end in self._windows(previous_end + 1, symbol.end_line, lines)
            )
        return chunks

    def _split_symbol(
        self, path: str, language: str, lines: list[str], symbol: SymbolRecord
    ) -> list[Chunk]:
        windows = self._windows(symbol.start_line, symbol.end_line, lines)
        return [
            self._symbol_chunk(
                path,
                language,
                lines,
                symbol,
                start,
                end,
                chunk_type="symbol_part",
                part=(index, len(windows)),
            )
            for index, (start, end) in enumerate(windows, start=1)
        ]

    def _symbol_chunk(
        self,
        path: str,
        language: str,
        lines: list[str],
        symbol: SymbolRecord,
        start: int,
        end: int,
        *,
        chunk_type: str = "symbol",
        part: tuple[int, int] | None = None,
    ) -> Chunk:
        metadata: dict[str, Any] = {}
        if part is not None:
            metadata["part"], metadata["parts"] = part
        if chunk_type == "symbol_header":
            metadata["members"] = [child.name for child in symbol.children[:50]]
        return self._make_chunk(
            path,
            language,
            lines,
            start,
            end,
            chunk_type=chunk_type,
            symbol=symbol,
            metadata=metadata,
        )

    # -- module-level code ----------------------------------------------------------

    def _module_chunks(
        self, path: str, language: str, lines: list[str], covered: list[tuple[int, int]]
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        for start, end in self._gaps(len(lines), covered):
            chunks.extend(
                self._make_chunk(
                    path, language, lines, window_start, window_end, chunk_type="module"
                )
                for window_start, window_end in self._windows(start, end, lines)
            )
        return chunks

    @staticmethod
    def _gaps(total_lines: int, covered: list[tuple[int, int]]) -> list[tuple[int, int]]:
        gaps: list[tuple[int, int]] = []
        cursor = 1
        for start, end in sorted(covered):
            if start > cursor:
                gaps.append((cursor, start - 1))
            cursor = max(cursor, end + 1)
        if cursor <= total_lines:
            gaps.append((cursor, total_lines))
        return gaps

    # -- Markdown --------------------------------------------------------------------

    def _markdown_chunks(self, path: str, language: str, lines: list[str]) -> list[Chunk]:
        sections: list[tuple[int, int, str | None]] = []
        current_start, heading = 1, None
        for number, line in enumerate(lines, start=1):
            match = _MARKDOWN_HEADING.match(line)
            if match and number > current_start:
                sections.append((current_start, number - 1, heading))
                current_start, heading = number, match.group(2)
            elif match:
                heading = match.group(2)
        sections.append((current_start, len(lines), heading))

        chunks: list[Chunk] = []
        for start, end, title in sections:
            for window_start, window_end in self._windows(start, end, lines):
                chunk = self._make_chunk(
                    path, language, lines, window_start, window_end, chunk_type="section"
                )
                if title:
                    chunk.symbol_name = title[:200]
                    chunk.symbol_type = "section"
                    chunk.qualified_name = title[:200]
                chunks.append(chunk)
        return chunks

    # -- helpers ----------------------------------------------------------------------

    def _windows(self, start: int, end: int, lines: list[str]) -> list[tuple[int, int]]:
        """Split [start, end] into windows, preferring blank lines as boundaries."""
        windows: list[tuple[int, int]] = []
        cursor = start
        while cursor <= end:
            limit = min(cursor + self.config.max_lines - 1, end)
            while limit > cursor and self._char_count(lines, cursor, limit) > self.config.max_chars:
                limit -= 1
            if limit < end:
                boundary = self._blank_line_before(lines, cursor, limit)
                if boundary is not None:
                    limit = boundary
            if self._has_content(lines, cursor, limit):
                windows.append((cursor, limit))
            cursor = (
                limit + 1
                if limit >= end
                else max(limit + 1 - self.config.overlap_lines, cursor + 1)
            )
            if windows and windows[-1][1] >= end:
                break
        return [window for window in windows if self._keep(lines, window)]

    def _keep(self, lines: list[str], window: tuple[int, int]) -> bool:
        start, end = window
        return self._has_content(lines, start, end) and not self._is_separator(lines, start, end)

    @staticmethod
    def _is_separator(lines: list[str], start: int, end: int) -> bool:
        """A gap holding only a comment or two, such as `# -- queries ---`, is not worth
        indexing. Blank lines do not count towards the limit."""
        content = [line.strip() for line in lines[start - 1 : end] if line.strip()]
        if len(content) > 3:
            return False
        return all(line.startswith(("#", "//", "/*", "*", "<!--", "--")) for line in content)

    @staticmethod
    def _blank_line_before(lines: list[str], start: int, limit: int) -> int | None:
        for number in range(limit, start + 2, -1):
            if not lines[number - 1].strip():
                return number - 1
        return None

    @staticmethod
    def _has_content(lines: list[str], start: int, end: int) -> bool:
        return any(line.strip() for line in lines[start - 1 : end])

    @staticmethod
    def _char_count(lines: list[str], start: int, end: int) -> int:
        return sum(len(line) + 1 for line in lines[start - 1 : end])

    def _make_chunk(
        self,
        path: str,
        language: str,
        lines: list[str],
        start: int,
        end: int,
        *,
        chunk_type: str,
        symbol: SymbolRecord | None = None,
        parent: SymbolRecord | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Chunk:
        content = "\n".join(lines[start - 1 : end])
        chunk = Chunk(
            chunk_id=uuid.uuid4(),  # replaced below by the deterministic id
            file_path=path,
            language=language,
            chunk_type=chunk_type,
            start_line=start,
            end_line=end,
            content=content,
            metadata=dict(metadata or {}),
        )
        if symbol is not None:
            chunk.symbol_id = symbol.id
            chunk.symbol_name = symbol.name
            chunk.symbol_type = symbol.kind
            chunk.qualified_name = symbol.qualified_name
            chunk.parent_symbol = symbol.parent_name
        elif parent is not None:
            chunk.parent_symbol = parent.qualified_name
        chunk.chunk_id = self._chunk_id(chunk)
        return chunk

    def _chunk_id(self, chunk: Chunk) -> uuid.UUID:
        """Stable across re-indexing: symbol chunks keyed by name + content, others by position."""
        digest = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()[:16]
        if chunk.qualified_name and chunk.chunk_type.startswith("symbol"):
            key = (chunk.file_path, chunk.qualified_name)
            occurrence = self._counts.get(key, 0)
            self._counts[key] = occurrence + 1
            part = chunk.metadata.get("part", 0)
            identity = (
                f"{chunk.file_path}|{chunk.qualified_name}|{chunk.chunk_type}"
                f"|{occurrence}|{part}|{digest}"
            )
        else:
            identity = f"{chunk.file_path}|{chunk.chunk_type}|{chunk.start_line}|{digest}"
        return uuid.uuid5(CHUNK_NAMESPACE, f"{self.repository_id}|{identity}")


def symbol_records(rows: Iterable[dict[str, Any]]) -> list[SymbolRecord]:
    """Build the symbol tree the chunker needs from `code_symbols`-shaped rows."""
    records: dict[uuid.UUID, SymbolRecord] = {}
    parents: dict[uuid.UUID, uuid.UUID | None] = {}
    for row in rows:
        records[row["id"]] = SymbolRecord(
            id=row["id"],
            name=row["name"],
            kind=row["kind"] if isinstance(row["kind"], str) else row["kind"].value,
            qualified_name=row["qualified_name"],
            start_line=row["start_line"],
            end_line=row["end_line"],
        )
        parents[row["id"]] = row.get("parent_symbol_id")
    for symbol_id, parent_id in parents.items():
        parent = records.get(parent_id) if parent_id else None
        if parent is not None:
            records[symbol_id].parent_name = parent.qualified_name
            parent.children.append(records[symbol_id])
    return list(records.values())


def container_kinds() -> frozenset[str]:
    return _CONTAINER_KINDS
