import pytest
from sqlalchemy import select
from uuid6 import uuid7

from billzebub.identity import OwnerIdentity
from billzebub.owner_actors import OwnerActors
from billzebub.persistence.database import Database
from billzebub.persistence.models import AuditActor, AuditActorKind, PendingReview, ReviewEvent
from billzebub.review_actions import ReviewActionError, ReviewActions
from billzebub.reviews import (
    PendingReviewStatus,
    ReviewCondition,
    ReviewDecision,
    ReviewInbox,
    ReviewSeverity,
)


@pytest.mark.integration
def test_owner_review_action_resolves_agent_proposal_with_durable_actor(
    database: Database,
) -> None:
    review = ReviewInbox(database).synchronize(
        ReviewCondition(
            subject_type="transaction",
            subject_id=uuid7(),
            condition_code="agent_proposal:correction",
            severity=ReviewSeverity.ATTENTION,
            allowed_decisions=("accept", "reject"),
            context={"proposal_type": "correction", "summary": "Synthetic owner proposal"},
        ),
        active=True,
    )
    assert review is not None
    actor_id = OwnerActors(database).resolve(
        OwnerIdentity(login="owner@example.test", name="Synthetic Owner")
    )

    resolved = ReviewActions(database).decide(
        ReviewDecision(
            review_id=review.id,
            expected_version=review.version,
            choice="accept",
            actor_id=actor_id,
        )
    )

    assert resolved.status is PendingReviewStatus.RESOLVED
    assert resolved.version == 2
    with database.transaction() as session:
        actor = session.get(AuditActor, actor_id)
        event = session.scalar(
            select(ReviewEvent)
            .where(ReviewEvent.review_id == review.id, ReviewEvent.event_type == "resolved")
            .limit(1)
        )
        assert actor is not None
        assert actor.kind is AuditActorKind.OWNER
        assert event is not None
        assert event.actor_id == actor_id


@pytest.mark.integration
def test_generic_review_action_cannot_silently_clear_categorization(
    database: Database,
) -> None:
    review = ReviewInbox(database).synchronize(
        ReviewCondition(
            subject_type="transaction",
            subject_id=uuid7(),
            condition_code="categorization_needed",
            severity=ReviewSeverity.ATTENTION,
            allowed_decisions=("categorize",),
        ),
        active=True,
    )
    assert review is not None

    with pytest.raises(ReviewActionError, match="categorizing"):
        ReviewActions(database).decide(
            ReviewDecision(
                review_id=review.id,
                expected_version=review.version,
                choice="categorize",
            )
        )
    with database.transaction() as session:
        pending = session.get(PendingReview, review.id)
        assert pending is not None
        assert pending.status == "pending"
