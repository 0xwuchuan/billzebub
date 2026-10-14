from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from billzebub.jobs import LeasedJob
from billzebub.persistence.models import JobStatus
from billzebub.worker import RetryableJobError, Worker, job_attempt


class FakeQueue:
    def __init__(self, leased: LeasedJob | None) -> None:
        self.leased = leased
        self.completed: list[tuple[UUID, str]] = []
        self.failed: list[tuple[UUID, str, str, timedelta | None]] = []

    def lease(self, worker_id: str, *, lease_for: timedelta) -> LeasedJob | None:
        del worker_id, lease_for
        leased, self.leased = self.leased, None
        return leased

    def complete(self, job_id: UUID, worker_id: str) -> None:
        self.completed.append((job_id, worker_id))

    def fail(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        error_code: str,
        retry_after: timedelta | None,
    ) -> JobStatus:
        self.failed.append((job_id, worker_id, error_code, retry_after))
        return JobStatus.QUEUED if retry_after is not None else JobStatus.FAILED


def leased_job(kind: str = "extract") -> LeasedJob:
    return LeasedJob(
        id=uuid4(),
        kind=kind,
        payload={"fictional": True},
        attempt=1,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )


def test_worker_publishes_the_leased_attempt() -> None:
    job = leased_job()
    job = type(job)(
        id=job.id,
        kind=job.kind,
        payload=job.payload,
        attempt=6,
        lease_expires_at=job.lease_expires_at,
    )
    seen: list[int] = []

    def remember(_payload: dict[str, Any]) -> None:
        seen.append(job_attempt.get())

    Worker(FakeQueue(job), {"extract": remember}, worker_id="worker-a", poll_seconds=1).run_once()

    assert seen == [6]
    assert job_attempt.get() == 1


def test_worker_completes_successful_handler() -> None:
    job = leased_job()
    queue = FakeQueue(job)
    received: list[dict[str, Any]] = []
    worker = Worker(
        queue,
        {"extract": received.append},
        worker_id="worker-a",
        poll_seconds=1,
    )

    assert worker.run_once() is True
    assert received == [{"fictional": True}]
    assert queue.completed == [(job.id, "worker-a")]


def test_worker_records_unknown_and_retryable_failures() -> None:
    unknown = leased_job("unknown")
    unknown_queue = FakeQueue(unknown)
    Worker(unknown_queue, {}, worker_id="worker-a", poll_seconds=1).run_once()
    assert unknown_queue.failed == [(unknown.id, "worker-a", "unknown_job_kind", None)]

    retryable = leased_job()
    retry_queue = FakeQueue(retryable)

    def fail_temporarily(_payload: dict[str, Any]) -> None:
        raise RetryableJobError("temporary_io", timedelta(seconds=10))

    Worker(
        retry_queue,
        {"extract": fail_temporarily},
        worker_id="worker-a",
        poll_seconds=1,
    ).run_once()
    assert retry_queue.failed == [(retryable.id, "worker-a", "temporary_io", timedelta(seconds=10))]
