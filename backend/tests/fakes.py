"""Test doubles and helpers shared across the test suite."""

import os
import subprocess
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.ingestion.errors import GitCommandError, GitErrorKind
from app.ingestion.git import CommitInfo, GitClient, RemoteInfo
from app.retrieval.rerankers import Reranker
from app.retrieval.tokenizer import tokenize

MAIN_SHA = "a" * 40
DEVELOP_SHA = "b" * 40

DEFAULT_FILES: dict[str, bytes] = {
    "README.md": b"# Demo\n\nA demo repository.\n",
    "LICENSE": b"MIT\n",
    "pyproject.toml": b"[project]\nname = 'demo'\n",
    "src/app.py": b"def main():\n    return 42\n",
    "src/util.py": b"X = 1\nY = 2\nZ = 3\n",
    "web/index.ts": b"export const answer = 42;\n",
    "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00binary",
    "node_modules/lib/index.js": b"module.exports = {};\n",
}


class FakeGitClient(GitClient):
    """Behaves like GitClient without touching the network or running git."""

    def __init__(self) -> None:
        super().__init__()
        self.branches = {"main": MAIN_SHA, "develop": DEVELOP_SHA}
        self.files = dict(DEFAULT_FILES)
        self.resolve_error: GitCommandError | None = None
        self.clone_error: Exception | None = None
        self.calls: list[tuple[str, ...]] = []

    def resolve_remote(self, source: str, branch: str | None = None) -> RemoteInfo:
        self.calls.append(("resolve_remote", source, branch or ""))
        if self.resolve_error is not None:
            raise self.resolve_error
        chosen = branch or "main"
        if chosen not in self.branches:
            raise GitCommandError(
                f"Branch '{chosen}' does not exist in this repository.",
                GitErrorKind.BRANCH_NOT_FOUND,
            )
        return RemoteInfo(default_branch="main", branch=chosen, commit_sha=self.branches[chosen])

    def clone(
        self,
        source: str,
        branch: str,
        destination: Path,
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        self.calls.append(("clone", source, branch))
        if self.clone_error is not None:
            raise self.clone_error
        for relative, content in self.files.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return self.branches[branch]

    def last_commit(self, checkout: Path) -> CommitInfo:
        return CommitInfo(
            sha=MAIN_SHA,
            author_name="Ada Lovelace",
            authored_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            subject="Initial commit",
        )


def _git(cwd: Path, *args: str) -> str:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(cwd),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]
    result = subprocess.run(
        ["git", *identity, *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def make_git_repository(
    path: Path, files: dict[str, bytes], *, branch: str = "main", extra_branch: str | None = None
) -> str:
    """Create a real git repository with one commit; returns the commit SHA."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "--quiet", f"--initial-branch={branch}")
    for relative, content in files.items():
        target = path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _git(path, "add", "--all")
    _git(path, "commit", "--quiet", "--message", "Initial commit")
    if extra_branch:
        _git(path, "branch", extra_branch)
    return _git(path, "rev-parse", "HEAD")


def run_git(path: Path, *args: str) -> str:
    return _git(path, *args)


class KeywordReranker(Reranker):
    """Deterministic stand-in for a cross-encoder: scores by query-term coverage.

    Real reranking needs a neural model and a download; tests need repeatable numbers.
    """

    name = "keyword"
    model_id = "keyword-overlap"

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        terms = set(tokenize(query))
        scores = []
        for document in documents:
            tokens = tokenize(document)
            if not tokens or not terms:
                scores.append(0.0)
                continue
            matched = sum(1 for token in tokens if token in terms)
            scores.append(round(matched / len(tokens) + len(terms & set(tokens)) / len(terms), 6))
        return scores
