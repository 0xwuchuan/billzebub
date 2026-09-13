import pytest
from sqlalchemy import text

from billzebub.persistence.database import Database


@pytest.mark.integration
def test_postgres_is_available(database: Database) -> None:
    with database.engine.connect() as connection:
        row = connection.execute(text("SELECT current_database(), 1")).one()

    assert row[0] == database.engine.url.database
    assert row[1] == 1
