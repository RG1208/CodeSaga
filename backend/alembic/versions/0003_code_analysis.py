"""Code analysis: parsed files, symbols, imports and the dependency graph.

Tables: code_files, code_symbols (tree via parent_symbol_id), code_imports,
code_relationships (imports / calls / inherits / renders, confirmed or inferred).
The new repository status value "parsing" needs no change: statuses are VARCHAR.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-17 16:52:56.665646+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "code_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "parse_status",
            sa.Enum(
                "parsed", "partial", "failed", name="parsestatus", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("symbol_count", sa.Integer(), nullable=False),
        sa.Column("import_count", sa.Integer(), nullable=False),
        sa.Column("file_metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_code_files_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_files")),
        sa.UniqueConstraint("repository_id", "path", name=op.f("uq_code_files_repository_id_path")),
    )
    op.create_table(
        "code_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("module", sa.String(length=1024), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("names", sa.JSON(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("is_type_only", sa.Boolean(), nullable=False),
        sa.Column("resolution_status", sa.String(length=16), nullable=False),
        sa.Column("resolved_path", sa.String(length=1024), nullable=True),
        sa.Column("resolved_file_id", sa.Uuid(), nullable=True),
        sa.Column("import_metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["code_files.id"],
            name=op.f("fk_code_imports_file_id_code_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_code_imports_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_file_id"],
            ["code_files.id"],
            name=op.f("fk_code_imports_resolved_file_id_code_files"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_imports")),
    )
    op.create_index(op.f("ix_code_imports_file_id"), "code_imports", ["file_id"], unique=False)
    op.create_index(
        op.f("ix_code_imports_repository_id"), "code_imports", ["repository_id"], unique=False
    )
    op.create_index(
        op.f("ix_code_imports_resolved_file_id"), "code_imports", ["resolved_file_id"], unique=False
    )
    op.create_table(
        "code_symbols",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("parent_symbol_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("qualified_name", sa.String(length=2048), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "function",
                "method",
                "class",
                "component",
                "interface",
                "type_alias",
                "enum",
                "variable",
                name="symbolkind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("docstring", sa.Text(), nullable=True),
        sa.Column("return_type", sa.String(length=512), nullable=True),
        sa.Column("is_exported", sa.Boolean(), nullable=False),
        sa.Column("is_async", sa.Boolean(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("decorators", sa.JSON(), nullable=False),
        sa.Column("symbol_metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["code_files.id"],
            name=op.f("fk_code_symbols_file_id_code_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_symbol_id"],
            ["code_symbols.id"],
            name=op.f("fk_code_symbols_parent_symbol_id_code_symbols"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_code_symbols_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_symbols")),
    )
    op.create_index(op.f("ix_code_symbols_file_id"), "code_symbols", ["file_id"], unique=False)
    op.create_index(
        op.f("ix_code_symbols_parent_symbol_id"), "code_symbols", ["parent_symbol_id"], unique=False
    )
    op.create_index(
        "ix_code_symbols_repository_id_kind",
        "code_symbols",
        ["repository_id", "kind"],
        unique=False,
    )
    op.create_index(
        "ix_code_symbols_repository_id_name",
        "code_symbols",
        ["repository_id", "name"],
        unique=False,
    )
    op.create_table(
        "code_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column(
            "relationship_type",
            sa.Enum(
                "imports",
                "calls",
                "inherits",
                "renders",
                name="relationshiptype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "confidence",
            sa.Enum("confirmed", "inferred", name="confidence", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("source_file_id", sa.Uuid(), nullable=False),
        sa.Column("target_file_id", sa.Uuid(), nullable=False),
        sa.Column("source_symbol_id", sa.Uuid(), nullable=True),
        sa.Column("target_symbol_id", sa.Uuid(), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("relationship_metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            name=op.f("fk_code_relationships_repository_id_repositories"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["code_files.id"],
            name=op.f("fk_code_relationships_source_file_id_code_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_symbol_id"],
            ["code_symbols.id"],
            name=op.f("fk_code_relationships_source_symbol_id_code_symbols"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_file_id"],
            ["code_files.id"],
            name=op.f("fk_code_relationships_target_file_id_code_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_symbol_id"],
            ["code_symbols.id"],
            name=op.f("fk_code_relationships_target_symbol_id_code_symbols"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_relationships")),
    )
    op.create_index(
        "ix_code_relationships_repository_id_type",
        "code_relationships",
        ["repository_id", "relationship_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_relationships_source_file_id"),
        "code_relationships",
        ["source_file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_relationships_source_symbol_id"),
        "code_relationships",
        ["source_symbol_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_relationships_target_file_id"),
        "code_relationships",
        ["target_file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_code_relationships_target_symbol_id"),
        "code_relationships",
        ["target_symbol_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_code_relationships_target_symbol_id"), table_name="code_relationships")
    op.drop_index(op.f("ix_code_relationships_target_file_id"), table_name="code_relationships")
    op.drop_index(op.f("ix_code_relationships_source_symbol_id"), table_name="code_relationships")
    op.drop_index(op.f("ix_code_relationships_source_file_id"), table_name="code_relationships")
    op.drop_index("ix_code_relationships_repository_id_type", table_name="code_relationships")
    op.drop_table("code_relationships")
    op.drop_index("ix_code_symbols_repository_id_name", table_name="code_symbols")
    op.drop_index("ix_code_symbols_repository_id_kind", table_name="code_symbols")
    op.drop_index(op.f("ix_code_symbols_parent_symbol_id"), table_name="code_symbols")
    op.drop_index(op.f("ix_code_symbols_file_id"), table_name="code_symbols")
    op.drop_table("code_symbols")
    op.drop_index(op.f("ix_code_imports_resolved_file_id"), table_name="code_imports")
    op.drop_index(op.f("ix_code_imports_repository_id"), table_name="code_imports")
    op.drop_index(op.f("ix_code_imports_file_id"), table_name="code_imports")
    op.drop_table("code_imports")
    op.drop_table("code_files")
