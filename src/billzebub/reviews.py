"""Durable Pending Review conditions and immutable decision history."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from uuid6 import uuid7

from billzebub.persistence.models import Extraction, PendingReview, ReviewEvent

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class ReviewSeverity(StrEnum):
    ATTENTION = "attention"
    BLOCKING = "blocking"


class PendingReviewStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class ReviewError(ValueError):
    """Review policy or optimistic concurrency rejected a command."""


STATEMENT_REPROCESS_CONDITION_PREFIX = "statement_reprocess:"


def categorization_needed_context(
    *,
    transaction_id: UUID,
    counterparty: str,
    amount: str,
    currency: str,
    account: str,
    financial_account_id: UUID,
    effective_date: str,
    version: int,
    kind: str,
) -> dict[str, Any]:
    """Display fields so a categorization card can render without a Transaction join."""
    return {
        "transaction_id": str(transaction_id),
        "counterparty": counterparty,
        "amount": amount,
        "currency": currency,
        "account": account,
        "financial_account_id": str(financial_account_id),
        "effective_date": effective_date,
        "version": version,
        "kind": kind,
    }


def merge_categorization_context(
    context: Mapping[str, Any],
    display: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Overlay live Transaction display fields without dropping other context keys."""
    merged = dict(context)
    if display:
        merged.update(display)
    return merged


@dataclass(frozen=True, slots=True)
class ReviewCondition:
    subject_type: str
    subject_id: UUID
    condition_code: str
    severity: ReviewSeverity
    allowed_decisions: tuple[str, ...]
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    review_id: UUID
    expected_version: int
    choice: str
    actor_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PendingReviewRecord:
    id: UUID
    subject_type: str
    subject_id: UUID
    condition_code: str
    severity: ReviewSeverity
    status: PendingReviewStatus
    version: int
    allowed_decisions: tuple[str, ...]
    context: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewEventRecord:
    id: UUID
    review_id: UUID
    version: int
    event_type: str
    decision: str | None
    occurred_at: datetime


class ReviewInbox:
    """Synchronize durable conditions and apply only versioned permitted decisions."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def synchronize(
        self,
        condition: ReviewCondition,
        *,
        active: bool,
    ) -> PendingReviewRecord | None:
        with self._database.transaction() as session:
            return self.synchronize_in_session(session, condition, active=active)

    @classmethod
    def synchronize_in_session(
        cls,
        session: Session,
        condition: ReviewCondition,
        *,
        active: bool,
    ) -> PendingReviewRecord | None:
        """Synchronize one condition within a caller-owned database transaction."""
        cls._validate_condition(condition)
        review = session.scalar(
            select(PendingReview)
            .where(
                PendingReview.subject_type == condition.subject_type,
                PendingReview.subject_id == condition.subject_id,
                PendingReview.condition_code == condition.condition_code,
                PendingReview.status == PendingReviewStatus.PENDING.value,
            )
            .with_for_update()
        )
        if not active:
            if review is None:
                return None
            review.status = PendingReviewStatus.CANCELLED.value
            review.version += 1
            review.updated_at = datetime.now(UTC)
            cls._event(session, review, "cancelled")
            session.flush()
            return cls._record(review)

        if review is None:
            review = PendingReview(
                id=uuid7(),
                subject_type=condition.subject_type,
                subject_id=condition.subject_id,
                condition_code=condition.condition_code,
                severity=condition.severity.value,
                status=PendingReviewStatus.PENDING.value,
                version=1,
                allowed_decisions=list(condition.allowed_decisions),
                context=dict(condition.context),
            )
            session.add(review)
            session.flush()
            cls._event(session, review, "created")
            session.flush()
            return cls._record(review)

        unchanged = (
            review.severity == condition.severity.value
            and tuple(review.allowed_decisions) == condition.allowed_decisions
            and review.context == condition.context
        )
        if unchanged:
            return cls._record(review)
        review.severity = condition.severity.value
        review.allowed_decisions = list(condition.allowed_decisions)
        review.context = dict(condition.context)
        review.version += 1
        review.updated_at = datetime.now(UTC)
        cls._event(session, review, "synchronized")
        session.flush()
        return cls._record(review)

    def decide(self, command: ReviewDecision) -> PendingReviewRecord:
        with self._database.transaction() as session:
            return self.decide_in_session(session, command)

    @classmethod
    def decide_in_session(
        cls,
        session: Session,
        command: ReviewDecision,
    ) -> PendingReviewRecord:
        """Resolve one review within a caller-owned database transaction."""
        review = session.scalar(
            select(PendingReview).where(PendingReview.id == command.review_id).with_for_update()
        )
        if review is None:
            raise ReviewError("Pending Review was not found")
        if review.status != PendingReviewStatus.PENDING.value:
            raise ReviewError("Pending Review is no longer Pending")
        if command.expected_version != review.version:
            raise ReviewError("Pending Review version is stale")
        if command.choice not in review.allowed_decisions:
            raise ReviewError("decision is not permitted for this Pending Review")

        review.status = PendingReviewStatus.RESOLVED.value
        review.version += 1
        review.updated_at = datetime.now(UTC)
        cls._event(
            session,
            review,
            "resolved",
            decision=command.choice,
            actor_id=command.actor_id,
        )
        session.flush()
        return cls._record(review)

    def history(self, review_id: UUID) -> tuple[ReviewEventRecord, ...]:
        with self._database.transaction() as session:
            if session.get(PendingReview, review_id) is None:
                raise ReviewError("Pending Review was not found")
            events = session.scalars(
                select(ReviewEvent)
                .where(ReviewEvent.review_id == review_id)
                .order_by(ReviewEvent.version)
            ).all()
            return tuple(
                ReviewEventRecord(
                    id=event.id,
                    review_id=event.review_id,
                    version=event.version,
                    event_type=event.event_type,
                    decision=event.decision,
                    occurred_at=event.occurred_at,
                )
                for event in events
            )

    @staticmethod
    def _event(
        session: Session,
        review: PendingReview,
        event_type: str,
        *,
        decision: str | None = None,
        actor_id: UUID | None = None,
    ) -> None:
        session.add(
            ReviewEvent(
                id=uuid7(),
                review_id=review.id,
                version=review.version,
                event_type=event_type,
                decision=decision,
                actor_id=actor_id,
            )
        )

    @staticmethod
    def _validate_condition(condition: ReviewCondition) -> None:
        if not condition.subject_type.strip() or not condition.condition_code.strip():
            raise ReviewError("Review condition identifiers are required")
        if not condition.allowed_decisions:
            raise ReviewError("Review condition requires permitted decisions")
        if any(not decision.strip() for decision in condition.allowed_decisions):
            raise ReviewError("Review decisions cannot be empty")
        if len(set(condition.allowed_decisions)) != len(condition.allowed_decisions):
            raise ReviewError("Review decisions must be unique")

    @staticmethod
    def _record(review: PendingReview) -> PendingReviewRecord:
        return PendingReviewRecord(
            id=review.id,
            subject_type=review.subject_type,
            subject_id=review.subject_id,
            condition_code=review.condition_code,
            severity=ReviewSeverity(review.severity),
            status=PendingReviewStatus(review.status),
            version=review.version,
            allowed_decisions=tuple(review.allowed_decisions),
            context=dict(review.context),
            created_at=review.created_at,
            updated_at=review.updated_at,
        )


def cancel_pending_reviews_for_dismissed_extractions(
    session: Session,
    extraction_ids: Iterable[UUID],
) -> None:
    """Cancel pending reviews tied to dismissed failed Extractions.

    Extraction-keyed reviews are cancelled for those Extractions. Source Artifact
    reviews are cancelled as well, which is how rejected Shortcut payloads are keyed.
    Statement reprocess reviews stay pending; they decide an accepted Extraction.
    """
    ids = tuple(dict.fromkeys(extraction_ids))
    if not ids:
        return
    artifact_ids = tuple(
        dict.fromkeys(
            session.scalars(select(Extraction.artifact_id).where(Extraction.id.in_(ids))).all()
        )
    )
    conditions = [
        (PendingReview.subject_type == "extraction") & (PendingReview.subject_id.in_(ids))
    ]
    if artifact_ids:
        conditions.append(
            (PendingReview.subject_type == "source_artifact")
            & (PendingReview.subject_id.in_(artifact_ids))
            & ~PendingReview.condition_code.startswith(STATEMENT_REPROCESS_CONDITION_PREFIX)
        )
    reviews = session.scalars(
        select(PendingReview)
        .where(PendingReview.status == PendingReviewStatus.PENDING.value, or_(*conditions))
        .with_for_update()
    ).all()
    now = datetime.now(UTC)
    for review in reviews:
        review.status = PendingReviewStatus.CANCELLED.value
        review.version += 1
        review.updated_at = now
        ReviewInbox._event(session, review, "cancelled")
    if reviews:
        session.flush()


def dismissed_failure_review_clause() -> ColumnElement[bool]:
    """Pending reviews whose linked failed Extraction is already dismissed."""
    dismissed_extraction = exists(
        select(Extraction.id)
        .where(
            Extraction.id == PendingReview.subject_id,
            Extraction.dismissed_at.is_not(None),
        )
        .correlate(PendingReview)
    )
    dismissed_artifact = exists(
        select(Extraction.id)
        .where(
            Extraction.artifact_id == PendingReview.subject_id,
            Extraction.status == "failed",
            Extraction.dismissed_at.is_not(None),
        )
        .correlate(PendingReview)
    )
    return or_(
        and_(PendingReview.subject_type == "extraction", dismissed_extraction),
        and_(
            PendingReview.subject_type == "source_artifact",
            ~PendingReview.condition_code.startswith(STATEMENT_REPROCESS_CONDITION_PREFIX),
            dismissed_artifact,
        ),
    )
