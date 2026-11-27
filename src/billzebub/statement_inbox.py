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


@dataclass(frozen=True, slots=True)
class _Account:
    id: UUID
    slug: str


@dataclass(frozen=True, slots=True)
class _InboxFile:
    account_id: UUID
    path: Path
    size: int
    modified_ns: int

    @property
    def key(self) -> tuple[UUID, str, int, int]:
        return (self.account_id, self.path.name, self.size, self.modified_ns)


@dataclass(frozen=True, slots=True)
class _ExistingObservation:
    id: UUID
    status: str
    first_observed_at: datetime


@dataclass(frozen=True, slots=True)
class _SeenFile:
    id: UUID
    created: bool
    status: str
    first_observed_at: datetime
    account_id: UUID
    path: Path
    size: int
    modified_ns: int


class StatementInbox:
    """Poll configured folders and leave captured PDFs in the account inbox."""

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
        files: list[_InboxFile] = []
        for account in self._active_accounts():
            folder = (self._inbox_root / account.slug).resolve()
            if folder.parent != self._inbox_root:
                errors += 1
                continue
            folder.mkdir(mode=0o700, parents=True, exist_ok=True)
            for path in sorted(folder.iterdir(), key=lambda candidate: candidate.name):
                if path.is_symlink() or not path.is_file() or path.suffix.casefold() != ".pdf":
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    errors += 1
                    continue
                files.append(
                    _InboxFile(
                        account_id=account.id,
                        path=path,
                        size=stat.st_size,
                        modified_ns=stat.st_mtime_ns,
                    )
                )

        for seen in self._observe_all(files, now):
            if seen.created:
                observed += 1
                continue
            if seen.status == "captured":
                continue
            if now - seen.first_observed_at < self._stable_for:
                continue
            try:
                result = self._capture_stable(seen, now)
            except OSError:
                errors += 1
                continue
            captured += result.captured
            enqueued += result.enqueued
            errors += result.errors

        return InboxPollResult(
            observed=observed,
            captured=captured,
            enqueued=enqueued,
            errors=errors,
        )

    def _active_accounts(self) -> list[_Account]:
        with self._database.read() as session:
            rows = session.execute(
                select(FinancialAccount.id, FinancialAccount.slug)
                .where(
                    FinancialAccount.active.is_(True),
                    FinancialAccount.statement_adapter_key.is_not(None),
                )
                .order_by(FinancialAccount.slug)
            ).all()
        return [_Account(id=row.id, slug=row.slug) for row in rows]

    def _observe_all(self, files: list[_InboxFile], now: datetime) -> list[_SeenFile]:
        """Record new files and refresh uncaptured ones in one transaction per poll.

        Captured fingerprints are read and left unchanged, so an idle inbox
        does not write.
        """
        if not files:
            return []
        existing = self._existing_observations(files)
        captured_only = True
        for file in files:
            row = existing.get(file.key)
            if row is None or row.status != "captured":
                captured_only = False
                break
        if captured_only:
            return [
                _SeenFile(
                    id=existing[file.key].id,
                    created=False,
                    status="captured",
                    first_observed_at=existing[file.key].first_observed_at,
                    account_id=file.account_id,
                    path=file.path,
                    size=file.size,
                    modified_ns=file.modified_ns,
                )
                for file in files
            ]

        with self._database.transaction() as session:
            seen: list[_SeenFile] = []
            for file in files:
                observation = session.scalar(
                    select(InboxFileObservation).where(
                        InboxFileObservation.financial_account_id == file.account_id,
                        InboxFileObservation.file_name == file.path.name,
                        InboxFileObservation.size == file.size,
                        InboxFileObservation.modified_ns == file.modified_ns,
                    )
                )
                created = False
                if observation is None:
                    observation = InboxFileObservation(
                        id=uuid7(),
                        financial_account_id=file.account_id,
                        file_name=file.path.name,
                        size=file.size,
                        modified_ns=file.modified_ns,
                        first_observed_at=now,
                        last_observed_at=now,
                        status="observed",
                    )
                    session.add(observation)
                    created = True
                elif observation.status != "captured":
                    observation.last_observed_at = now
                seen.append(
                    _SeenFile(
                        id=observation.id,
                        created=created,
                        status=observation.status,
                        first_observed_at=observation.first_observed_at,
                        account_id=file.account_id,
                        path=file.path,
                        size=file.size,
                        modified_ns=file.modified_ns,
                    )
                )
            return seen

    def _existing_observations(
        self,
        files: list[_InboxFile],
    ) -> dict[tuple[UUID, str, int, int], _ExistingObservation]:
        account_ids = {file.account_id for file in files}
        with self._database.read() as session:
            rows = session.execute(
                select(
                    InboxFileObservation.id,
                    InboxFileObservation.financial_account_id,
                    InboxFileObservation.file_name,
                    InboxFileObservation.size,
                    InboxFileObservation.modified_ns,
                    InboxFileObservation.status,
                    InboxFileObservation.first_observed_at,
                ).where(InboxFileObservation.financial_account_id.in_(account_ids))
            ).all()
        return {
            (row.financial_account_id, row.file_name, row.size, row.modified_ns): (
                _ExistingObservation(
                    id=row.id,
                    status=row.status,
                    first_observed_at=row.first_observed_at,
                )
            )
            for row in rows
        }

    def _capture_stable(self, seen: _SeenFile, now: datetime) -> InboxPollResult:
        artifact = self._artifact_capture.capture_file(
            seen.path,
            ArtifactArrivalInput(
                source_type="statement_inbox",
                media_type="application/pdf",
                received_at=now,
                original_name=seen.path.name,
                metadata={"financial_account_id": str(seen.account_id)},
            ),
        )
        after = seen.path.stat()
        if after.st_size != seen.size or after.st_mtime_ns != seen.modified_ns:
            return InboxPollResult(errors=1)

        job = self._queue.enqueue(
            "extract_statement",
            {
                "artifact_id": str(artifact.id),
                "financial_account_id": str(seen.account_id),
            },
            dedupe_key=f"{artifact.id}:{seen.account_id}",
        )
        self._mark_captured(seen.id, artifact.id, now)
        return InboxPollResult(captured=1, enqueued=0 if job.duplicate else 1)

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
