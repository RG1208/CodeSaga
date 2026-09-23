"""The analyzer interface and small helpers shared by Tree-sitter based analyzers."""

import inspect
import re
from abc import ABC, abstractmethod
from collections.abc import Iterator

from tree_sitter import Language, Node, Parser, Tree

from app.analysis.results import FileAnalysis

MAX_SYMBOLS_PER_FILE = 5000
MAX_TEXT_LENGTH = 300
_WHITESPACE = re.compile(r"\s+")


class LanguageAnalyzer(ABC):
    """Extracts structure from the source of one language.

    To support a new language: subclass this (usually via a Tree-sitter grammar),
    set `language` and `extensions`, implement `analyze`, and register it in
    `registry.default_registry()`.
    """

    language: str
    extensions: tuple[str, ...]

    @abstractmethod
    def analyze(self, source: bytes, path: str) -> FileAnalysis: ...


class TreeSitterAnalyzer(LanguageAnalyzer):
    """Base for analyzers backed by a Tree-sitter grammar."""

    def __init__(self, language: Language) -> None:
        # Parsers are cheap but not thread-safe; create one per analyze() call.
        self._language = language

    def parse(self, source: bytes) -> Tree:
        return Parser(self._language).parse(source)


def node_text(node: Node | None, source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def compact(text: str, limit: int = MAX_TEXT_LENGTH) -> str:
    """Collapse whitespace and truncate, for signatures and type annotations."""
    collapsed = _WHITESPACE.sub(" ", text).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def start_line(node: Node) -> int:
    return node.start_point.row + 1


def end_line(node: Node) -> int:
    return node.end_point.row + 1


def clean_docstring(text: str, limit: int = 2000) -> str | None:
    cleaned = inspect.cleandoc(text).strip()
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def count_errors(node: Node) -> int:
    """Number of ERROR / MISSING nodes (syntax errors Tree-sitter recovered from)."""
    if not node.has_error:
        return 0
    errors = 0
    for descendant in walk(node):
        if descendant.is_error or descendant.is_missing:
            errors += 1
    return errors


def walk(root: Node) -> Iterator[Node]:
    """Pre-order traversal without recursion (deep trees cannot overflow the stack)."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def count_comment_lines(root: Node) -> int:
    lines: set[int] = set()
    for node in walk(root):
        if node.type == "comment":
            lines.update(range(node.start_point.row, node.end_point.row + 1))
    return len(lines)


def preceding_comments(node: Node) -> list[Node]:
    """Comment nodes immediately above `node`, with no blank line in between."""
    comments: list[Node] = []
    expected_row = node.start_point.row
    sibling = node.prev_sibling
    while sibling is not None and sibling.type == "comment":
        if sibling.end_point.row < expected_row - 1:
            break
        comments.append(sibling)
        expected_row = sibling.start_point.row
        sibling = sibling.prev_sibling
    comments.reverse()
    return comments
