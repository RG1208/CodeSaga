"""Helpers for analyzer tests: load fixture projects and locate lines by content."""

from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "code"


def fixture_root(project: str) -> Path:
    return FIXTURES / project


def fixture_paths(project: str) -> list[str]:
    root = fixture_root(project)
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def fixture_files(project: str) -> dict[str, bytes]:
    root = fixture_root(project)
    return {path: (root / path).read_bytes() for path in fixture_paths(project)}


def read_fixture(project: str, path: str) -> bytes:
    return (fixture_root(project) / path).read_bytes()


def line_of(source: bytes, needle: str, occurrence: int = 1) -> int:
    """1-based line number of the n-th line containing `needle` (keeps tests readable
    and robust: expected line numbers are derived from the fixture, not hard-coded)."""
    seen = 0
    for number, line in enumerate(source.decode().splitlines(), start=1):
        if needle in line:
            seen += 1
            if seen == occurrence:
                return number
    raise AssertionError(f"{needle!r} not found {occurrence} time(s)")
