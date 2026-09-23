"""Build a searchable index from a fixture project, without a database or a server."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.analysis.registry import default_registry
from app.core.config import Settings
from app.retrieval.builder import build_retrieval_index
from app.retrieval.chunking import Chunk, ChunkingConfig, CodeChunker, symbol_records
from app.retrieval.embeddings import EmbeddingProvider, HashingEmbeddingProvider
from app.retrieval.engine import RetrievalEngine, RetrievalIndex
from app.retrieval.index_store import RepositoryIndexStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "retrieval"


@dataclass
class FixtureIndex:
    repository_id: uuid.UUID
    chunks: list[Chunk]
    index: RetrievalIndex
    store: RepositoryIndexStore
    embeddings: EmbeddingProvider
    settings: Settings
    summary: dict

    def by_id(self) -> dict[str, Chunk]:
        return {str(chunk.chunk_id): chunk for chunk in self.chunks}

    def documents(self, chunk_ids: Sequence[str]) -> dict[str, str]:
        lookup = self.by_id()
        return {
            chunk_id: lookup[chunk_id].index_text() for chunk_id in chunk_ids if chunk_id in lookup
        }

    def engine(self) -> RetrievalEngine:
        return RetrievalEngine(self.index, self.embeddings, self.documents, self.settings)

    def file_of(self, chunk_id: str) -> str:
        return self.by_id()[chunk_id].file_path


def fixture_root(project: str = "support_desk") -> Path:
    return FIXTURES / project


def chunk_fixture(
    project: str, repository_id: uuid.UUID, config: ChunkingConfig | None = None
) -> list[Chunk]:
    """Chunk a fixture project exactly as the indexing pipeline would."""
    root = fixture_root(project)
    registry = default_registry()
    chunker = CodeChunker(repository_id, config)
    chunks: list[Chunk] = []
    for path in sorted(
        item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file()
    ):
        content = (root / path).read_text(encoding="utf-8")
        analyzer = registry.analyzer_for(path)
        if analyzer is not None:
            analysis = analyzer.analyze(content.encode("utf-8"), path)
            ids = {symbol.key: uuid.uuid4() for symbol in analysis.symbols}
            rows = [
                {
                    "id": ids[symbol.key],
                    "name": symbol.name,
                    "kind": symbol.kind.value,
                    "qualified_name": symbol.qualified_name,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "parent_symbol_id": ids[symbol.parent_key]
                    if symbol.parent_key is not None
                    else None,
                }
                for symbol in analysis.symbols
            ]
            chunks.extend(
                chunker.chunk_source_file(path, analysis.language, content, symbol_records(rows))
            )
        elif CodeChunker.should_chunk(path, "Markdown" if path.endswith(".md") else None):
            chunks.extend(chunker.chunk_text_file(path, "Markdown", content))
    return chunks


def build_fixture_index(
    tmp_path: Path,
    *,
    project: str = "support_desk",
    embeddings: EmbeddingProvider | None = None,
    settings: Settings | None = None,
) -> FixtureIndex:
    repository_id = uuid.uuid5(uuid.NAMESPACE_URL, f"fixture://{project}")
    settings = settings or Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        embedding_provider="hashing",
        index_storage_dir=tmp_path / "indexes",
    )
    embeddings = embeddings or HashingEmbeddingProvider()
    store = RepositoryIndexStore(settings.index_storage_dir)
    chunks = chunk_fixture(project, repository_id)
    build = build_retrieval_index(
        repository_id=repository_id,
        commit_sha="fixture-commit",
        chunks=chunks,
        settings=settings,
        embeddings=embeddings,
        index_store=store,
    )
    store.install(repository_id, build.directory)
    index = store.load(
        repository_id, commit_sha="fixture-commit", embeddings=embeddings, settings=settings
    )
    return FixtureIndex(
        repository_id=repository_id,
        chunks=chunks,
        index=index,
        store=store,
        embeddings=embeddings,
        settings=settings,
        summary=build.summary,
    )
