"""Requeue failed Jev categorize jobs without duplicating active work."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from billzebub.jev_categorizer import (
    CATEGORIZE_CLAIM_JOB,
    CATEGORIZE_MAX_ATTEMPTS,
    CATEGORIZE_TRANSACTION_JOB,
    JevCategorizer,
    requeue_failed_categorizations,
)
from billzebub.jobs import JobQueue
from billzebub.persistence.database import Database
from billzebub.persistence.models import DurableJob, JobStatus


def _fail_once(queue: JobQueue, kind: str, payload: dict[str, str], dedupe_key: str) -> None:
    queued = queue.enqueue(kind, payload, dedupe_key=dedupe_key, max_attempts=1)
    leased = queue.lease("worker-a", lease_for=timedelta(minutes=1))
    assert leased is not None
    assert leased.id == queued.id
    assert (
        queue.fail(
            leased.id,
            "worker-a",
            error_code="jev_unavailable",
            retry_after=timedelta(seconds=30),
        )
        is JobStatus.FAILED
    )


@pytest.mark.integration
def test_requeue_failed_jev_unavailable_is_idempotent(database: Database) -> None:
    queue = JobQueue(database)
    transaction_id = uuid4()
    claim_id = uuid4()
    other_id = uuid4()
    _fail_once(
        queue,
        CATEGORIZE_TRANSACTION_JOB,
        {"transaction_id": str(transaction_id)},
        str(transaction_id),
    )
    _fail_once(
        queue,
        CATEGORIZE_CLAIM_JOB,
        {"claim_id": str(claim_id)},
        str(claim_id),
    )
    other = queue.enqueue(
        CATEGORIZE_TRANSACTION_JOB,
        {"transaction_id": str(other_id)},
        dedupe_key=str(other_id),
        max_attempts=1,
    )
    other_lease = queue.lease("worker-a", lease_for=timedelta(minutes=1))
    assert other_lease is not None
    assert (
        queue.fail(
            other.id,
            "worker-a",
            error_code="invalid_categorize_job",
            retry_after=None,
        )
        is JobStatus.FAILED
    )

    dry_run = requeue_failed_categorizations(database, queue, apply=False)
    assert dry_run.applied is False
    assert dry_run.failed_before == 2
    assert dry_run.active_before == 0
    assert dry_run.would_requeue == 2
    assert dry_run.requeued == 0
    assert dry_run.failed_after == 2
    assert dry_run.active_after == 0
    assert _queued_count(database) == 0

    first = requeue_failed_categorizations(database, queue, apply=True)
    assert first.failed_before == 2
    assert first.active_before == 0
    assert first.requeued == 2
    assert first.failed_after == 2
    assert first.active_after == 2
    assert _queued_count(database) == 2
    assert _max_attempts(database) == {CATEGORIZE_MAX_ATTEMPTS}

    second = requeue_failed_categorizations(database, queue, apply=True)
    assert second.failed_before == 2
    assert second.active_before == 2
    assert second.would_requeue == 0
    assert second.requeued == 0
    assert second.active_after == 2
    assert _queued_count(database) == 2

    caught_up = JevCategorizer(database, None).enqueue_pending(queue)
    assert caught_up == 0
    assert _queued_count(database) == 2


def _queued_count(database: Database) -> int:
    with database.transaction() as session:
        count = session.scalar(
            select(func.count())
            .select_from(DurableJob)
            .where(DurableJob.status == JobStatus.QUEUED)
        )
    assert count is not None
    return int(count)


def _max_attempts(database: Database) -> set[int]:
    with database.transaction() as session:
        values = session.scalars(
            select(DurableJob.max_attempts).where(DurableJob.status == JobStatus.QUEUED)
        ).all()
    return set(values)
