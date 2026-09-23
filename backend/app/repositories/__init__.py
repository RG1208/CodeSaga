"""Data-access layer (the Repository design pattern).

Each class wraps SQLAlchemy queries for one model, so services never build
queries directly. Note the naming: `RepositoryRepository` is the data-access
class for the `Repository` model (a source code repository).
"""

from app.repositories.code_analysis_repository import CodeAnalysisRepository
from app.repositories.code_chunk_repository import CodeChunkRepository
from app.repositories.code_file_repository import CodeFileRepository
from app.repositories.code_relationship_repository import CodeRelationshipRepository
from app.repositories.code_symbol_repository import CodeSymbolRepository
from app.repositories.indexing_job_repository import IndexingJobRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.repository_file_repository import RepositoryFileRepository
from app.repositories.repository_repository import RepositoryRepository
from app.repositories.retrieval_log_repository import RetrievalLogRepository
from app.repositories.user_repository import UserRepository

__all__ = [
    "CodeAnalysisRepository",
    "CodeChunkRepository",
    "CodeFileRepository",
    "CodeRelationshipRepository",
    "CodeSymbolRepository",
    "IndexingJobRepository",
    "ProjectRepository",
    "RepositoryFileRepository",
    "RepositoryRepository",
    "RetrievalLogRepository",
    "UserRepository",
]
