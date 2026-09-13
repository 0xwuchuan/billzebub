"""Worker loop over the durable job module."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from threading import Event
from typing import Any, Protocol
from uuid import UUID

from billzebub.jobs import LeasedJob
from billzebub.persistence.models import JobStatus

logger = logging.getLogger(__name__)
JobHandler = Callable[[dict[str, Any]], None]


class JobRuntime(Protocol):
    def lease(self, worker_id: str, *, lease_for: timedelta) -> LeasedJob | None: ...

    def complete(self, job_id: UUID, worker_id: str) -> None: ...

    def fail(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        error_code: str,
        retry_after: timedelta | None,
    ) -> JobStatus: ...


@dataclass(frozen=True, slots=True)
class RetryableJobError(Exception):
    error_code: str
    retry_after: timedelta


@dataclass(frozen=True, slots=True)
class TerminalJobError(Exception):
    error_code: str


class Worker:
    """Lease one job at a time and turn failures into explicit transitions."""

    def __init__(
        self,
        queue: JobRuntime,
        handlers: Mapping[str, JobHandler],
        *,
        worker_id: str,
        poll_seconds: float,
        lease_for: timedelta = timedelta(minutes=5),
    ) -> None:
        self._queue = queue
        self._handlers = handlers
        self._worker_id = worker_id
        self._poll_seconds = poll_seconds
        self._lease_for = lease_for

    def run_once(self) -> bool:
        leased = self._queue.lease(self._worker_id, lease_for=self._lease_for)
        if leased is None:
            return False
        self._execute(leased)
        return True

    def run_forever(self, stop: Event) -> None:
        while not stop.is_set():
            if not self.run_once():
                stop.wait(self._poll_seconds)

    def _execute(self, leased: LeasedJob) -> None:
        handler = self._handlers.get(leased.kind)
        if handler is None:
            self._queue.fail(
                leased.id,
                self._worker_id,
                error_code="unknown_job_kind",
                retry_after=None,
            )
            return

        try:
            handler(leased.payload)
        except RetryableJobError as error:
            self._queue.fail(
                leased.id,
                self._worker_id,
                error_code=error.error_code,
                retry_after=error.retry_after,
            )
        except TerminalJobError as error:
            self._queue.fail(
                leased.id,
                self._worker_id,
                error_code=error.error_code,
                retry_after=None,
            )
        except Exception:
            logger.exception("job handler failed", extra={"job_kind": leased.kind})
            delay_seconds = min(300, 5 * 2 ** (leased.attempt - 1))
            self._queue.fail(
                leased.id,
                self._worker_id,
                error_code="unhandled_exception",
                retry_after=timedelta(seconds=delay_seconds),
            )
        else:
            self._queue.complete(leased.id, self._worker_id)
