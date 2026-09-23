"""Code-aware chunking: structure decides the boundaries, and metadata is preserved."""

import uuid

import pytest

from app.retrieval.chunking import ChunkingConfig, CodeChunker, SymbolRecord, symbol_records
from tests.retrieval.helpers import chunk_fixture, fixture_root

REPOSITORY_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def chunker(**config: int) -> CodeChunker:
    return CodeChunker(REPOSITORY_ID, ChunkingConfig(**config))  # type: ignore[arg-type]


def symbol(name: str, kind: str, start: int, end: int, parent: str | None = None) -> SymbolRecord:
    return SymbolRecord(
        id=uuid.uuid4(),
        name=name.split(".")[-1],
        kind=kind,
        qualified_name=name,
        start_line=start,
        end_line=end,
        parent_name=parent,
    )


SOURCE = """\
import os

CONSTANT = 3


def first(a, b):
    return a + b


def second(value):
    # a comment
    return value * CONSTANT
"""


def test_one_chunk_per_function_plus_module_code() -> None:
    chunks = chunker().chunk_source_file(
        "mod.py",
        "python",
        SOURCE,
        [symbol("first", "function", 6, 7), symbol("second", "function", 10, 12)],
    )

    assert [(c.chunk_type, c.qualified_name, c.start_line, c.end_line) for c in chunks] == [
        ("module", None, 1, 5),  # imports and constants, up to the blank line
        ("symbol", "first", 6, 7),
        ("symbol", "second", 10, 12),
    ]
    # Content is exactly the lines of the range, so line numbers can be trusted.
    assert chunks[1].content == "def first(a, b):\n    return a + b"
    assert chunks[0].content.startswith("import os")


def test_symbol_metadata_is_preserved() -> None:
    method = symbol("TicketService.close_ticket", "method", 3, 4, parent="TicketService")
    chunks = chunker().chunk_source_file("svc.py", "python", "a\nb\nc\nd\ne\n", [method])

    chunk = next(c for c in chunks if c.chunk_type == "symbol")
    assert chunk.file_path == "svc.py"
    assert chunk.language == "python"
    assert (chunk.symbol_name, chunk.symbol_type) == ("close_ticket", "method")
    assert chunk.qualified_name == "TicketService.close_ticket"
    assert chunk.parent_symbol == "TicketService"
    assert chunk.symbol_id == method.id
    assert (chunk.start_line, chunk.end_line) == (3, 4)


def test_small_class_stays_one_chunk() -> None:
    source = "\n".join(f"line {number}" for number in range(1, 21)) + "\n"
    klass = symbol("Small", "class", 1, 20)
    klass.children = [symbol("Small.method", "method", 5, 8, parent="Small")]

    chunks = chunker(max_lines=60).chunk_source_file("m.py", "python", source, [klass])

    assert [(c.chunk_type, c.qualified_name) for c in chunks] == [("symbol", "Small")]


def test_large_class_becomes_header_plus_methods() -> None:
    source = "\n".join(f"line {number}" for number in range(1, 61)) + "\n"
    klass = symbol("Big", "class", 1, 60)
    klass.children = [
        symbol("Big.one", "method", 10, 25, parent="Big"),
        symbol("Big.two", "method", 30, 45, parent="Big"),
    ]

    chunks = chunker(max_lines=20).chunk_source_file("m.py", "python", source, [klass])

    kinds = [(c.chunk_type, c.qualified_name, c.start_line, c.end_line) for c in chunks]
    assert ("symbol_header", "Big", 1, 9) in kinds
    assert ("symbol", "Big.one", 10, 25) in kinds
    assert ("symbol", "Big.two", 30, 45) in kinds
    header = next(c for c in chunks if c.chunk_type == "symbol_header")
    assert header.metadata["members"] == ["one", "two"]


def test_oversized_function_is_split_into_overlapping_parts() -> None:
    source = "\n".join(f"    statement_{number}()" for number in range(1, 101)) + "\n"
    chunks = chunker(max_lines=30, overlap_lines=5).chunk_source_file(
        "big.py", "python", source, [symbol("huge", "function", 1, 100)]
    )

    assert all(chunk.chunk_type == "symbol_part" for chunk in chunks)
    assert all(chunk.qualified_name == "huge" for chunk in chunks)  # metadata survives splitting
    assert [chunk.metadata["part"] for chunk in chunks] == list(range(1, len(chunks) + 1))
    assert all(chunk.line_count <= 30 for chunk in chunks)
    assert chunks[0].end_line >= chunks[1].start_line  # parts overlap
    assert chunks[-1].end_line == 100  # nothing is lost


def test_windows_prefer_blank_lines() -> None:
    lines = (
        [f"a{number}" for number in range(1, 9)] + [""] + [f"b{number}" for number in range(1, 9)]
    )
    chunks = chunker(max_lines=12).chunk_text_file("plain.txt", "Text", "\n".join(lines) + "\n")

    assert chunks[0].end_line == 8  # split at the blank line, not mid-block


def test_comment_only_gaps_are_skipped() -> None:
    source = "def a():\n    pass\n\n\n# -- section --\n\n\ndef b():\n    pass\n"
    chunks = chunker().chunk_source_file(
        "m.py", "python", source, [symbol("a", "function", 1, 2), symbol("b", "function", 8, 9)]
    )

    assert [c.qualified_name for c in chunks] == ["a", "b"]


def test_markdown_is_split_at_headings() -> None:
    markdown = "# Title\n\nIntro.\n\n## Auth\n\nPasswords are hashed.\n\n## Billing\n\nRefunds.\n"

    chunks = chunker().chunk_text_file("docs/guide.md", "Markdown", markdown)

    assert [(c.symbol_name, c.chunk_type) for c in chunks] == [
        ("Title", "section"),
        ("Auth", "section"),
        ("Billing", "section"),
    ]
    assert chunks[1].content.startswith("## Auth")
    assert chunks[1].symbol_type == "section"


@pytest.mark.parametrize(
    ("path", "language", "expected"),
    [
        ("app/main.py", "Python", True),
        ("README.md", None, True),
        ("package-lock.json", "JSON", False),
        ("data/values.json", "JSON", False),
        ("uv.lock", None, False),
        ("logo.png", None, False),
    ],
)
def test_should_chunk(path: str, language: str | None, expected: bool) -> None:
    assert CodeChunker.should_chunk(path, language) is expected


def test_chunk_ids_are_deterministic_and_unique() -> None:
    first = chunk_fixture("support_desk", REPOSITORY_ID)
    second = chunk_fixture("support_desk", REPOSITORY_ID)

    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert len({chunk.chunk_id for chunk in first}) == len(first)
    # A different repository never shares chunk ids.
    other = chunk_fixture("support_desk", uuid.uuid4())
    assert not {chunk.chunk_id for chunk in first} & {chunk.chunk_id for chunk in other}


def test_chunk_ids_survive_moving_code() -> None:
    source = "def keep(x):\n    return x\n"
    original = chunker().chunk_source_file(
        "m.py", "python", source, [symbol("keep", "function", 1, 2)]
    )
    moved_source = "# a new header comment\n\n" + source
    moved = chunker().chunk_source_file(
        "m.py", "python", moved_source, [symbol("keep", "function", 3, 4)]
    )

    kept = next(c for c in moved if c.qualified_name == "keep")
    assert kept.chunk_id == original[0].chunk_id  # same symbol, same content, same id
    assert (kept.start_line, kept.end_line) == (3, 4)


def test_fixture_repository_chunks_cover_every_file() -> None:
    chunks = chunk_fixture("support_desk", REPOSITORY_ID)
    root = fixture_root("support_desk")

    expected = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    assert {chunk.file_path for chunk in chunks} == expected
    assert all(chunk.content for chunk in chunks)
    assert all(chunk.start_line <= chunk.end_line for chunk in chunks)


def test_index_text_includes_location_and_symbol() -> None:
    chunks = chunk_fixture("support_desk", REPOSITORY_ID)
    chunk = next(c for c in chunks if c.qualified_name == "hash_password")

    text = chunk.index_text()
    assert text.startswith("app/auth/passwords.py (python) - function hash_password")
    assert "pbkdf2_hmac" in text


def test_symbol_records_builds_the_tree() -> None:
    parent_id, child_id = uuid.uuid4(), uuid.uuid4()
    rows = [
        {
            "id": parent_id,
            "name": "Service",
            "kind": "class",
            "qualified_name": "Service",
            "start_line": 1,
            "end_line": 9,
            "parent_symbol_id": None,
        },
        {
            "id": child_id,
            "name": "run",
            "kind": "method",
            "qualified_name": "Service.run",
            "start_line": 3,
            "end_line": 5,
            "parent_symbol_id": parent_id,
        },
    ]

    records = symbol_records(rows)

    parent = next(record for record in records if record.id == parent_id)
    child = next(record for record in records if record.id == child_id)
    assert [item.name for item in parent.children] == ["run"]
    assert child.parent_name == "Service"
