import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.indexing_job import JobStatus
from app.models.repository import RepositorySourceType, RepositoryStatus
from app.schemas.common import ORMSchema


class RepositoryCreate(BaseModel):
    """Register a repository. Validation of the URL/path happens in the service layer."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_type: RepositorySourceType = RepositorySourceType.GITHUB
    url: str = Field(
        min_length=1,
        max_length=4096,
        description=(
            "GitHub HTTPS URL (https://github.com/owner/repo), or an absolute path to a "
            "local git repository when source_type is 'local' (development only)."
        ),
        examples=["https://github.com/pallets/markupsafe"],
    )
    branch: str | None = Field(
        default=None,
        max_length=255,
        description="Branch to index. Defaults to the repository's default branch.",
    )
    name: str | None = Field(
        default=None,
        max_length=255,
        description="Display name. Defaults to the repository name from the URL or path.",
    )
    project_id: uuid.UUID | None = Field(
        default=None, description="Project to add the repository to. Defaults to 'Default'."
    )


class LanguageStat(BaseModel):
    language: str
    files: int
    bytes: int


class LastCommit(BaseModel):
    sha: str
    author_name: str
    authored_at: datetime
    subject: str


class RepositoryMetadata(BaseModel):
    """Facts extracted from a checkout during the ANALYZING and INDEXING stages."""

    total_files: int
    total_size_bytes: int
    indexed_files: int
    skipped_files: dict[str, int]
    primary_language: str | None
    languages: list[LanguageStat]
    manifests: list[str]
    readme_path: str | None
    license_path: str | None
    last_commit: LastCommit | None
    # Code-analysis statistics (Phase 3). None for repositories indexed before analysis
    # existed: re-index them to build symbols and the dependency graph.
    analysis: dict[str, Any] | None = None
    # Retrieval index statistics (Phase 4): chunk counts, BM25 and dense index details.
    retrieval: dict[str, Any] | None = None


class IndexingJobRead(ORMSchema):
    id: uuid.UUID
    repository_id: uuid.UUID
    status: JobStatus
    stage: RepositoryStatus
    branch: str
    commit_sha: str | None
    files_total: int | None
    files_processed: int
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RepositoryRead(ORMSchema):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    owner: str | None
    url: str
    source_type: RepositorySourceType
    default_branch: str
    branch: str
    commit_sha: str | None
    local_path: str | None
    status: RepositoryStatus
    status_message: str | None
    last_indexed_at: datetime | None
    metadata: RepositoryMetadata | None = Field(validation_alias="repo_metadata")
    created_at: datetime
    updated_at: datetime


class RepositoryDetail(RepositoryRead):
    latest_job: IndexingJobRead | None = None
