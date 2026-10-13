"""Owner command to re-extract one excluded statement Source Artifact."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.jobs import JobQueue
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    AuditActor,
    AuditActorKind,
    Extraction,
    FinancialAccount,
    PendingReview,
    ReviewEvent,
    SourceArtifact,
)
from billzebub.reviews import ReviewInbox
from billzebub.statement_extraction import (
    ExtractionStatus,
    StatementAdapterError,
    StatementAdapterRegistry,
    StatementExtraction,
)

_SYSTEM_ACTOR_KEY = "statement-reextract"
_EXCLUDE_DECISION = "exclude_source_artifact"
_REEXTRACT_REQUESTED = "reextract_requested"
_RECONCILE_JOB = "reconcile_financial_account"


class StatementReextractError(ValueError):
    """The Source Artifact cannot be re-extracted."""


class StatementReextractAction(StrEnum):
    EXTRACTED = "extracted"
    VERSION_UNCHANGED = "version_unchanged"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class StatementReextractReport:
    artifact_id: UUID
    action: StatementReextractAction
    extraction_id: UUID | None
    status: str | None
    claim_count: int
    enqueued_reconciliation: bool


@dataclass(frozen=True, slots=True)
class _CurrentExtraction:
    extraction_id: UUID
    status: str
    claim_count: int


@dataclass(frozen=True, slots=True)
class _ReextractPlan:
    artifact_id: UUID
    account_id: UUID
    review_id: UUID
    current: _CurrentExtraction | None


class StatementReextractor:
    """Re-extract excluded statement artifacts at the account's current adapter.

    A second call changes nothing. The same parser version as the excluded
    failure does not run the adapter again.
    """

    def __init__(
        self,
        database: Database,
        extraction: StatementExtraction,
        adapters: StatementAdapterRegistry,
        queue: JobQueue,
    ) -> None:
        self._database = database
        self._extraction = extraction
        self._adapters = adapters
        self._queue = queue

    def reextract(self, artifact_ids: tuple[UUID, ...]) -> tuple[StatementReextractReport, ...]:
        identifiers = tuple(dict.fromkeys(artifact_ids))
        if not identifiers:
            raise StatementReextractError("reextract requires an artifact id")
        plans = tuple(self._plan(artifact_id) for artifact_id in identifiers)
        return tuple(self._run(plan) for plan in plans)

    def _plan(self, artifact_id: UUID) -> _ReextractPlan:
        with self._database.transaction() as session:
            artifact = session.get(SourceArtifact, artifact_id)
            if artifact is None:
                raise StatementReextractError("Source Artifact was not found")
            if artifact.media_type != "application/pdf":
                raise StatementReextractError("Source Artifact is not a statement PDF")
            excluded = session.execute(
                select(Extraction, PendingReview)
                .join(
                    PendingReview,
                    (PendingReview.subject_type == "extraction")
                    & (PendingReview.subject_id == Extraction.id),
                )
                .join(ReviewEvent, ReviewEvent.review_id == PendingReview.id)
                .where(
                    Extraction.artifact_id == artifact_id,
                    Extraction.status == "failed",
                    PendingReview.status == "resolved",
                    ReviewEvent.event_type == "resolved",
                    ReviewEvent.decision == _EXCLUDE_DECISION,
                )
                .order_by(Extraction.created_at.desc(), Extraction.id.desc())
            ).first()
            if excluded is None:
                raise StatementReextractError(
                    "Source Artifact is not an excluded statement failure"
                )
            extraction, review = excluded
            if extraction.financial_account_id is None:
                raise StatementReextractError("excluded Extraction has no Financial Account")
            account = session.get(FinancialAccount, extraction.financial_account_id)
            if account is None or account.statement_adapter_key is None:
                raise StatementReextractError("Financial Account has no statement adapter")
            try:
                adapter = self._adapters.get(account.statement_adapter_key)
            except StatementAdapterError as error:
                raise StatementReextractError("statement adapter is not configured") from error
            current_row = session.scalar(
                select(Extraction).where(
                    Extraction.artifact_id == artifact_id,
                    Extraction.financial_account_id == account.id,
                    Extraction.adapter_key == adapter.key,
                    Extraction.parser_version == adapter.version,
                )
            )
            current = None
            if current_row is not None:
                current = _CurrentExtraction(
                    extraction_id=current_row.id,
                    status=current_row.status,
                    claim_count=current_row.claim_count,
                )
            elif (
                session.scalar(
                    select(Extraction.id).where(
                        Extraction.artifact_id == artifact_id,
                        Extraction.financial_account_id == account.id,
                        Extraction.status == "accepted",
                    )
                )
                is not None
            ):
                raise StatementReextractError("accepted Extraction cannot be reextracted")
            return _ReextractPlan(
                artifact_id=artifact_id,
                account_id=account.id,
                review_id=review.id,
                current=current,
            )

    def _run(self, plan: _ReextractPlan) -> StatementReextractReport:
        if plan.current is not None:
            action = (
                StatementReextractAction.VERSION_UNCHANGED
                if plan.current.status == "failed"
                else StatementReextractAction.UNCHANGED
            )
            return StatementReextractReport(
                artifact_id=plan.artifact_id,
                action=action,
                extraction_id=plan.current.extraction_id,
                status=plan.current.status,
                claim_count=plan.current.claim_count,
                enqueued_reconciliation=False,
            )
        self._record_request(plan.review_id)
        outcome = self._extraction.extract(
            artifact_id=plan.artifact_id,
            financial_account_id=plan.account_id,
        )
        enqueued = False
        if outcome.status is ExtractionStatus.ACCEPTED and not outcome.duplicate:
            queued = self._queue.enqueue(
                _RECONCILE_JOB,
                {"financial_account_id": str(plan.account_id)},
                dedupe_key=str(plan.account_id),
            )
            enqueued = not queued.duplicate
        return StatementReextractReport(
            artifact_id=plan.artifact_id,
            action=StatementReextractAction.EXTRACTED,
            extraction_id=outcome.extraction_id,
            status=outcome.status.value,
            claim_count=outcome.claim_count,
            enqueued_reconciliation=enqueued,
        )

    def _record_request(self, review_id: UUID) -> None:
        with self._database.transaction() as session:
            review = session.get(PendingReview, review_id, with_for_update=True)
            if review is None or review.status != "resolved":
                raise StatementReextractError("exclusion review is no longer resolved")
            review.version += 1
            review.updated_at = datetime.now(UTC)
            actor_id = _system_actor_id(session)
            ReviewInbox._event(
                session,
                review,
                _REEXTRACT_REQUESTED,
                actor_id=actor_id,
            )
            session.flush()


def format_statement_reextract(report: StatementReextractReport) -> str:
    """One stable line for the owner CLI."""
    if report.action is StatementReextractAction.VERSION_UNCHANGED:
        return f"artifact_id={report.artifact_id} parser version bump required"
    if report.action is StatementReextractAction.UNCHANGED:
        return (
            f"artifact_id={report.artifact_id} extraction_id={report.extraction_id} "
            f"status={report.status} unchanged"
        )
    reconcile = " reconcile=enqueued" if report.enqueued_reconciliation else ""
    return (
        f"artifact_id={report.artifact_id} extraction_id={report.extraction_id} "
        f"status={report.status} claim_count={report.claim_count}{reconcile}"
    )


def _system_actor_id(session: Session) -> UUID:
    inserted = session.execute(
        insert(AuditActor)
        .values(
            id=uuid7(),
            kind=AuditActorKind.SYSTEM.value,
            label="Statement reextract",
            external_key=_SYSTEM_ACTOR_KEY,
        )
        .on_conflict_do_nothing(
            index_elements=(AuditActor.kind, AuditActor.external_key),
        )
        .returning(AuditActor.id)
    ).scalar_one_or_none()
    if inserted is not None:
        return inserted
    actor_id = session.scalar(
        select(AuditActor.id).where(
            AuditActor.kind == AuditActorKind.SYSTEM.value,
            AuditActor.external_key == _SYSTEM_ACTOR_KEY,
        )
    )
    if actor_id is None:
        raise StatementReextractError("statement reextract audit actor disappeared")
    return actor_id
