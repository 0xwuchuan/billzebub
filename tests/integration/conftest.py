from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text

from billzebub.config import Environment, Settings
from billzebub.persistence.base import Base
from billzebub.persistence.database import Database


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


@pytest.fixture(scope="session")
def migrated_database(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Database]:
    configured_url = os.environ.get("TEST_DATABASE_URL")
    if configured_url is None:
        pytest.skip("TEST_DATABASE_URL is not configured")

    database_url = _sqlalchemy_url(configured_url)
    prior_url = os.environ.get("BILLZEBUB_DATABASE_URL")
    os.environ["BILLZEBUB_DATABASE_URL"] = database_url
    command.upgrade(Config("alembic.ini"), "head")

    database = Database(
        Settings(
            environment=Environment.TEST,
            database_url=SecretStr(database_url),
            artifact_root=tmp_path_factory.mktemp("artifacts"),
        )
    )
    try:
        yield database
    finally:
        database.close()
        if prior_url is None:
            os.environ.pop("BILLZEBUB_DATABASE_URL", None)
        else:
            os.environ["BILLZEBUB_DATABASE_URL"] = prior_url


@pytest.fixture
def database(migrated_database: Database) -> Database:
    table_names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with migrated_database.engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    return migrated_database
