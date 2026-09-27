"""Owner-facing projection of Source Artifact Extraction history."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session

from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    ArtifactArrival,
    Claim,
    Extraction,
    FinancialAccount,
    InboxFileObservation,
    PendingReview,
    ReviewEvent,
    SourceArtifact,
)
from billzebub.reviews import cancel_pending_reviews_for_dismissed_extractions
from billzebub.statement_coverage import (
    DEFAULT_WINDOW_MONTHS,
    StatementCoverageReport,
    report_for_session,
    reporting_today,
)

SHORTCUT_ADAPTER_KEYS = frozenset({"apple_wallet_shortcut", "paylah_shortcut"})
JUNK_FAILURE_CODES = frozenset(
    {
        "unmapped_card",
        "unsupported_source",
        "unsupported_schema_version",
        "invalid_payload_shape",
        "invalid_payload_values",
        "invalid_json",
        "invalid_amount",
        "invalid_occurrence_time",
        "invalid_card_label",
    }
)
JUNK_FAILURE_PREFIXES = ("invalid_payload_", "unsupported_")


class ImportNotFoundError(LookupError):
    """No Extraction exists for the requested import identifier."""


class ImportNotDismissableError(ValueError):
    """Only failed Extractions may be dismissed."""


@dataclass(frozen=True, slots=True)
class ImportRecord:
    id: UUID
    source_artifact_id: UUID
    financial_account_id: UUID | None
    financial_account_name: str | None
    status: str
    adapter_key: str | None
    parser_version: str
    statement_date: date | None
    period_start: date | None
    period_end: date | None
    candidate_row_count: int | None
    claim_count: int
    failure_code: str | None
    validation_report: dict[str, Any]
    duplicate_arrivals: int
    active_review_id: UUID | None
    supersedes_extraction_id: UUID | None
    created_at: datetime
    accepted_at: datetime | None
    dismissed_at: datetime | None


@dataclass(frozen=True, slots=True)
class FailedImportPurgeReport:
    extraction_ids: tuple[UUID, ...]
    artifact_ids: tuple[UUID, ...]
    skipped_extraction_ids: tuple[UUID, ...]
    dry_run: bool


def is_junk_shortcut_failure(
    *,
    status: str,
    adapter_key: str | None,
    failure_code: str | None,
) -> bool:
    """Match historical Shortcut/probe junk without touching statement failures."""
    if status != "failed" or adapter_key not in SHORTCUT_ADAPTER_KEYS:
        return False
    code = failure_code or ""
    return code in JUNK_FAILURE_CODES or code.startswith(JUNK_FAILURE_PREFIXES)


class ImportCatalog:
    """Project sanitized import diagnostics without exposing statement contents."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def list(self, *, include_dismissed: bool = False) -> tuple[ImportRecord, ...]:
        with self._database.transaction() as session:
            query = select(Extraction).order_by(Extraction.created_at.desc(), Extraction.id.desc())
            if not include_dismissed:
                query = query.where(Extraction.dismissed_at.is_(None))
            extractions = session.scalars(query).all()
            return tuple(self._record(session, extraction) for extraction in extractions)

    def get(self, extraction_id: UUID) -> ImportRecord:
        with self._database.transaction() as session:
            extraction = session.get(Extraction, extraction_id)
            if extraction is None:
                raise ImportNotFoundError(str(extraction_id))
            return self._record(session, extraction)

    def dismiss(self, extraction_id: UUID) -> ImportRecord:
        with self._database.transaction() as session:
            extraction = session.get(Extraction, extraction_id)
            if extraction is None:
                raise ImportNotFoundError(str(extraction_id))
            if extraction.status != "failed":
                raise ImportNotDismissableError("only failed Extractions may be dismissed")
            if extraction.dismissed_at is None:
                extraction.dismissed_at = datetime.now(UTC)
                session.flush()
            cancel_pending_reviews_for_dismissed_extractions(session, (extraction.id,))
            return self._record(session, extraction)

    def dismiss_failed(self) -> int:
        with self._database.transaction() as session:
            ids = session.scalars(
                select(Extraction.id).where(
                    Extraction.status == "failed", Extraction.dismissed_at.is_(None)
                )
            ).all()
            if not ids:
                return 0
            session.execute(
                update(Extraction)
                .where(Extraction.id.in_(ids))
                .values(dismissed_at=datetime.now(UTC))
            )
            session.flush()
            cancel_pending_reviews_for_dismissed_extractions(session, ids)
            return len(ids)

    def purge_failed(
        self, *, dry_run: bool = True, all_failed: bool = False
    ) -> FailedImportPurgeReport:
        """Hard-delete failed junk Extractions. Never deletes accepted work or Claims."""
        with self._database.transaction() as session:
            query = select(Extraction).where(Extraction.status == "failed")
            if not dry_run:
                query = query.with_for_update()
            candidates = session.scalars(query).all()
            selected = [
                extraction
                for extraction in candidates
                if all_failed
                or is_junk_shortcut_failure(
                    status=extraction.status,
                    adapter_key=extraction.adapter_key,
                    failure_code=extraction.failure_code,
                )
            ]
            selected_ids = {extraction.id for extraction in selected}
            if not selected_ids:
                return FailedImportPurgeReport((), (), (), dry_run)
            claimed_ids = set(
                session.scalars(
                    select(Claim.extraction_id).where(Claim.extraction_id.in_(selected_ids))
                ).all()
            )
            externally_referenced = set(
                session.scalars(
                    select(Extraction.supersedes_extraction_id).where(
                        Extraction.supersedes_extraction_id.in_(selected_ids),
                        Extraction.id.notin_(selected_ids),
                    )
                ).all()
            )
            skipped = {
                extraction.id
                for extraction in selected
                if extraction.id in claimed_ids
                or extraction.claim_count > 0
                or extraction.id in externally_referenced
            }
            purge_ids = selected_ids - skipped
            artifact_ids = self._orphan_artifact_ids(session, purge_ids)
            if dry_run or not purge_ids:
                return FailedImportPurgeReport(
                    extraction_ids=tuple(sorted(purge_ids, key=str)),
                    artifact_ids=tuple(sorted(artifact_ids, key=str)),
                    skipped_extraction_ids=tuple(sorted(skipped, key=str)),
                    dry_run=dry_run,
                )

            review_ids = self._review_ids_for_purge(session, purge_ids, artifact_ids)
            remaining = set(purge_ids)
            with _purge_triggers_disabled(session):
                if review_ids:
                    session.execute(
                        delete(ReviewEvent).where(ReviewEvent.review_id.in_(review_ids))
                    )
                    session.execute(delete(PendingReview).where(PendingReview.id.in_(review_ids)))
                supersedes = {
                    extraction.id: extraction.supersedes_extraction_id
                    for extraction in selected
                    if extraction.id in remaining
                }
                while remaining:
                    referenced = {
                        target
                        for extraction_id, target in supersedes.items()
                        if extraction_id in remaining and target in remaining
                    }
                    wave = remaining - referenced
                    if not wave:
                        skipped.update(remaining)
                        break
                    session.execute(delete(Extraction).where(Extraction.id.in_(wave)))
                    remaining -= wave
                if artifact_ids:
                    session.execute(
                        delete(ArtifactArrival).where(ArtifactArrival.artifact_id.in_(artifact_ids))
                    )
                    session.execute(
                        delete(SourceArtifact).where(SourceArtifact.id.in_(artifact_ids))
                    )
            return FailedImportPurgeReport(
                extraction_ids=tuple(sorted(purge_ids - remaining, key=str)),
                artifact_ids=tuple(sorted(artifact_ids, key=str)),
                skipped_extraction_ids=tuple(sorted(skipped, key=str)),
                dry_run=False,
            )

    def coverage(
        self,
        *,
        months: int = DEFAULT_WINDOW_MONTHS,
        as_of: date | None = None,
    ) -> StatementCoverageReport:
        """Project calendar-month coverage from accepted Extraction periods."""
        as_of_date = as_of if as_of is not None else reporting_today()
        with self._database.transaction() as session:
            return report_for_session(session, as_of=as_of_date, months=months)

    @staticmethod
    def _orphan_artifact_ids(session: Session, purge_ids: set[UUID]) -> tuple[UUID, ...]:
        if not purge_ids:
            return ()
        artifact_ids = set(
            session.scalars(
                select(Extraction.artifact_id).where(Extraction.id.in_(purge_ids))
            ).all()
        )
        still_linked = set(
            session.scalars(
                select(Extraction.artifact_id).where(
                    Extraction.artifact_id.in_(artifact_ids),
                    Extraction.id.notin_(purge_ids),
                )
            ).all()
        )
        claimed_artifacts = set(
            session.scalars(
                select(Claim.source_artifact_id).where(Claim.source_artifact_id.in_(artifact_ids))
            ).all()
        )
        observed_artifacts = set(
            session.scalars(
                select(InboxFileObservation.artifact_id).where(
                    InboxFileObservation.artifact_id.in_(artifact_ids)
                )
            ).all()
        )
        safe = artifact_ids - still_linked - claimed_artifacts - observed_artifacts
        return tuple(safe)

    @staticmethod
    def _review_ids_for_purge(
        session: Session,
        purge_ids: set[UUID],
        artifact_ids: Iterable[UUID],
    ) -> tuple[UUID, ...]:
        artifact_id_set = set(artifact_ids)
        conditions = [
            (PendingReview.subject_type == "extraction") & (PendingReview.subject_id.in_(purge_ids))
        ]
        if artifact_id_set:
            conditions.append(
                (PendingReview.subject_type == "source_artifact")
                & (PendingReview.subject_id.in_(artifact_id_set))
            )
        return tuple(session.scalars(select(PendingReview.id).where(or_(*conditions))).all())

    @staticmethod
    def _record(session: Session, extraction: Extraction) -> ImportRecord:
        account_name: str | None = None
        if extraction.financial_account_id is not None:
            account_name = session.scalar(
                select(FinancialAccount.display_name).where(
                    FinancialAccount.id == extraction.financial_account_id
                )
            )
        arrivals = session.scalar(
            select(func.count(ArtifactArrival.id)).where(
                ArtifactArrival.artifact_id == extraction.artifact_id
            )
        )
        active_review_id = session.scalar(
            select(PendingReview.id)
            .where(
                PendingReview.status == "pending",
                or_(
                    (PendingReview.subject_type == "extraction")
                    & (PendingReview.subject_id == extraction.id),
                    (PendingReview.subject_type == "source_artifact")
                    & (PendingReview.subject_id == extraction.artifact_id),
                ),
            )
            .order_by(PendingReview.created_at.desc())
            .limit(1)
        )
        return ImportRecord(
            id=extraction.id,
            source_artifact_id=extraction.artifact_id,
            financial_account_id=extraction.financial_account_id,
            financial_account_name=account_name,
            status=extraction.status,
            adapter_key=extraction.adapter_key,
            parser_version=extraction.parser_version,
            statement_date=extraction.statement_date,
            period_start=extraction.period_start,
            period_end=extraction.period_end,
            candidate_row_count=extraction.candidate_row_count,
            claim_count=extraction.claim_count,
            failure_code=extraction.failure_code,
            validation_report=dict(extraction.validation_report),
            duplicate_arrivals=max(0, int(arrivals or 0) - 1),
            active_review_id=active_review_id,
            supersedes_extraction_id=extraction.supersedes_extraction_id,
            created_at=extraction.created_at,
            accepted_at=extraction.accepted_at,
            dismissed_at=extraction.dismissed_at,
        )


@contextmanager
def _purge_triggers_disabled(session: Session) -> Iterator[None]:
    session.execute(text("ALTER TABLE extraction DISABLE TRIGGER extraction_append_only"))
    session.execute(text("ALTER TABLE review_event DISABLE TRIGGER review_event_append_only"))
    try:
        yield
    finally:
        session.execute(text("ALTER TABLE review_event ENABLE TRIGGER review_event_append_only"))
        session.execute(text("ALTER TABLE extraction ENABLE TRIGGER extraction_append_only"))
