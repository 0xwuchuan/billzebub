"""Durable PostgreSQL-backed job leasing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from uuid6 import uuid7

from billzebub.persistence.database import Database
from billzebub.persistence.models import DurableJob, JobStatus

_ACTIVE_DEDUPE_PREDICATE = text(
    "dedupe_key IS NOT NULL AND status IN ('queued'::durable_job_status, "
    "'running'::durable_job_status)"
)


class JobStateError(Exception):
    """A worker attempted a transition it no longer owns."""


@dataclass(frozen=True, slots=True)
class EnqueuedJob:
    id: UUID
    duplicate: bool


@dataclass(frozen=True, slots=True)
class LeasedJob:
    id: UUID
    kind: str
    payload: dict[str, Any]
    attempt: int
    lease_expires_at: datetime


class JobQueue:
    """Enqueue idempotently and lease work with crash-safe ownership."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        dedupe_key: str | None = None,
        max_attempts: int = 5,
        available_at: datetime | None = None,
    ) -> EnqueuedJob:
        if not kind.strip():
            raise ValueError("job kind is required")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if available_at is not None and available_at.tzinfo is None:
            raise ValueError("available_at must include a timezone")

        proposed_id = uuid7()
        values: dict[str, Any] = {
            "id": proposed_id,
            "kind": kind,
            "payload": payload,
            "dedupe_key": dedupe_key,
            "max_attempts": max_attempts,
        }
        if available_at is not None:
            values["available_at"] = available_at

        with self._database.transaction() as session:
            statement = insert(DurableJob).values(**values)
            if dedupe_key is not None:
                statement = statement.on_conflict_do_nothing(
                    index_elements=[DurableJob.kind, DurableJob.dedupe_key],
                    index_where=_ACTIVE_DEDUPE_PREDICATE,
                )
            inserted_id = session.execute(statement.returning(DurableJob.id)).scalar_one_or_none()
            if inserted_id is not None:
                return EnqueuedJob(id=inserted_id, duplicate=False)

            existing_id = session.execute(
                select(DurableJob.id).where(
                    DurableJob.kind == kind,
                    DurableJob.dedupe_key == dedupe_key,
                    DurableJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
                )
            ).scalar_one()
            return EnqueuedJob(id=existing_id, duplicate=True)

    def lease(self, worker_id: str, *, lease_for: timedelta) -> LeasedJob | None:
        if not worker_id.strip():
            raise ValueError("worker_id is required")
        if lease_for <= timedelta(0):
            raise ValueError("lease_for must be positive")

        now = datetime.now(UTC)
        if not self._has_leased_or_due_work(now):
            return None
        with self._database.transaction() as session:
            running = (
                session.scalar(
                    select(DurableJob.id).where(DurableJob.status == JobStatus.RUNNING).limit(1)
                )
                is not None
            )
            if running:
                self._recover_expired(session, now)
            job = session.execute(
                select(DurableJob)
                .where(
                    DurableJob.status == JobStatus.QUEUED,
                    DurableJob.available_at <= now,
                    DurableJob.attempts < DurableJob.max_attempts,
                )
                .order_by(DurableJob.available_at, DurableJob.created_at, DurableJob.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            ).scalar_one_or_none()
            if job is None:
                if not running:
                    session.rollback()
                return None

            lease_expires_at = now + lease_for
            job.status = JobStatus.RUNNING
            job.lease_owner = worker_id
            job.lease_expires_at = lease_expires_at
            job.attempts += 1
            job.updated_at = now
            session.flush()
            return LeasedJob(
                id=job.id,
                kind=job.kind,
                payload=job.payload,
                attempt=job.attempts,
                lease_expires_at=lease_expires_at,
            )

    def heartbeat(self, job_id: UUID, worker_id: str, *, lease_for: timedelta) -> datetime:
        if lease_for <= timedelta(0):
            raise ValueError("lease_for must be positive")
        lease_expires_at = datetime.now(UTC) + lease_for
        with self._database.transaction() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(DurableJob)
                    .where(
                        DurableJob.id == job_id,
                        DurableJob.status == JobStatus.RUNNING,
                        DurableJob.lease_owner == worker_id,
                    )
                    .values(lease_expires_at=lease_expires_at, updated_at=datetime.now(UTC))
                ),
            )
            if result.rowcount != 1:
                raise JobStateError("job lease is not owned by this worker")
        return lease_expires_at

    def complete(self, job_id: UUID, worker_id: str) -> None:
        now = datetime.now(UTC)
        with self._database.transaction() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(DurableJob)
                    .where(
                        DurableJob.id == job_id,
                        DurableJob.status == JobStatus.RUNNING,
                        DurableJob.lease_owner == worker_id,
                    )
                    .values(
                        status=JobStatus.SUCCEEDED,
                        lease_owner=None,
                        lease_expires_at=None,
                        updated_at=now,
                        completed_at=now,
                    )
                ),
            )
            if result.rowcount != 1:
                raise JobStateError("job lease is not owned by this worker")

    def fail(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        error_code: str,
        retry_after: timedelta | None,
    ) -> JobStatus:
        if not error_code.strip():
            raise ValueError("error_code is required")
        if retry_after is not None and retry_after < timedelta(0):
            raise ValueError("retry_after cannot be negative")

        now = datetime.now(UTC)
        with self._database.transaction() as session:
            job = session.execute(
                select(DurableJob)
                .where(
                    DurableJob.id == job_id,
                    DurableJob.status == JobStatus.RUNNING,
                    DurableJob.lease_owner == worker_id,
                )
                .with_for_update()
            ).scalar_one_or_none()
            if job is None:
                raise JobStateError("job lease is not owned by this worker")

            should_retry = retry_after is not None and job.attempts < job.max_attempts
            job.status = JobStatus.QUEUED if should_retry else JobStatus.FAILED
            job.available_at = now + retry_after if should_retry and retry_after else now
            job.lease_owner = None
            job.lease_expires_at = None
            job.last_error_code = error_code
            job.updated_at = now
            job.completed_at = None if should_retry else now
            return job.status

    def _has_leased_or_due_work(self, now: datetime) -> bool:
        """True when a recover or lease would write. An idle queue stays uncommitted."""
        with self._database.read() as session:
            running = session.scalar(
                select(DurableJob.id).where(DurableJob.status == JobStatus.RUNNING).limit(1)
            )
            if running is not None:
                return True
            due = session.scalar(
                select(DurableJob.id)
                .where(
                    DurableJob.status == JobStatus.QUEUED,
                    DurableJob.available_at <= now,
                    DurableJob.attempts < DurableJob.max_attempts,
                )
                .limit(1)
            )
            return due is not None

    @staticmethod
    def _recover_expired(session: Any, now: datetime) -> None:
        session.execute(
            update(DurableJob)
            .where(
                DurableJob.status == JobStatus.RUNNING,
                DurableJob.lease_expires_at < now,
                DurableJob.attempts >= DurableJob.max_attempts,
            )
            .values(
                status=JobStatus.FAILED,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code="lease_expired",
                updated_at=now,
                completed_at=now,
            )
        )
        session.execute(
            update(DurableJob)
            .where(
                DurableJob.status == JobStatus.RUNNING,
                DurableJob.lease_expires_at < now,
                DurableJob.attempts < DurableJob.max_attempts,
            )
            .values(
                status=JobStatus.QUEUED,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code="lease_expired",
                available_at=now,
                updated_at=now,
            )
        )
