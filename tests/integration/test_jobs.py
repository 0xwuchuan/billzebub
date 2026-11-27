from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select, update

from billzebub.jobs import JobQueue, JobStateError
from billzebub.persistence.database import Database
from billzebub.persistence.models import DurableJob, JobStatus


@pytest.mark.integration
def test_active_dedupe_and_completion(database: Database) -> None:
    queue = JobQueue(database)

    first = queue.enqueue("extract", {"artifact_id": "fictional"}, dedupe_key="artifact-1")
    duplicate = queue.enqueue("extract", {"artifact_id": "fictional"}, dedupe_key="artifact-1")

    assert duplicate.id == first.id
    assert duplicate.duplicate is True
    leased = queue.lease("worker-a", lease_for=timedelta(minutes=1))
    assert leased is not None
    with pytest.raises(JobStateError):
        queue.complete(leased.id, "worker-b")
    queue.complete(leased.id, "worker-a")

    replacement = queue.enqueue("extract", {}, dedupe_key="artifact-1")
    assert replacement.id != first.id
    assert replacement.duplicate is False


@pytest.mark.integration
def test_retry_increments_attempt_and_preserves_explicit_error_code(database: Database) -> None:
    queue = JobQueue(database)
    queued = queue.enqueue("extract", {}, max_attempts=2)

    first = queue.lease("worker-a", lease_for=timedelta(minutes=1))
    assert first is not None
    assert first.attempt == 1
    assert (
        queue.fail(
            first.id,
            "worker-a",
            error_code="temporary_io",
            retry_after=timedelta(0),
        )
        is JobStatus.QUEUED
    )

    second = queue.lease("worker-a", lease_for=timedelta(minutes=1))
    assert second is not None
    assert second.id == queued.id
    assert second.attempt == 2
    assert (
        queue.fail(
            second.id,
            "worker-a",
            error_code="temporary_io",
            retry_after=timedelta(0),
        )
        is JobStatus.FAILED
    )

    with database.transaction() as session:
        stored = session.get(DurableJob, queued.id)
        assert stored is not None
        assert stored.last_error_code == "temporary_io"
        assert stored.completed_at is not None


@pytest.mark.integration
def test_expired_lease_is_recovered_until_attempts_are_exhausted(database: Database) -> None:
    queue = JobQueue(database)
    queued = queue.enqueue("extract", {}, max_attempts=2)
    first = queue.lease("worker-crashed", lease_for=timedelta(minutes=1))
    assert first is not None

    expired = datetime.now(UTC) - timedelta(seconds=1)
    with database.transaction() as session:
        session.execute(
            update(DurableJob).where(DurableJob.id == queued.id).values(lease_expires_at=expired)
        )

    second = queue.lease("worker-b", lease_for=timedelta(minutes=1))
    assert second is not None
    assert second.attempt == 2
    with database.transaction() as session:
        session.execute(
            update(DurableJob).where(DurableJob.id == queued.id).values(lease_expires_at=expired)
        )

    assert queue.lease("worker-c", lease_for=timedelta(minutes=1)) is None
    with database.transaction() as session:
        status = session.scalar(select(DurableJob.status).where(DurableJob.id == queued.id))
    assert status is JobStatus.FAILED


@pytest.mark.integration
def test_empty_queue_lease_does_not_commit(database: Database) -> None:
    commits = {"n": 0}

    def on_commit(conn: object) -> None:
        del conn
        commits["n"] += 1

    event.listen(database.engine, "commit", on_commit)
    try:
        assert JobQueue(database).lease("idle-worker", lease_for=timedelta(minutes=1)) is None
    finally:
        event.remove(database.engine, "commit", on_commit)
    assert commits["n"] == 0
