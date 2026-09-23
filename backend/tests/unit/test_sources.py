"""Validation of repository URLs, branch names and local paths (security boundary)."""

from pathlib import Path

import pytest

from app.ingestion.errors import InvalidRepositorySourceError
from app.ingestion.sources import (
    parse_github_url,
    validate_branch_name,
    validate_local_repository_path,
)

# --- GitHub URLs -------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "owner", "name"),
    [
        ("https://github.com/pallets/markupsafe", "pallets", "markupsafe"),
        ("https://github.com/pallets/markupsafe.git", "pallets", "markupsafe"),
        ("https://github.com/pallets/markupsafe/", "pallets", "markupsafe"),
        ("  https://github.com/pallets/markupsafe  ", "pallets", "markupsafe"),
        ("https://www.github.com/vercel/next.js", "vercel", "next.js"),
        ("https://GitHub.com/Microsoft/TypeScript", "Microsoft", "TypeScript"),
        ("https://github.com/a-b/repo_name-1.0", "a-b", "repo_name-1.0"),
    ],
)
def test_parse_valid_github_urls(url: str, owner: str, name: str) -> None:
    ref = parse_github_url(url)

    assert (ref.owner, ref.name) == (owner, name)
    assert ref.clone_url == f"https://github.com/{owner}/{name}.git"


def test_canonical_url_is_lowercase_for_duplicate_detection() -> None:
    assert (
        parse_github_url("https://github.com/Microsoft/TypeScript.git").canonical_url
        == parse_github_url("https://github.com/microsoft/typescript").canonical_url
        == "https://github.com/microsoft/typescript"
    )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "github.com/pallets/markupsafe",  # no scheme
        "http://github.com/pallets/markupsafe",  # not https
        "git@github.com:pallets/markupsafe.git",  # SSH
        "ssh://git@github.com/pallets/markupsafe.git",
        "file:///etc/passwd",
        "ext::sh -c touch% /tmp/pwned",  # git remote-helper command execution
        "https://gitlab.com/pallets/markupsafe",
        "https://github.com.evil.com/pallets/markupsafe",
        "https://evil.com/github.com/pallets/markupsafe",
        "https://user:token@github.com/pallets/markupsafe",  # credentials
        "https://github.com:8443/pallets/markupsafe",  # port
        "https://github.com/pallets",  # missing repo
        "https://github.com/pallets/markupsafe/tree/main",  # extra segments
        "https://github.com/pallets/markupsafe?tab=readme",
        "https://github.com/pallets/markupsafe#readme",
        "https://github.com/pallets/..",
        "https://github.com/../etc",
        "https://github.com/pallets/%2e%2e",  # encoded traversal
        "https://github.com/-pallets/markupsafe",  # owner cannot start with '-'
        "https://github.com/pal lets/markupsafe",
        "https://github.com/pallets/markup;safe",
        "https://github.com/pallets/$(whoami)",
        "https://github.com/pallets/markupsafe\n--upload-pack=touch",
        "https://github.com/" + "a" * 40 + "/repo",  # owner too long
    ],
)
def test_reject_invalid_github_urls(url: str) -> None:
    with pytest.raises(InvalidRepositorySourceError):
        parse_github_url(url)


def test_ssh_url_error_explains_https_alternative() -> None:
    with pytest.raises(InvalidRepositorySourceError, match="HTTPS"):
        parse_github_url("git@github.com:pallets/markupsafe.git")


# --- Branch names ------------------------------------------------------------


@pytest.mark.parametrize("branch", ["main", "develop", "feature/login", "release-1.2", "v2.x"])
def test_valid_branch_names(branch: str) -> None:
    assert validate_branch_name(branch) == branch


@pytest.mark.parametrize(
    "branch",
    [
        "",
        "-b",  # would look like an option
        "--upload-pack=touch /tmp/pwned",
        "a..b",
        "has space",
        "semi;colon",
        "$(whoami)",
        "back`tick`",
        "tilde~1",
        "caret^",
        "colon:x",
        "question?",
        "star*",
        "bracket[",
        "back\\slash",
        "ends/",
        "/starts",
        "ends.",
        "branch.lock",
        "double//slash",
        "at@{brace",
        "@",
        ".hidden",
        "feature/.hidden",
        "new\nline",
        "x" * 256,
    ],
)
def test_invalid_branch_names(branch: str) -> None:
    with pytest.raises(InvalidRepositorySourceError):
        validate_branch_name(branch)


# --- Local paths -------------------------------------------------------------


@pytest.fixture
def local_repo(local_repos_root: Path) -> Path:
    repo = local_repos_root / "my-repo"
    (repo / ".git").mkdir(parents=True)
    return repo


def test_valid_local_path_is_resolved(local_repo: Path, local_repos_root: Path) -> None:
    assert (
        validate_local_repository_path(str(local_repo), [local_repos_root]) == local_repo.resolve()
    )


@pytest.mark.parametrize("raw", ["", "   ", "relative/path", "~/my-repo", "my-repo"])
def test_local_path_must_be_absolute(raw: str, local_repos_root: Path) -> None:
    with pytest.raises(InvalidRepositorySourceError):
        validate_local_repository_path(raw, [local_repos_root])


def test_local_path_rejects_dot_dot_traversal(local_repo: Path, local_repos_root: Path) -> None:
    sneaky = f"{local_repos_root}/my-repo/../../../etc"
    with pytest.raises(InvalidRepositorySourceError, match=r"\.\."):
        validate_local_repository_path(sneaky, [local_repos_root])


def test_local_path_rejects_null_byte(local_repos_root: Path) -> None:
    with pytest.raises(InvalidRepositorySourceError):
        validate_local_repository_path(f"{local_repos_root}/my-repo\x00", [local_repos_root])


def test_local_path_outside_allowed_roots_is_rejected(
    tmp_path: Path, local_repos_root: Path
) -> None:
    outside = tmp_path / "elsewhere" / "repo"
    (outside / ".git").mkdir(parents=True)

    with pytest.raises(InvalidRepositorySourceError, match="allowed directory"):
        validate_local_repository_path(str(outside), [local_repos_root])


def test_symlink_escaping_allowed_root_is_rejected(tmp_path: Path, local_repos_root: Path) -> None:
    outside = tmp_path / "secret-repo"
    (outside / ".git").mkdir(parents=True)
    link = local_repos_root / "innocent-link"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidRepositorySourceError, match="allowed directory"):
        validate_local_repository_path(str(link), [local_repos_root])


def test_sibling_directory_with_common_prefix_is_not_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "repos"
    root.mkdir()
    sibling = tmp_path / "repos-evil" / "repo"
    (sibling / ".git").mkdir(parents=True)

    with pytest.raises(InvalidRepositorySourceError, match="allowed directory"):
        validate_local_repository_path(str(sibling), [root])


def test_local_path_must_exist(local_repos_root: Path) -> None:
    with pytest.raises(InvalidRepositorySourceError, match="does not exist"):
        validate_local_repository_path(str(local_repos_root / "missing"), [local_repos_root])


def test_local_path_must_be_a_directory(local_repos_root: Path) -> None:
    file_path = local_repos_root / "file.txt"
    file_path.write_text("x")

    with pytest.raises(InvalidRepositorySourceError, match="not a directory"):
        validate_local_repository_path(str(file_path), [local_repos_root])


def test_local_path_must_be_a_git_repository(local_repos_root: Path) -> None:
    plain = local_repos_root / "plain-dir"
    plain.mkdir()

    with pytest.raises(InvalidRepositorySourceError, match="not a git repository"):
        validate_local_repository_path(str(plain), [local_repos_root])
