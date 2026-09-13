"""Owner-facing projection of Source Artifact Extraction history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    ArtifactArrival,
    Extraction,
    FinancialAccount,
    PendingReview,
)


class ImportNotFoundError(LookupError):
    """No Extraction exists for the requested import identifier."""


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


class ImportCatalog:
    """Project sanitized import diagnostics without exposing statement contents."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def list(self) -> tuple[ImportRecord, ...]:
        with self._database.transaction() as session:
            extractions = session.scalars(
                select(Extraction).order_by(Extraction.created_at.desc(), Extraction.id.desc())
            ).all()
            return tuple(self._record(session, extraction) for extraction in extractions)

    def get(self, extraction_id: UUID) -> ImportRecord:
        with self._database.transaction() as session:
            extraction = session.get(Extraction, extraction_id)
            if extraction is None:
                raise ImportNotFoundError(str(extraction_id))
            return self._record(session, extraction)

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
                PendingReview.subject_type == "extraction",
                PendingReview.subject_id == extraction.id,
                PendingReview.status == "pending",
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
        )
