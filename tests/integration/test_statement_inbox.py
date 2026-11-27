from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, func, select
from uuid6 import uuid7

from billzebub.artifact_capture import ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.jobs import JobQueue
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    ArtifactArrival,
    DurableJob,
    FinancialAccount,
    InboxFileObservation,
    SourceArtifact,
)
from billzebub.statement_inbox import InboxPollResult, StatementInbox


def _count(database: Database, model: type[Any]) -> int:
    with database.transaction() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


@pytest.mark.integration
def test_inbox_requires_stability_then_captures_enqueues_and_retains_source(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-inbox-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Inbox Card",
                default_currency="SGD",
                statement_adapter_key="synthetic-credit",
                statement_account_identifier="SYNTHETIC-001",
            )
        )
    inbox_root = tmp_path / "inbox"
    account_folder = inbox_root / "synthetic-inbox-card"
    account_folder.mkdir(parents=True)
    source = account_folder / "statement.pdf"
    source.write_bytes(b"%PDF-1.7\nsynthetic\n%%EOF\n")
    store = ContentAddressedStore(tmp_path / "artifacts")
    queue = JobQueue(database)
    first_seen = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    inbox = StatementInbox(
        database,
        ArtifactCapture(store, database),
        queue,
        inbox_root=inbox_root,
        stable_for=timedelta(seconds=30),
    )

    first = inbox.poll(first_seen)
    assert first.observed == 1
    assert first.captured == 0
    assert source.exists()

    second = inbox.poll(first_seen + timedelta(seconds=31))

    assert second.captured == 1
    assert second.enqueued == 1
    assert source.exists()

    job = queue.lease("test-worker", lease_for=timedelta(minutes=1))
    assert job is not None
    assert job.kind == "extract_statement"
    assert job.payload["financial_account_id"] == str(account_id)
    assert "artifact_id" in job.payload
    stored_files = [
        path for path in (tmp_path / "artifacts" / "sha256").rglob("*") if path.is_file()
    ]
    assert len(stored_files) == 1
    assert _count(database, DurableJob) == 1
    assert _count(database, SourceArtifact) == 1
    assert _count(database, ArtifactArrival) == 1

    third = inbox.poll(first_seen + timedelta(seconds=62))

    assert third.captured == 0
    assert third.enqueued == 0
    assert source.exists()
    assert source.read_bytes() == b"%PDF-1.7\nsynthetic\n%%EOF\n"
    assert _count(database, DurableJob) == 1
    assert _count(database, SourceArtifact) == 1
    assert _count(database, ArtifactArrival) == 1
    with database.transaction() as session:
        observation = session.scalar(select(InboxFileObservation))
        assert observation is not None
        assert observation.status == "captured"
        assert str(observation.artifact_id) == job.payload["artifact_id"]
        assert session.scalar(select(func.count()).select_from(InboxFileObservation)) == 1


@pytest.mark.integration
def test_inbox_resets_stability_when_file_changes(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-changing-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Changing Card",
                default_currency="SGD",
                statement_adapter_key="synthetic-credit",
                statement_account_identifier="SYNTHETIC-002",
            )
        )
    inbox_root = tmp_path / "inbox"
    folder = inbox_root / "synthetic-changing-card"
    folder.mkdir(parents=True)
    source = folder / "statement.pdf"
    source.write_bytes(b"first")
    store = ContentAddressedStore(tmp_path / "artifacts")
    inbox = StatementInbox(
        database,
        ArtifactCapture(store, database),
        JobQueue(database),
        inbox_root=inbox_root,
        stable_for=timedelta(seconds=30),
    )
    now = datetime(2026, 4, 1, 12, 0, tzinfo=UTC)
    inbox.poll(now)
    source.write_bytes(b"second version")

    changed = inbox.poll(now + timedelta(seconds=31))

    assert changed.captured == 0
    assert source.exists()


def _account(database: Database, slug: str) -> None:
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=uuid7(),
                slug=slug,
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Inbox Card",
                default_currency="SGD",
                statement_adapter_key="synthetic-credit",
                statement_account_identifier="SYNTHETIC-003",
            )
        )


@contextmanager
def _db_activity(database: Database) -> Iterator[dict[str, int]]:
    stats = {"writes": 0, "commits": 0}

    def before_execute(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE"}:
            stats["writes"] += 1

    def on_commit(conn: object) -> None:
        del conn
        stats["commits"] += 1

    event.listen(database.engine, "before_cursor_execute", before_execute)
    event.listen(database.engine, "commit", on_commit)
    try:
        yield stats
    finally:
        event.remove(database.engine, "before_cursor_execute", before_execute)
        event.remove(database.engine, "commit", on_commit)


@pytest.mark.integration
def test_observation_updates_share_one_transaction_per_poll(
    database: Database,
    tmp_path: Path,
) -> None:
    _account(database, "synthetic-batch-card")
    inbox_root = tmp_path / "inbox"
    folder = inbox_root / "synthetic-batch-card"
    folder.mkdir(parents=True)
    for name in ("one.pdf", "two.pdf", "three.pdf"):
        (folder / name).write_bytes(b"%PDF-1.7\nsynthetic\n%%EOF\n")
    inbox = StatementInbox(
        database,
        ArtifactCapture(ContentAddressedStore(tmp_path / "artifacts"), database),
        JobQueue(database),
        inbox_root=inbox_root,
        stable_for=timedelta(seconds=30),
    )
    seen = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)

    with _db_activity(database) as first_poll:
        assert inbox.poll(seen).observed == 3
    assert first_poll["commits"] == 1
    assert first_poll["writes"] == 3

    with _db_activity(database) as second_poll:
        assert inbox.poll(seen + timedelta(seconds=1)) == InboxPollResult()
    assert second_poll["commits"] == 1
    assert second_poll["writes"] == 3
    with database.transaction() as session:
        observed_at = set(session.scalars(select(InboxFileObservation.last_observed_at)).all())
    assert observed_at == {seen + timedelta(seconds=1)}
