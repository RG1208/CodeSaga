"""The hardened git wrapper, exercised with real git against local repositories.

No network access: GitHub behaviour is covered with a fake in the API tests.
"""

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app.ingestion.errors import GitCommandError, GitErrorKind, IngestionCancelledError
from app.ingestion.git import GitClient, _git_environment, _protocol_for
from tests.fakes import make_git_repository, run_git

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture
def git() -> GitClient:
    return GitClient(remote_timeout=30, clone_timeout=60)


@pytest.fixture
def source_repo(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "source"
    sha = make_git_repository(
        path,
        {"README.md": b"# Source\n", "src/main.py": b"print('hello')\n"},
        branch="trunk",
        extra_branch="feature/x",
    )
    return path, sha


def test_resolve_remote_reports_default_branch_and_commit(
    git: GitClient, source_repo: tuple[Path, str]
) -> None:
    path, sha = source_repo

    info = git.resolve_remote(str(path))

    assert (info.default_branch, info.branch, info.commit_sha) == ("trunk", "trunk", sha)


def test_resolve_remote_with_selected_branch(git: GitClient, source_repo: tuple[Path, str]) -> None:
    path, sha = source_repo

    info = git.resolve_remote(str(path), "feature/x")

    assert (info.default_branch, info.branch, info.commit_sha) == ("trunk", "feature/x", sha)


def test_resolve_remote_unknown_branch(git: GitClient, source_repo: tuple[Path, str]) -> None:
    with pytest.raises(GitCommandError) as caught:
        git.resolve_remote(str(source_repo[0]), "nope")

    assert caught.value.kind is GitErrorKind.BRANCH_NOT_FOUND


def test_resolve_remote_not_a_repository(git: GitClient, tmp_path: Path) -> None:
    with pytest.raises(GitCommandError) as caught:
        git.resolve_remote(str(tmp_path))

    assert caught.value.kind is GitErrorKind.NOT_FOUND


def test_resolve_remote_empty_repository(git: GitClient, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    run_git(empty, "init", "--quiet")

    with pytest.raises(GitCommandError) as caught:
        git.resolve_remote(str(empty))

    assert caught.value.kind is GitErrorKind.EMPTY_REPOSITORY


def test_clone_checks_out_branch_and_returns_sha(
    git: GitClient, source_repo: tuple[Path, str], tmp_path: Path
) -> None:
    path, sha = source_repo
    destination = tmp_path / "clone"

    cloned_sha = git.clone(str(path), "trunk", destination)

    assert cloned_sha == sha
    assert (destination / "src" / "main.py").read_text() == "print('hello')\n"
    commit = git.last_commit(destination)
    assert (commit.sha, commit.subject, commit.author_name) == (sha, "Initial commit", "Test")


def test_clone_unknown_branch_fails_cleanly(
    git: GitClient, source_repo: tuple[Path, str], tmp_path: Path
) -> None:
    with pytest.raises(GitCommandError) as caught:
        git.clone(str(source_repo[0]), "missing", tmp_path / "clone")

    assert caught.value.kind is GitErrorKind.BRANCH_NOT_FOUND


def test_clone_writes_symlinks_as_plain_files(git: GitClient, tmp_path: Path) -> None:
    source = tmp_path / "with-link"
    source.mkdir()
    (source / "link").symlink_to("/etc/passwd")
    make_git_repository(source, {"README.md": b"x\n"})

    destination = tmp_path / "clone"
    git.clone(str(source), "main", destination)

    link = destination / "link"
    assert not link.is_symlink()
    assert link.read_text() == "/etc/passwd"  # the link target as text, not the file


def test_clone_never_runs_repository_hooks_or_config_commands(
    git: GitClient, tmp_path: Path
) -> None:
    source = tmp_path / "malicious"
    make_git_repository(source, {"README.md": b"x\n"})
    marker = tmp_path / "PWNED"
    hook = source / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    run_git(source, "config", "core.fsmonitor", f"touch {marker}")
    run_git(source, "config", "core.hooksPath", str(source / ".git" / "hooks"))

    destination = tmp_path / "clone"
    git.clone(str(source), "main", destination)
    git.last_commit(destination)
    git.head_sha(destination)

    assert not marker.exists()
    assert not (destination / ".git" / "hooks" / "post-checkout").exists()


@pytest.mark.parametrize(
    "source",
    [
        "http://github.com/a/b.git",
        "https://gitlab.com/a/b.git",
        "ext::sh -c touch /tmp/pwned",
        "file:///etc",
        "relative/path",
        "--upload-pack=touch /tmp/pwned",
    ],
)
def test_only_github_https_or_absolute_paths_are_accepted(source: str) -> None:
    with pytest.raises(GitCommandError):
        _protocol_for(source)


def test_git_environment_drops_inherited_secrets_and_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_ASKPASS", "/usr/bin/evil")
    monkeypatch.setenv("GIT_SSH_COMMAND", "touch /tmp/pwned")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/home/me/.gitconfig")

    env = _git_environment()

    assert "GIT_ASKPASS" not in env
    assert "GIT_SSH_COMMAND" not in env
    assert "GITHUB_TOKEN" not in env
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_missing_git_binary_is_reported(source_repo: tuple[Path, str]) -> None:
    client = GitClient()
    client.executable = None

    with pytest.raises(GitCommandError) as caught:
        client.resolve_remote(str(source_repo[0]))

    assert caught.value.kind is GitErrorKind.UNAVAILABLE


def _sleeping_process() -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["sleep", "30"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


@pytest.mark.skipif(os.name != "posix", reason="uses the POSIX sleep command")
def test_cancel_event_kills_a_running_command(git: GitClient) -> None:
    process = _sleeping_process()
    cancelled = threading.Event()
    cancelled.set()
    started = time.monotonic()

    with pytest.raises(IngestionCancelledError):
        git._wait(process, timeout=30, cancel_event=cancelled)

    assert time.monotonic() - started < 5
    assert process.poll() is not None  # the process was killed


@pytest.mark.skipif(os.name != "posix", reason="uses the POSIX sleep command")
def test_timeout_kills_a_running_command(git: GitClient) -> None:
    process = _sleeping_process()

    with pytest.raises(GitCommandError) as caught:
        git._wait(process, timeout=0.2, cancel_event=None)

    assert caught.value.kind is GitErrorKind.TIMEOUT
    assert process.poll() is not None
