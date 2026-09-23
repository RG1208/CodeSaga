"""The background ingestion pipeline: clone → analyze → index → complete/fail."""

import shutil
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.errors import GitCommandError, GitErrorKind
from app.ingestion.git import GitClient
from app.ingestion.indexer import INTERRUPTED_MESSAGE, RepositoryIndexer, recover_interrupted_jobs
from app.jobs.base import JobContext
from app.models import (
    CodeChunk,
    CodeFile,
    CodeRelationship,
    CodeSymbol,
    IndexingJob,
    JobStatus,
    Project,
    Repository,
    RepositoryFile,
    RepositorySourceType,
    RepositoryStatus,
)
from tests.analysis.helpers import fixture_files
from tests.fakes import MAIN_SHA, FakeGitClient, make_git_repository


def _create_repository(
    session: Session,
    *,
    source_type: RepositorySourceType = RepositorySourceType.GITHUB,
    url: str = "https://github.com/demo/app",
    branch: str = "main",
) -> Repository:
    project = Project(name=f"project-{uuid.uuid4().hex[:8]}")
    session.add(project)
    session.flush()
    repository = Repository(
        project_id=project.id,
        name="app",
        owner="demo",
        url=url,
        source_type=source_type,
        default_branch=branch,
        branch=branch,
    )
    session.add(repository)
    session.commit()
    return repository


def _queue_job(session: Session, repository: Repository) -> IndexingJob:
    job = IndexingJob(repository_id=repository.id, branch=repository.branch)
    repository.status = RepositoryStatus.QUEUED
    session.add(job)
    session.commit()
    return job


def _reload(session: Session, *objects: object) -> None:
    session.expire_all()
    for obj in objects:
        session.refresh(obj)


def test_successful_run_indexes_repository(job_context: JobContext, db_session: Session) -> None:
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)

    RepositoryIndexer(job_context).run(job.id)

    _reload(db_session, repository, job)
    assert repository.status is RepositoryStatus.COMPLETED
    assert repository.status_message is None
    assert repository.commit_sha == MAIN_SHA
    assert repository.last_indexed_at is not None
    assert job.status is JobStatus.SUCCEEDED
    assert job.stage is RepositoryStatus.COMPLETED
    assert job.started_at is not None and job.finished_at is not None
    assert job.files_total == job.files_processed

    checkout = Path(repository.local_path or "")
    assert checkout == job_context.storage.path_for(repository.id)
    assert (checkout / "src" / "app.py").exists()
    assert not job_context.storage.temp_root.exists() or not any(
        job_context.storage.temp_root.iterdir()
    )

    paths = set(db_session.scalars(select(RepositoryFile.path)))
    assert {"README.md", "src/app.py", "src/util.py", "web/index.ts"} <= paths
    assert "assets/logo.png" not in paths  # binary
    assert not any(path.startswith("node_modules/") for path in paths)


def test_metadata_is_extracted(job_context: JobContext, db_session: Session) -> None:
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)

    RepositoryIndexer(job_context).run(job.id)

    _reload(db_session, repository)
    metadata = repository.repo_metadata or {}
    assert metadata["primary_language"] == "Python"
    assert metadata["readme_path"] == "README.md"
    assert metadata["license_path"] == "LICENSE"
    assert metadata["manifests"] == ["pyproject.toml"]
    assert metadata["total_files"] == 7  # node_modules excluded
    assert metadata["indexed_files"] == 6
    assert metadata["skipped_files"] == {"binary_or_unreadable": 1}
    assert metadata["last_commit"]["subject"] == "Initial commit"
    languages = {item["language"]: item["files"] for item in metadata["languages"]}
    assert languages == {"Python": 2, "TypeScript": 1, "Markdown": 1, "TOML": 1}


def test_clone_failure_marks_job_and_repository_failed(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.clone_error = GitCommandError("Could not reach the host.", GitErrorKind.NETWORK)
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)

    RepositoryIndexer(job_context).run(job.id)

    _reload(db_session, repository, job)
    assert repository.status is RepositoryStatus.FAILED
    assert repository.status_message == "Could not reach the host."
    assert job.status is JobStatus.FAILED
    assert job.stage is RepositoryStatus.CLONING  # shows where it failed
    assert job.error_message == "Could not reach the host."
    assert repository.commit_sha is None


def test_unexpected_error_hides_internal_details(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.clone_error = RuntimeError("secret internal detail")
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)

    RepositoryIndexer(job_context).run(job.id)

    _reload(db_session, job)
    assert job.status is JobStatus.FAILED
    assert "secret" not in (job.error_message or "")


def test_failed_reindex_keeps_previous_successful_index(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    repository = _create_repository(db_session)
    RepositoryIndexer(job_context).run(_queue_job(db_session, repository).id)
    _reload(db_session, repository)
    previous = (repository.commit_sha, repository.local_path, repository.repo_metadata)
    file_count = len(db_session.scalars(select(RepositoryFile.id)).all())

    fake_git.files = {"only.py": b"x = 1\n"}
    fake_git.clone_error = None
    job_context.settings.max_repository_files = 0  # force the ANALYZING stage to fail
    RepositoryIndexer(job_context).run(_queue_job(db_session, repository).id)

    _reload(db_session, repository)
    assert repository.status is RepositoryStatus.FAILED
    assert "more than 0 files" in (repository.status_message or "")
    assert (repository.commit_sha, repository.local_path, repository.repo_metadata) == previous
    assert len(db_session.scalars(select(RepositoryFile.id)).all()) == file_count
    assert (Path(repository.local_path or "") / "src" / "app.py").exists()
    assert not any(job_context.storage.temp_root.iterdir())


def test_repository_size_limit(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.files = {"huge.bin": b"x" * (1024 * 1024 + 1)}
    job_context.settings.max_repository_size_mb = 1
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)

    RepositoryIndexer(job_context).run(job.id)

    _reload(db_session, repository)
    assert repository.status is RepositoryStatus.FAILED
    assert "larger than the 1 MB limit" in (repository.status_message or "")


def test_cancellation_marks_job_interrupted(job_context: JobContext, db_session: Session) -> None:
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)
    job_context.cancel_event.set()

    RepositoryIndexer(job_context).run(job.id)

    _reload(db_session, job)
    assert job.status is JobStatus.FAILED
    assert job.error_message == INTERRUPTED_MESSAGE


def test_job_that_is_not_queued_is_skipped(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)
    job.status = JobStatus.SUCCEEDED
    db_session.commit()

    RepositoryIndexer(job_context).run(job.id)
    RepositoryIndexer(job_context).run(uuid.uuid4())  # unknown job id

    assert not [call for call in fake_git.calls if call[0] == "clone"]


def test_local_repository_is_revalidated_before_cloning(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    repository = _create_repository(db_session, source_type=RepositorySourceType.LOCAL, url="/etc")
    job = _queue_job(db_session, repository)

    RepositoryIndexer(job_context).run(job.id)

    _reload(db_session, repository)
    assert repository.status is RepositoryStatus.FAILED
    assert "allowed directory" in (repository.status_message or "")
    assert not [call for call in fake_git.calls if call[0] == "clone"]


def test_recover_interrupted_jobs(job_context: JobContext, db_session: Session) -> None:
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)
    job.status = JobStatus.RUNNING
    repository.status = RepositoryStatus.CLONING
    db_session.commit()
    leftover = job_context.storage.create_temp_dir(repository.id)
    leftover.mkdir()

    assert recover_interrupted_jobs(job_context) == 1

    _reload(db_session, repository, job)
    assert job.status is JobStatus.FAILED
    assert job.error_message == INTERRUPTED_MESSAGE
    assert repository.status is RepositoryStatus.FAILED
    assert not leftover.exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_end_to_end_with_real_git_and_local_repository(
    job_context: JobContext,
    db_session: Session,
    local_repos_root: Path,
) -> None:
    source = local_repos_root / "real-repo"
    sha = make_git_repository(
        source, {"main.go": b"package main\n", "README.md": b"# Real\n"}, branch="main"
    )
    context = replace(job_context, git=GitClient())
    repository = _create_repository(
        db_session, source_type=RepositorySourceType.LOCAL, url=str(source)
    )
    job = _queue_job(db_session, repository)

    RepositoryIndexer(context).run(job.id)

    _reload(db_session, repository)
    assert repository.status is RepositoryStatus.COMPLETED, repository.status_message
    assert repository.commit_sha == sha
    assert (repository.repo_metadata or {})["primary_language"] == "Go"
    assert (Path(repository.local_path or "") / "main.go").exists()


def test_parsing_stage_stores_code_analysis(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.files = fixture_files("python_project")
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)

    RepositoryIndexer(job_context).run(job.id)

    _reload(db_session, repository, job)
    assert repository.status is RepositoryStatus.COMPLETED, repository.status_message
    # files_total/files_processed track the job's last file-based stage (chunk embedding).
    assert job.files_total == job.files_processed == 17
    paths = set(db_session.scalars(select(CodeFile.path)))
    assert paths == {
        "main.py", "shop/__init__.py", "shop/models.py", "shop/utils.py",
        "shop/services.py", "shop/api/__init__.py", "shop/api/routes.py",
    }  # fmt: skip
    assert db_session.scalar(select(func.count()).select_from(CodeSymbol)) == 18
    assert db_session.scalar(select(func.count()).select_from(CodeRelationship)) == 17
    summary = (repository.repo_metadata or {})["analysis"]
    assert summary["files_analyzed"] == 7
    assert summary["relationships"]["calls"] == {"confirmed": 0, "inferred": 8}


def test_reindex_replaces_analysis_and_failure_keeps_it(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.files = fixture_files("python_project")
    repository = _create_repository(db_session)
    RepositoryIndexer(job_context).run(_queue_job(db_session, repository).id)
    RepositoryIndexer(job_context).run(
        _queue_job(db_session, repository).id
    )  # replace, not duplicate

    assert db_session.scalar(select(func.count()).select_from(CodeSymbol)) == 18

    fake_git.clone_error = GitCommandError("Network down.", GitErrorKind.NETWORK)
    RepositoryIndexer(job_context).run(_queue_job(db_session, repository).id)

    _reload(db_session, repository)
    assert repository.status is RepositoryStatus.FAILED
    assert db_session.scalar(select(func.count()).select_from(CodeSymbol)) == 18
    assert (repository.repo_metadata or {})["analysis"]["files_analyzed"] == 7


# --- search index (Phase 4) ---------------------------------------------------------


def test_indexing_builds_a_search_index(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.files = fixture_files("python_project")
    repository = _create_repository(db_session)
    job = _queue_job(db_session, repository)

    RepositoryIndexer(job_context).run(job.id)

    _reload(db_session, repository)
    chunks = db_session.scalars(
        select(CodeChunk).where(CodeChunk.repository_id == repository.id)
    ).all()
    directory = job_context.index_store.path_for(repository.id)
    manifest = job_context.index_store.read_manifest(repository.id) or {}
    summary = (repository.repo_metadata or {})["retrieval"]

    assert len(chunks) > 5
    assert manifest["chunk_count"] == len(chunks)
    assert manifest["commit_sha"] == repository.commit_sha == MAIN_SHA
    assert (directory / "bm25.npz").exists()
    assert (directory / "dense.faiss").exists()
    assert summary["chunks"] == len(chunks)
    assert summary["dense"]["status"] == "ready"
    # Chunks point back at the symbols they came from, with their source location.
    symbol_chunks = [chunk for chunk in chunks if chunk.chunk_type == "symbol"]
    assert symbol_chunks
    for chunk in symbol_chunks:
        assert chunk.symbol_name and chunk.symbol_type
        assert 1 <= chunk.start_line <= chunk.end_line
        assert chunk.token_count > 0
    assert any(chunk.symbol_id is not None for chunk in symbol_chunks)
    assert {chunk.file_path for chunk in chunks} <= set(
        db_session.scalars(select(RepositoryFile.path))
    )


def test_reindex_replaces_chunks_and_failure_keeps_the_previous_index(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.files = fixture_files("python_project")
    repository = _create_repository(db_session)
    RepositoryIndexer(job_context).run(_queue_job(db_session, repository).id)
    first = {chunk.id for chunk in db_session.scalars(select(CodeChunk))}
    built_at = (job_context.index_store.read_manifest(repository.id) or {})["built_at"]

    RepositoryIndexer(job_context).run(_queue_job(db_session, repository).id)

    # Chunk ids are deterministic, so an unchanged repository re-indexes to the same set.
    assert {chunk.id for chunk in db_session.scalars(select(CodeChunk))} == first
    assert (job_context.index_store.read_manifest(repository.id) or {})["built_at"] >= built_at

    fake_git.clone_error = GitCommandError("Network down.", GitErrorKind.NETWORK)
    RepositoryIndexer(job_context).run(_queue_job(db_session, repository).id)

    _reload(db_session, repository)
    assert repository.status is RepositoryStatus.FAILED
    assert {chunk.id for chunk in db_session.scalars(select(CodeChunk))} == first
    assert job_context.index_store.path_for(repository.id).is_dir()
    assert not list(job_context.index_store.temp_root.glob("*"))


def test_changed_files_produce_changed_chunks(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.files = fixture_files("python_project")
    repository = _create_repository(db_session)
    RepositoryIndexer(job_context).run(_queue_job(db_session, repository).id)
    before = {
        chunk.qualified_name
        for chunk in db_session.scalars(select(CodeChunk))
        if chunk.file_path == "shop/utils.py"
    }

    fake_git.files["shop/utils.py"] = (
        b'"""Utilities."""\n\n\ndef slugify(value: str) -> str:\n    return value.lower()\n'
    )
    RepositoryIndexer(job_context).run(_queue_job(db_session, repository).id)

    after = {
        chunk.qualified_name
        for chunk in db_session.scalars(select(CodeChunk))
        if chunk.file_path == "shop/utils.py"
    }
    assert "slugify" in after
    assert after != before


def test_indexing_without_dense_retrieval_still_builds_bm25(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.files = fixture_files("python_project")
    context = replace(
        job_context,
        settings=job_context.settings.model_copy(update={"dense_retrieval_enabled": False}),
    )
    repository = _create_repository(db_session)

    RepositoryIndexer(context).run(_queue_job(db_session, repository).id)

    _reload(db_session, repository)
    directory = context.index_store.path_for(repository.id)
    assert repository.status is RepositoryStatus.COMPLETED
    assert (directory / "bm25.npz").exists()
    assert not (directory / "dense.faiss").exists()
    assert (repository.repo_metadata or {})["retrieval"]["dense"]["status"] == "disabled"


def test_retrieval_can_be_switched_off_entirely(
    job_context: JobContext, db_session: Session, fake_git: FakeGitClient
) -> None:
    fake_git.files = fixture_files("python_project")
    context = replace(
        job_context, settings=job_context.settings.model_copy(update={"retrieval_enabled": False})
    )
    repository = _create_repository(db_session)

    RepositoryIndexer(context).run(_queue_job(db_session, repository).id)

    _reload(db_session, repository)
    assert repository.status is RepositoryStatus.COMPLETED
    assert db_session.scalars(select(CodeChunk)).all() == []
    assert not context.index_store.path_for(repository.id).exists()
    assert (repository.repo_metadata or {}).get("retrieval") is None
    # Code analysis is unaffected.
    assert db_session.scalar(select(func.count()).select_from(CodeSymbol)) == 18
