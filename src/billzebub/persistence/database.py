"""Database construction and transaction ownership."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from billzebub.config import Settings


class Database:
    """Own the PostgreSQL engine and short-lived transaction sessions."""

    def __init__(self, settings: Settings) -> None:
        self.engine: Engine = create_engine(
            settings.database_url_value,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self._sessions.begin() as session:
            yield session

    @contextmanager
    def read(self) -> Iterator[Session]:
        """Run queries and roll them back so a read does not commit."""
        session = self._sessions()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def close(self) -> None:
        self.engine.dispose()
