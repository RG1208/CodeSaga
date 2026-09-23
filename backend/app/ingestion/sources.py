"""Validation of user-supplied repository sources.

Everything here is pure validation: nothing is fetched or executed. Every value
that later reaches a `git` command line or the filesystem passes through one of
these functions first.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.ingestion.errors import InvalidRepositorySourceError

GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})

# GitHub rules: owners are 1-39 alphanumerics or single hyphens (not at the ends);
# repository names are 1-100 characters of letters, digits, '.', '_' and '-'.
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_MAX_URL_LENGTH = 2048


@dataclass(frozen=True)
class GitHubRepositoryRef:
    owner: str
    name: str

    @property
    def canonical_url(self) -> str:
        """Lower-cased so the same repository is always stored under the same URL."""
        return f"https://github.com/{self.owner}/{self.name}".lower()

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}.git"


def parse_github_url(raw_url: str) -> GitHubRepositoryRef:
    """Parse `https://github.com/<owner>/<repo>` (optionally `.git` or a trailing slash)."""
    url = raw_url.strip()
    if not url:
        raise InvalidRepositorySourceError("Repository URL is required.")
    if len(url) > _MAX_URL_LENGTH:
        raise InvalidRepositorySourceError("Repository URL is too long.")
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in url):
        raise InvalidRepositorySourceError(
            "Repository URL must not contain spaces or control characters."
        )
    if url.startswith("git@") or url.startswith("ssh://"):
        raise InvalidRepositorySourceError(
            "SSH URLs are not supported. Use the HTTPS form: https://github.com/<owner>/<repo>"
        )

    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise InvalidRepositorySourceError("Repository URL is malformed.") from exc

    if parts.scheme != "https":
        raise InvalidRepositorySourceError(
            "Only https:// GitHub URLs are supported, e.g. https://github.com/<owner>/<repo>"
        )
    if parts.username is not None or parts.password is not None or port is not None:
        raise InvalidRepositorySourceError(
            "Repository URL must not contain credentials or a port number."
        )
    if (parts.hostname or "").lower() not in GITHUB_HOSTS:
        raise InvalidRepositorySourceError("Only repositories hosted on github.com are supported.")
    if parts.query or parts.fragment:
        raise InvalidRepositorySourceError("Repository URL must not contain '?' or '#' parts.")
    if "%" in parts.path or "\\" in parts.path:
        raise InvalidRepositorySourceError("Repository URL contains invalid characters.")

    segments = parts.path.strip("/").split("/")
    if len(segments) != 2:
        raise InvalidRepositorySourceError(
            "Use the repository's main URL: https://github.com/<owner>/<repo>"
        )
    owner, name = segments
    if name.endswith(".git"):
        name = name[: -len(".git")]

    if not _OWNER_RE.fullmatch(owner):
        raise InvalidRepositorySourceError(f"'{owner}' is not a valid GitHub owner name.")
    if not _REPO_NAME_RE.fullmatch(name) or name in {".", ".."}:
        raise InvalidRepositorySourceError(f"'{name}' is not a valid GitHub repository name.")
    return GitHubRepositoryRef(owner=owner, name=name)


# An allowlist, stricter than git itself: git would also accept characters such as
# ';', '$' or '`'. They are harmless without a shell, but no real branch needs them.
_BRANCH_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9._/+#@-]+$")


def validate_branch_name(raw_branch: str) -> str:
    """Enforce git's ref-name rules (`git check-ref-format --branch`) without calling git."""
    branch = raw_branch.strip()
    invalid = (
        not branch
        or len(branch) > 255
        or _BRANCH_ALLOWED_CHARS.fullmatch(branch) is None
        or branch.startswith(("-", "/"))  # a leading '-' could be read as a git option
        or branch.endswith(("/", ".", ".lock"))
        or ".." in branch
        or "//" in branch
        or "@{" in branch
        or branch == "@"
        or any(component.startswith(".") for component in branch.split("/"))
    )
    if invalid:
        raise InvalidRepositorySourceError(
            f"'{raw_branch}' is not a valid branch name. Use letters, digits and . _ / + # @ -"
        )
    return branch


def validate_local_repository_path(raw_path: str, allowed_roots: Sequence[Path]) -> Path:
    """Return the resolved path of a local git working copy inside an allowed root.

    Symlinks are resolved *before* the containment check, so a link that points
    outside the allowed roots is rejected too.
    """
    path_text = raw_path.strip()
    if not path_text:
        raise InvalidRepositorySourceError("Repository path is required.")
    if "\x00" in path_text or len(path_text) > 4096:
        raise InvalidRepositorySourceError("Repository path is invalid.")

    path = Path(path_text)
    if not path.is_absolute():
        raise InvalidRepositorySourceError("Use an absolute path, e.g. /home/you/projects/my-repo")
    if ".." in path.parts:
        raise InvalidRepositorySourceError("Repository path must not contain '..'.")

    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InvalidRepositorySourceError(f"Path does not exist: {path_text}") from exc

    if not any(resolved.is_relative_to(root.resolve()) for root in allowed_roots):
        allowed = ", ".join(str(root) for root in allowed_roots) or "(none configured)"
        raise InvalidRepositorySourceError(
            f"Local repositories must be inside an allowed directory: {allowed}"
        )
    if not resolved.is_dir():
        raise InvalidRepositorySourceError("Repository path is not a directory.")
    if not (resolved / ".git").exists():
        raise InvalidRepositorySourceError(
            "Path is not a git repository (no .git directory found)."
        )
    return resolved
