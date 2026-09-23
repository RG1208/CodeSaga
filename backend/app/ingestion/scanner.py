"""Repository analysis: walk a checkout and describe its contents.

This module only *reads* files. It never imports, executes, or builds anything
from the repository — manifests such as `setup.py` are recorded by name only.

Two steps, matching the indexing stages:

1. `scan_repository` (ANALYZING) walks the tree once, collecting file sizes,
   languages, manifests, README/LICENSE and the list of indexable files.
2. `index_file` (INDEXING) reads each indexable file to compute its line count
   and content hash, skipping binary files.
"""

import hashlib
import os
import stat
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ingestion.errors import RepositoryLimitExceededError
from app.ingestion.languages import (
    IGNORED_DIRECTORIES,
    LICENSE_PREFIXES,
    MANIFEST_FILENAMES,
    NON_PROGRAMMING_LANGUAGES,
    README_PREFIXES,
    detect_language,
)

MAX_INDEXED_PATH_LENGTH = 1024
_BINARY_SNIFF_BYTES = 8192
_MAX_LISTED_MANIFESTS = 50


@dataclass(frozen=True)
class ScannedFile:
    path: str  # POSIX-style, relative to the repository root
    language: str | None
    size_bytes: int


@dataclass
class LanguageStats:
    files: int = 0
    bytes: int = 0


@dataclass
class ScanResult:
    total_files: int = 0
    total_size_bytes: int = 0
    all_paths: list[str] = field(default_factory=list)  # every regular file, incl. binaries
    indexable_files: list[ScannedFile] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    languages: dict[str, LanguageStats] = field(default_factory=dict)
    manifests: list[str] = field(default_factory=list)
    readme_path: str | None = None
    license_path: str | None = None

    @property
    def primary_language(self) -> str | None:
        programming = {
            name: stats
            for name, stats in self.languages.items()
            if name not in NON_PROGRAMMING_LANGUAGES
        }
        candidates = programming or self.languages
        if not candidates:
            return None
        return max(candidates.items(), key=lambda item: (item[1].bytes, item[0]))[0]

    def language_breakdown(self) -> list[dict[str, Any]]:
        ordered = sorted(self.languages.items(), key=lambda item: (-item[1].bytes, item[0]))
        return [
            {"language": name, "files": stats.files, "bytes": stats.bytes}
            for name, stats in ordered
        ]


@dataclass(frozen=True)
class IndexedFile:
    path: str
    language: str | None
    size_bytes: int
    line_count: int
    content_sha256: str


def scan_repository(root: Path, *, max_files: int, max_file_bytes: int) -> ScanResult:
    """Walk `root` without following symlinks and classify every regular file."""
    result = ScanResult()
    root = root.resolve()

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        # Prune ignored directories in place so os.walk never descends into them.
        dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_DIRECTORIES)
        directory = Path(dirpath)
        relative_dir = directory.relative_to(root)

        for filename in sorted(filenames):
            full_path = directory / filename
            try:
                info = os.lstat(full_path)
            except OSError:
                result.skipped["unreadable"] += 1
                continue
            if not stat.S_ISREG(info.st_mode):  # symlinks, sockets, devices...
                result.skipped["not_regular_file"] += 1
                continue

            result.total_files += 1
            if result.total_files > max_files:
                raise RepositoryLimitExceededError(
                    f"Repository has more than {max_files:,} files, the configured limit."
                )
            result.total_size_bytes += info.st_size
            relative_path = (relative_dir / filename).as_posix()
            result.all_paths.append(relative_path)
            language = detect_language(filename)

            if language is not None:
                stats = result.languages.setdefault(language, LanguageStats())
                stats.files += 1
                stats.bytes += info.st_size
            _record_notable_file(result, relative_dir, relative_path, filename)

            if info.st_size > max_file_bytes:
                result.skipped["too_large"] += 1
            elif len(relative_path) > MAX_INDEXED_PATH_LENGTH:
                result.skipped["path_too_long"] += 1
            else:
                result.indexable_files.append(
                    ScannedFile(path=relative_path, language=language, size_bytes=info.st_size)
                )

    return result


def _record_notable_file(
    result: ScanResult, relative_dir: Path, relative_path: str, filename: str
) -> None:
    at_top_level = relative_dir == Path(".")
    lowered = filename.lower()
    if filename in MANIFEST_FILENAMES and len(result.manifests) < _MAX_LISTED_MANIFESTS:
        result.manifests.append(relative_path)
    if at_top_level and result.readme_path is None and lowered.startswith(README_PREFIXES):
        result.readme_path = relative_path
    if at_top_level and result.license_path is None and lowered.startswith(LICENSE_PREFIXES):
        result.license_path = relative_path


def read_text_file(root: Path, relative_path: str, max_bytes: int | None = None) -> bytes | None:
    """Read a file inside a checkout. Returns None if it is missing, too large or binary.

    `relative_path` must come from our own scan or index (never raw user input);
    O_NOFOLLOW additionally refuses to open a file that is a symlink.
    """
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(root / relative_path, flags), "rb") as handle:
            content = handle.read(max_bytes + 1) if max_bytes is not None else handle.read()
    except OSError:
        return None
    if max_bytes is not None and len(content) > max_bytes:
        return None
    if b"\x00" in content[:_BINARY_SNIFF_BYTES]:
        return None
    return content


def count_lines(content: bytes) -> int:
    return content.count(b"\n") + (1 if content and not content.endswith(b"\n") else 0)


def index_file(root: Path, scanned: ScannedFile) -> IndexedFile | None:
    """Read one file and describe it. Returns None for binary or unreadable files."""
    content = read_text_file(root, scanned.path)
    if content is None:
        return None
    return IndexedFile(
        path=scanned.path,
        language=scanned.language,
        size_bytes=len(content),
        line_count=count_lines(content),
        content_sha256=hashlib.sha256(content).hexdigest(),
    )
