"""Metadata extraction and file indexing — pure filesystem reads, nothing executed."""

import hashlib
from pathlib import Path

import pytest

from app.ingestion.errors import RepositoryLimitExceededError
from app.ingestion.languages import detect_language
from app.ingestion.scanner import index_file, scan_repository


def _write(root: Path, files: dict[str, bytes]) -> None:
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _write(
        root,
        {
            "README.md": b"# Title\n",
            "LICENSE.txt": b"MIT\n",
            "package.json": b"{}\n",
            "backend/pyproject.toml": b"[project]\n",
            "backend/app/main.py": b"print('never executed')\n" * 10,
            "backend/app/models.py": b"x = 1\n",
            "web/src/index.tsx": b"export {};\n",
            "Dockerfile": b"FROM scratch\n",
            "docs/guide.md": b"# Guide\n",
            "image.png": b"\x89PNG\x00\x00\x00",
            "big.log": b"x" * 5000,
            "node_modules/dep/index.js": b"module.exports = 1;\n",
            ".git/config": b"[core]\n",
            "backend/__pycache__/main.cpython-312.pyc": b"\x00\x01",
        },
    )
    (root / "link-to-readme").symlink_to(root / "README.md")
    return root


def test_scan_counts_files_and_skips_ignored_directories(repo: Path) -> None:
    result = scan_repository(repo, max_files=1000, max_file_bytes=1024)

    paths = {item.path for item in result.indexable_files}
    assert "backend/app/main.py" in paths
    assert not any(path.startswith(("node_modules/", ".git/")) for path in paths)
    assert not any("__pycache__" in path for path in paths)
    assert result.total_files == 11  # symlink and ignored directories excluded
    assert result.skipped["not_regular_file"] == 1  # the symlink
    assert result.skipped["too_large"] == 1  # big.log
    assert "big.log" not in paths


def test_scan_detects_languages_and_primary_language(repo: Path) -> None:
    result = scan_repository(repo, max_files=1000, max_file_bytes=1024)

    breakdown = {item["language"]: item for item in result.language_breakdown()}
    assert breakdown["Python"]["files"] == 2
    assert breakdown["TypeScript"]["files"] == 1
    assert breakdown["Markdown"]["files"] == 2
    # Markdown/JSON never win "primary language" over real code.
    assert result.primary_language == "Python"


def test_scan_finds_readme_license_and_manifests(repo: Path) -> None:
    result = scan_repository(repo, max_files=1000, max_file_bytes=1024)

    assert result.readme_path == "README.md"
    assert result.license_path == "LICENSE.txt"
    assert set(result.manifests) == {"package.json", "backend/pyproject.toml", "Dockerfile"}


def test_scan_enforces_file_count_limit(repo: Path) -> None:
    with pytest.raises(RepositoryLimitExceededError):
        scan_repository(repo, max_files=3, max_file_bytes=1024)


def test_scan_of_empty_directory(tmp_path: Path) -> None:
    result = scan_repository(tmp_path, max_files=10, max_file_bytes=10)

    assert result.total_files == 0
    assert result.primary_language is None
    assert result.readme_path is None


def test_index_file_computes_lines_and_hash(repo: Path) -> None:
    result = scan_repository(repo, max_files=1000, max_file_bytes=1024)
    scanned = next(item for item in result.indexable_files if item.path == "backend/app/main.py")

    indexed = index_file(repo, scanned)

    content = (repo / "backend/app/main.py").read_bytes()
    assert indexed is not None
    assert indexed.line_count == 10
    assert indexed.size_bytes == len(content)
    assert indexed.content_sha256 == hashlib.sha256(content).hexdigest()
    assert indexed.language == "Python"


def test_index_file_counts_last_line_without_newline(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"one\ntwo")
    scanned = scan_repository(tmp_path, max_files=10, max_file_bytes=100).indexable_files[0]

    assert index_file(tmp_path, scanned).line_count == 2  # type: ignore[union-attr]


def test_index_file_skips_binary_files(repo: Path) -> None:
    result = scan_repository(repo, max_files=1000, max_file_bytes=1024)
    image = next(item for item in result.indexable_files if item.path == "image.png")

    assert index_file(repo, image) is None


def test_index_file_refuses_to_follow_a_swapped_in_symlink(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"x = 1\n")
    scanned = scan_repository(tmp_path, max_files=10, max_file_bytes=100).indexable_files[0]
    secret = tmp_path.parent / f"{tmp_path.name}-secret.txt"
    secret.write_text("secret")
    (tmp_path / "a.py").unlink()
    (tmp_path / "a.py").symlink_to(secret)

    assert index_file(tmp_path, scanned) is None


@pytest.mark.parametrize(
    ("filename", "language"),
    [
        ("main.py", "Python"),
        ("App.TSX", "TypeScript"),
        ("Dockerfile", "Dockerfile"),
        ("styles.scss", "SCSS"),
        (".gitignore", None),
        ("Makefile", "Makefile"),
        ("notes", None),
        ("archive.tar.gz", None),
    ],
)
def test_detect_language(filename: str, language: str | None) -> None:
    assert detect_language(filename) == language
