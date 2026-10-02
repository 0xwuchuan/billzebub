import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from billzebub.persistence.database import Database


@pytest.mark.integration
def test_migrations_create_current_foundation_tables(database: Database) -> None:
    tables = set(inspect(database.engine).get_table_names())

    assert {
        "alembic_version",
        "artifact_arrival",
        "audit_actor",
        "category",
        "durable_job",
        "financial_account",
        "financial_account_alias",
        "claim",
        "claim_disposition_event",
        "claim_source_locator",
        "extraction",
        "financial_transaction",
        "idempotency_record",
        "inbox_file_observation",
        "integration_token",
        "journal",
        "ledger_posting",
        "offset_allocation",
        "pending_review",
        "review_event",
        "recurring_occurrence",
        "recurring_series",
        "source_artifact",
        "transaction_version",
    }.issubset(tables)


@pytest.mark.integration
def test_migration_matches_sqlalchemy_metadata(database: Database) -> None:
    assert os.environ.get("BILLZEBUB_DATABASE_URL") is not None
    command.check(Config("alembic.ini"))


@pytest.mark.integration
def test_migrations_can_downgrade_to_phase_1_and_reapply(database: Database) -> None:
    config = Config("alembic.ini")

    command.downgrade(config, "0001")
    assert "claim" not in inspect(database.engine).get_table_names()

    command.upgrade(config, "head")
    assert "claim" in inspect(database.engine).get_table_names()
    assert "counterparty_category_map" not in inspect(database.engine).get_table_names()
    columns = {column["name"] for column in inspect(database.engine).get_columns("extraction")}
    assert "dismissed_at" in columns
