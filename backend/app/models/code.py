"""Tables produced by source-code analysis (Phase 3).

    repositories 1 ── * code_files 1 ── * code_symbols (tree via parent_symbol_id)
                                     └── * code_imports
    code_relationships: file → file (imports) and symbol → symbol (calls, renders, inherits)

All rows are replaced together each time a repository is indexed.
"""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.analysis.results import Confidence, ParseStatus, RelationshipType, SymbolKind
from app.db.base import Base, UUIDPrimaryKeyMixin
from app.models.repository import enum_column

if TYPE_CHECKING:
    from app.models.repository import Repository


class CodeFile(UUIDPrimaryKeyMixin, Base):
    """A source file that was parsed (Python, JavaScript, TypeScript, TSX)."""

    __tablename__ = "code_files"
    __table_args__ = (UniqueConstraint("repository_id", "path"),)

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    path: Mapped[str] = mapped_column(String(1024))
    language: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    line_count: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    parse_status: Mapped[ParseStatus] = mapped_column(enum_column(ParseStatus))
    symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    import_count: Mapped[int] = mapped_column(Integer, default=0)
    # docstring, exports, api_calls, syntax_errors, comment_lines
    file_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    repository: Mapped["Repository"] = relationship()
    symbols: Mapped[list["CodeSymbol"]] = relationship(
        back_populates="file", cascade="all, delete-orphan", passive_deletes=True
    )
    imports: Mapped[list["CodeImport"]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="CodeImport.file_id",
    )


class CodeSymbol(UUIDPrimaryKeyMixin, Base):
    """A named definition: function, method, class, component, interface, type, enum…"""

    __tablename__ = "code_symbols"
    __table_args__ = (
        Index("ix_code_symbols_repository_id_name", "repository_id", "name"),
        Index("ix_code_symbols_repository_id_kind", "repository_id", "kind"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_files.id", ondelete="CASCADE"), index=True
    )
    parent_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(512))
    qualified_name: Mapped[str] = mapped_column(String(2048))  # e.g. "ProductService.save"
    kind: Mapped[SymbolKind] = mapped_column(enum_column(SymbolKind))
    start_line: Mapped[int] = mapped_column(Integer)  # 1-based, inclusive, includes decorators
    end_line: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str | None] = mapped_column(Text)
    docstring: Mapped[str | None] = mapped_column(Text)
    return_type: Mapped[str | None] = mapped_column(String(512))
    is_exported: Mapped[bool] = mapped_column(Boolean, default=False)
    is_async: Mapped[bool] = mapped_column(Boolean, default=False)
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    decorators: Mapped[list[str]] = mapped_column(JSON, default=list)
    # calls, renders, hooks, api_calls, bases, comment, method_type, default_export…
    symbol_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    file: Mapped[CodeFile] = relationship(back_populates="symbols")


class CodeImport(UUIDPrimaryKeyMixin, Base):
    """One import statement and where it resolved to."""

    __tablename__ = "code_imports"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_files.id", ondelete="CASCADE"), index=True
    )
    module: Mapped[str] = mapped_column(String(1024))  # as written in the source
    kind: Mapped[str] = mapped_column(
        String(32)
    )  # import|from|require|dynamic|side_effect|re_export
    names: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    is_type_only: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_status: Mapped[str] = mapped_column(String(16))  # resolved|external|unresolved
    resolved_path: Mapped[str | None] = mapped_column(String(1024))
    resolved_file_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_files.id", ondelete="SET NULL"), index=True
    )
    # confidence, strategy, candidates, name_targets, package, level, scope, conditional
    import_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    file: Mapped[CodeFile] = relationship(back_populates="imports", foreign_keys=[file_id])


class CodeRelationship(UUIDPrimaryKeyMixin, Base):
    """A directed dependency edge between files or symbols."""

    __tablename__ = "code_relationships"
    __table_args__ = (
        Index("ix_code_relationships_repository_id_type", "repository_id", "relationship_type"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE")
    )
    relationship_type: Mapped[RelationshipType] = mapped_column(enum_column(RelationshipType))
    confidence: Mapped[Confidence] = mapped_column(enum_column(Confidence))
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_files.id", ondelete="CASCADE"), index=True
    )
    target_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_files.id", ondelete="CASCADE"), index=True
    )
    source_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"), index=True
    )
    target_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="CASCADE"), index=True
    )
    weight: Mapped[int] = mapped_column(Integer, default=1)  # occurrences aggregated into the edge
    # specifiers/lines/strategies for imports; resolution/expressions/lines for symbols
    relationship_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    source_file: Mapped[CodeFile] = relationship(foreign_keys=[source_file_id])
    target_file: Mapped[CodeFile] = relationship(foreign_keys=[target_file_id])
    source_symbol: Mapped[CodeSymbol | None] = relationship(foreign_keys=[source_symbol_id])
    target_symbol: Mapped[CodeSymbol | None] = relationship(foreign_keys=[target_symbol_id])
