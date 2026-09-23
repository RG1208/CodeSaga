"""Migrations must apply cleanly, match the ORM models, and be reversible."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def alembic_config(tmp_path: Path) -> tuple[Config, str]:
    database_url = f"sqlite:///{tmp_path / 'migrations.db'}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.attributes["database_url"] = database_url
    config.attributes["skip_logging_config"] = True
    return config, database_url


def test_upgrade_creates_tables_matching_models(alembic_config: tuple[Config, str]) -> None:
    config, database_url = alembic_config

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            assert {"users", "projects", "repositories", "alembic_version"} <= tables

            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def test_downgrade_removes_all_tables(alembic_config: tuple[Config, str]) -> None:
    config, database_url = alembic_config

    command.upgrade(config, "head")
    command.downgrade(config, "base")

    engine = create_engine(database_url)
    try:
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()
