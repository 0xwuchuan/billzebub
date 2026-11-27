"""An idle worker must not write while captured statements sit in the inbox."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, select
from uuid6 import uuid7

from billzebub.artifact_capture import ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.entrypoints.worker import enqueue_scheduled_catch_up
from billzebub.jev_categorizer import JevCatchupScheduler
from billzebub.jobs import JobQueue
from billzebub.persistence.database import Database
from billzebub.persistence.models import FinancialAccount, InboxFileObservation
from billzebub.statement_inbox import StatementInbox
from billzebub.worker import Worker

_POLLS = 5


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
def test_idle_worker_with_captured_inbox_issues_no_writes(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-idle-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Idle Card",
                default_currency="SGD",
                statement_adapter_key="synthetic-credit",
                statement_account_identifier="SYNTHETIC-IDLE",
            )
        )
    inbox_root = tmp_path / "inbox"
    folder = inbox_root / "synthetic-idle-card"
    folder.mkdir(parents=True)
    for name in ("alpha.pdf", "beta.pdf", "gamma.pdf", "delta.pdf"):
        (folder / name).write_bytes(f"%PDF-1.7\nsynthetic idle {name}\n%%EOF\n".encode())
    queue = JobQueue(database)
    inbox = StatementInbox(
        database,
        ArtifactCapture(ContentAddressedStore(tmp_path / "artifacts"), database),
        queue,
        inbox_root=inbox_root,
        stable_for=timedelta(seconds=30),
    )
    seen = datetime(2026, 11, 26, 1, 0, tzinfo=UTC)
    assert inbox.poll(seen).observed == 4
    captured = inbox.poll(seen + timedelta(seconds=31))
    assert captured.captured == 4
    assert captured.enqueued == 4
    completed = 0
    while True:
        job = queue.lease("idle-worker", lease_for=timedelta(minutes=1))
        if job is None:
            break
        queue.complete(job.id, "idle-worker")
        completed += 1
    assert completed == 4

    with database.transaction() as session:
        observed_at = set(session.scalars(select(InboxFileObservation.last_observed_at)).all())
    scheduler = JevCatchupScheduler(hour=21, timezone=ZoneInfo("Asia/Singapore"))
    worker = Worker(queue, {}, worker_id="idle-worker", poll_seconds=0.01)

    with _db_activity(database) as idle:
        for offset in range(_POLLS):
            assert inbox.poll(seen + timedelta(minutes=2, seconds=offset)).captured == 0
            run_date = scheduler.catchup_date(seen + timedelta(minutes=2, seconds=offset))
            enqueue_scheduled_catch_up(queue, run_date)
            assert worker.run_once() is False

    assert idle["writes"] == 0
    assert idle["commits"] == 0
    with database.transaction() as session:
        assert set(session.scalars(select(InboxFileObservation.last_observed_at)).all()) == (
            observed_at
        )
        assert set(session.scalars(select(InboxFileObservation.status)).all()) == {"captured"}
