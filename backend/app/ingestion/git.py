"""A hardened wrapper around the `git` command-line tool.

Why a subprocess and not a Python git library? The git CLI is the reference
implementation, handles every transport and edge case, and is easy to sandbox:

* Commands are argument lists — no shell is ever involved, so characters such as
  `;`, `|` or `$(...)` in user input have no special meaning.
* `--` separates options from URLs/paths, so a value can never become an option.
* The environment is rebuilt from an allowlist and system/global git config is
  ignored, so settings such as `url.<x>.insteadOf`, credential helpers or
  `core.fsmonitor` (which can run programs) cannot influence us.
* `-c` overrides disable hooks, credential prompts and submodules, check files
  out with symlinks as plain files, and allow only the one expected protocol.
* Every command has a timeout, and the whole process group is killed on expiry.
"""

import contextlib
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from app.ingestion.errors import GitCommandError, GitErrorKind, IngestionCancelledError

logger = logging.getLogger(__name__)

_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_ENV_ALLOWLIST = (
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
)  # fmt: skip
_MAX_ERROR_LENGTH = 300
_POLL_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True)
class RemoteInfo:
    default_branch: str
    branch: str
    commit_sha: str


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    author_name: str
    authored_at: datetime
    subject: str


def _protocol_for(source: str) -> str:
    """Only two source shapes are ever accepted: GitHub HTTPS URLs and absolute paths."""
    if source.startswith("https://"):
        if (urlsplit(source).hostname or "").lower() not in {"github.com", "www.github.com"}:
            raise GitCommandError("Only github.com URLs may be cloned.", GitErrorKind.FAILED)
        return "https"
    if Path(source).is_absolute():
        return "file"
    raise GitCommandError("Unsupported repository source.", GitErrorKind.FAILED)


def _git_environment() -> dict[str, str]:
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",  # fail instead of asking for a username/password
            "GIT_CONFIG_NOSYSTEM": "1",  # ignore /etc/gitconfig
            "GIT_CONFIG_GLOBAL": os.devnull,  # ignore ~/.gitconfig
            "GIT_LFS_SKIP_SMUDGE": "1",  # never download LFS objects
            "LC_ALL": "C",  # stable, English error messages for classification
        }
    )
    return env


def _classify_failure(stderr: str) -> tuple[GitErrorKind, str]:
    text = stderr.lower()
    if "remote branch" in text and "not found" in text:
        return GitErrorKind.BRANCH_NOT_FOUND, "The requested branch does not exist."
    if any(
        marker in text
        for marker in (
            "repository not found",
            "could not read username",
            "authentication failed",
            "terminal prompts disabled",
            "does not appear to be a git repository",
            "not a git repository",
            "returned error: 404",
            "returned error: 403",
        )
    ):
        return (
            GitErrorKind.NOT_FOUND,
            "Repository not found or not public. Only public GitHub repositories are supported.",
        )
    if any(
        marker in text
        for marker in (
            "could not resolve host",
            "failed to connect",
            "connection timed out",
            "network is unreachable",
            "connection refused",
            "operation too slow",
            "unable to access",
        )
    ):
        return GitErrorKind.NETWORK, "Could not reach the repository host. Check your network."
    last_line = next((line for line in reversed(stderr.strip().splitlines()) if line), "")
    return GitErrorKind.FAILED, f"git failed: {last_line[:_MAX_ERROR_LENGTH]}".rstrip(": ")


class GitClient:
    def __init__(self, *, remote_timeout: float = 30, clone_timeout: float = 600) -> None:
        self.remote_timeout = remote_timeout
        self.clone_timeout = clone_timeout
        self.executable = shutil.which("git")

    # -- public operations -------------------------------------------------

    def resolve_remote(self, source: str, branch: str | None = None) -> RemoteInfo:
        """Confirm a repository is reachable and resolve its default branch and commit.

        Uses `git ls-remote`, which reads refs without downloading any files.
        """
        refs = ["HEAD"] + ([f"refs/heads/{branch}"] if branch else [])
        output = self._run(
            ["ls-remote", "--symref", "--", source, *refs],
            protocol=_protocol_for(source),
            timeout=self.remote_timeout,
        )

        default_branch: str | None = None
        shas: dict[str, str] = {}
        for line in output.splitlines():
            sha_or_symref, _, ref = line.partition("\t")
            if sha_or_symref.startswith("ref: refs/heads/") and ref == "HEAD":
                default_branch = sha_or_symref.removeprefix("ref: refs/heads/")
            elif _SHA_RE.fullmatch(sha_or_symref):
                shas[ref] = sha_or_symref

        if not shas:
            raise GitCommandError(
                "The repository is empty (it has no commits).", GitErrorKind.EMPTY_REPOSITORY
            )
        if branch:
            commit_sha = shas.get(f"refs/heads/{branch}")
            if commit_sha is None:
                raise GitCommandError(
                    f"Branch '{branch}' does not exist in this repository.",
                    GitErrorKind.BRANCH_NOT_FOUND,
                )
            return RemoteInfo(
                default_branch=default_branch or branch, branch=branch, commit_sha=commit_sha
            )
        if default_branch is None or "HEAD" not in shas:
            raise GitCommandError(
                "Could not determine the default branch. Please specify a branch.",
                GitErrorKind.FAILED,
            )
        return RemoteInfo(
            default_branch=default_branch, branch=default_branch, commit_sha=shas["HEAD"]
        )

    def clone(
        self,
        source: str,
        branch: str,
        destination: Path,
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Shallow-clone a single branch into `destination` and return the checked-out SHA.

        Setting `cancel_event` (e.g. on server shutdown) aborts the clone promptly.
        """
        protocol = _protocol_for(source)
        args = ["clone", "--depth", "1", "--single-branch", "--no-tags", "--branch", branch]
        if protocol == "file":
            # Use the normal transport instead of copying .git internals directly.
            args.append("--no-local")
        self._run(
            [*args, "--", source, str(destination)],
            protocol=protocol,
            timeout=self.clone_timeout,
            cancel_event=cancel_event,
        )
        return self.head_sha(destination)

    def head_sha(self, checkout: Path) -> str:
        sha = self._run(["-C", str(checkout), "rev-parse", "--verify", "HEAD"]).strip()
        if not _SHA_RE.fullmatch(sha):
            raise GitCommandError("Could not read the checked-out commit.", GitErrorKind.FAILED)
        return sha

    def last_commit(self, checkout: Path) -> CommitInfo:
        output = self._run(
            [
                "-C",
                str(checkout),
                "log",
                "-1",
                "--no-show-signature",
                "--format=%H%x1f%an%x1f%aI%x1f%s",
            ]
        )
        sha, author_name, authored_at, subject = output.rstrip("\n").split("\x1f", 3)
        return CommitInfo(
            sha=sha,
            author_name=author_name,
            authored_at=datetime.fromisoformat(authored_at),
            subject=subject,
        )

    # -- process handling --------------------------------------------------

    def _command(self, args: list[str], protocol: str | None) -> list[str]:
        if self.executable is None:
            raise GitCommandError("git is not installed on the server.", GitErrorKind.UNAVAILABLE)
        hardening = [
            "protocol.allow=never",
            *([f"protocol.{protocol}.allow=always"] if protocol else []),
            f"core.hooksPath={os.devnull}",
            "core.symlinks=false",
            "core.fsmonitor=false",
            "credential.helper=",
            "submodule.recurse=false",
            "advice.detachedHead=false",
            # Abort transfers that stall below 1 KB/s for a minute.
            "http.lowSpeedLimit=1000",
            "http.lowSpeedTime=60",
        ]
        command = [self.executable]
        for option in hardening:
            command += ["-c", option]
        return command + args

    def _run(
        self,
        args: list[str],
        *,
        protocol: str | None = None,
        timeout: float = 60,
        cancel_event: threading.Event | None = None,
    ) -> str:
        command = self._command(args, protocol)
        logger.debug("running git", extra={"git_args": args})
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_environment(),
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name == "posix",  # own process group, see _kill
        )
        stdout, stderr = self._wait(process, timeout=timeout, cancel_event=cancel_event)

        if process.returncode != 0:
            kind, message = _classify_failure(stderr)
            logger.info(
                "git command failed",
                extra={"git_args": args, "returncode": process.returncode, "stderr": stderr[-500:]},
            )
            raise GitCommandError(message, kind)
        return stdout

    def _wait(
        self,
        process: subprocess.Popen[str],
        *,
        timeout: float,
        cancel_event: threading.Event | None,
    ) -> tuple[str, str]:
        deadline = time.monotonic() + timeout
        while True:
            try:
                return process.communicate(timeout=_POLL_INTERVAL_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            if cancel_event is not None and cancel_event.is_set():
                self._kill(process)
                raise IngestionCancelledError()
            if time.monotonic() >= deadline:
                self._kill(process)
                raise GitCommandError(
                    f"git did not finish within {int(timeout)} seconds.", GitErrorKind.TIMEOUT
                )

    @staticmethod
    def _kill(process: subprocess.Popen[str]) -> None:
        # git spawns helpers (git-remote-https, index-pack); kill the whole group.
        if os.name == "posix":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
