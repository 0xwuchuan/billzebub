import pytest
from uuid6 import uuid7

from billzebub.persistence.database import Database
from billzebub.reviews import (
    PendingReviewStatus,
    ReviewCondition,
    ReviewDecision,
    ReviewError,
    ReviewInbox,
    ReviewSeverity,
)


@pytest.mark.integration
def test_review_condition_has_one_versioned_active_review(database: Database) -> None:
    reviews = ReviewInbox(database)
    subject_id = uuid7()
    condition = ReviewCondition(
        subject_type="transaction",
        subject_id=subject_id,
        condition_code="category_ambiguous",
        severity=ReviewSeverity.ATTENTION,
        allowed_decisions=("choose_food", "choose_household"),
        context={"candidate_count": 2},
    )

    created = reviews.synchronize(condition, active=True)
    synchronized = reviews.synchronize(
        ReviewCondition(
            subject_type=condition.subject_type,
            subject_id=condition.subject_id,
            condition_code=condition.condition_code,
            severity=ReviewSeverity.BLOCKING,
            allowed_decisions=condition.allowed_decisions,
            context={"candidate_count": 3},
        ),
        active=True,
    )

    assert created is not None
    assert synchronized is not None
    assert synchronized.id == created.id
    assert synchronized.version == 2
    assert synchronized.severity is ReviewSeverity.BLOCKING
    assert synchronized.status is PendingReviewStatus.PENDING
    assert [event.event_type for event in reviews.history(created.id)] == [
        "created",
        "synchronized",
    ]


@pytest.mark.integration
def test_review_decision_is_permitted_and_optimistically_versioned(database: Database) -> None:
    reviews = ReviewInbox(database)
    review = reviews.synchronize(
        ReviewCondition(
            subject_type="claim",
            subject_id=uuid7(),
            condition_code="reconciliation_ambiguous",
            severity=ReviewSeverity.BLOCKING,
            allowed_decisions=("confirm_candidate", "reject_all"),
        ),
        active=True,
    )
    assert review is not None

    with pytest.raises(ReviewError, match="permitted"):
        reviews.decide(
            ReviewDecision(
                review_id=review.id,
                expected_version=review.version,
                choice="silently_mutate",
            )
        )
    with pytest.raises(ReviewError, match="version"):
        reviews.decide(
            ReviewDecision(
                review_id=review.id,
                expected_version=99,
                choice="reject_all",
            )
        )

    resolved = reviews.decide(
        ReviewDecision(
            review_id=review.id,
            expected_version=review.version,
            choice="reject_all",
        )
    )
    assert resolved.status is PendingReviewStatus.RESOLVED
    assert resolved.version == 2
    assert reviews.history(review.id)[-1].decision == "reject_all"


@pytest.mark.integration
def test_disappearing_condition_cancels_pending_review(database: Database) -> None:
    reviews = ReviewInbox(database)
    condition = ReviewCondition(
        subject_type="extraction",
        subject_id=uuid7(),
        condition_code="validation_failure",
        severity=ReviewSeverity.BLOCKING,
        allowed_decisions=("retry",),
    )
    review = reviews.synchronize(condition, active=True)
    assert review is not None

    cancelled = reviews.synchronize(condition, active=False)

    assert cancelled is not None
    assert cancelled.status is PendingReviewStatus.CANCELLED
    assert cancelled.version == 2
    assert reviews.synchronize(condition, active=False) is None
