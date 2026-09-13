"""Stable-file polling contract for account-specific statement inboxes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from uuid6 import uuid7

from billzebub.artifact_capture import ArtifactArrivalInput, ArtifactCapture
from billzebub.jobs import EnqueuedJob
from billzebub.persistence.database import Database
from billzebub.persistence.models import FinancialAccount, InboxFileObservation


class StatementJobQueue(Protocol):
    def enqueue(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        dedupe_key: str | None = None,
        max_attempts: int = 5,
        available_at: datetime | None = None,
    ) -> EnqueuedJob: ...


@dataclass(frozen=True, slots=True)
class InboxPollResult:
    observed: int = 0
    captured: int = 0
    enqueued: int = 0
    errors: int = 0


class StatementInbox:
    """Poll configured folders and remove files only after capture and enqueue."""

    def __init__(
        self,
        database: Database,
        artifact_capture: ArtifactCapture,
        queue: StatementJobQueue,
        *,
        inbox_root: Path,
        stable_for: timedelta,
    ) -> None:
        if stable_for <= timedelta(0):
            raise ValueError("statement stability duration must be positive")
        self._database = database
        self._artifact_capture = artifact_capture
        self._queue = queue
        self._inbox_root = inbox_root.expanduser().resolve()
        self._stable_for = stable_for

    def poll(self, now: datetime) -> InboxPollResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("statement inbox poll time must include a timezone")
        observed = captured = enqueued = errors = 0
        self._inbox_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with self._database.transaction() as session:
            accounts = session.scalars(
                select(FinancialAccount)
                .where(
                    FinancialAccount.active.is_(True),
                    FinancialAccount.statement_adapter_key.is_not(None),
                )
                .order_by(FinancialAccount.slug)
            ).all()

        for account in accounts:
            folder = (self._inbox_root / account.slug).resolve()
            if folder.parent != self._inbox_root:
                errors += 1
                continue
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            for path in sorted(folder.iterdir(), key=lambda candidate: candidate.name):
                if path.is_symlink() or not path.is_file() or path.suffix.casefold() != ".pdf":
                    continue
                try:
                    result = self._poll_file(account.id, path, now)
                except OSError:
                    errors += 1
                    continue
                observed += result.observed
                captured += result.captured
                enqueued += result.enqueued
                errors += result.errors

        return InboxPollResult(
            observed=observed,
            captured=captured,
            enqueued=enqueued,
            errors=errors,
        )

    def _poll_file(
        self,
        account_id: UUID,
        path: Path,
        now: datetime,
    ) -> InboxPollResult:
        before = path.stat()
        observation, created = self._observe(
            account_id,
            path.name,
            before.st_size,
            before.st_mtime_ns,
            now,
        )
        if created:
            return InboxPollResult(observed=1)
        if observation.status == "captured":
            return InboxPollResult()
        if now - observation.first_observed_at < self._stable_for:
            return InboxPollResult()

        artifact = self._artifact_capture.capture_file(
            path,
            ArtifactArrivalInput(
                source_type="statement_inbox",
                media_type="application/pdf",
                received_at=now,
                original_name=path.name,
                metadata={"financial_account_id": str(account_id)},
            ),
        )
        after = path.stat()
        if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
            return InboxPollResult(errors=1)

        job = self._queue.enqueue(
            "extract_statement",
            {
                "artifact_id": str(artifact.id),
                "financial_account_id": str(account_id),
            },
            dedupe_key=f"{artifact.id}:{account_id}",
        )
        path.unlink()
        self._mark_captured(observation.id, artifact.id, now)
        return InboxPollResult(captured=1, enqueued=0 if job.duplicate else 1)

    def _observe(
        self,
        account_id: UUID,
        file_name: str,
        size: int,
        modified_ns: int,
        now: datetime,
    ) -> tuple[InboxFileObservation, bool]:
        with self._database.transaction() as session:
            observation = session.scalar(
                select(InboxFileObservation).where(
                    InboxFileObservation.financial_account_id == account_id,
                    InboxFileObservation.file_name == file_name,
                    InboxFileObservation.size == size,
                    InboxFileObservation.modified_ns == modified_ns,
                )
            )
            if observation is not None:
                observation.last_observed_at = now
                session.flush()
                return observation, False
            observation = InboxFileObservation(
                id=uuid7(),
                financial_account_id=account_id,
                file_name=file_name,
                size=size,
                modified_ns=modified_ns,
                first_observed_at=now,
                last_observed_at=now,
                status="observed",
            )
            session.add(observation)
            session.flush()
            return observation, True

    def _mark_captured(
        self,
        observation_id: UUID,
        artifact_id: UUID,
        now: datetime,
    ) -> None:
        with self._database.transaction() as session:
            observation = session.get(InboxFileObservation, observation_id)
            if observation is None:
                raise RuntimeError("statement inbox observation disappeared")
            observation.status = "captured"
            observation.artifact_id = artifact_id
            observation.last_observed_at = now
