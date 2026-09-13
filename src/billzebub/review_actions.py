"""Route Pending Review decisions to the workflow that owns their side effects."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from billzebub.persistence.models import PendingReview
from billzebub.reconciliation import Reconciliation
from billzebub.reviews import PendingReviewRecord, ReviewDecision, ReviewError, ReviewInbox

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class ReviewActionError(ValueError):
    """A Pending Review cannot be resolved by the generic browser action."""


class ReviewActions:
    """Prevent a generic resolve button from bypassing specialized workflow policy."""

    _RECONCILIATION_CONDITIONS = frozenset({"reconciliation_ambiguous", "real_time_unconfirmed"})

    def __init__(self, database: Database) -> None:
        self._database = database
        self._inbox = ReviewInbox(database)
        self._reconciliation = Reconciliation(database)

    def decide(self, command: ReviewDecision) -> PendingReviewRecord:
        condition_code = self._condition_code(command.review_id)
        if condition_code in self._RECONCILIATION_CONDITIONS:
            return self._reconciliation.decide(command).review
        if condition_code.startswith("agent_proposal:"):
            return self._inbox.decide(command)
        if condition_code == "categorization_needed":
            raise ReviewActionError(
                "categorization reviews are resolved by categorizing the Transaction"
            )
        raise ReviewActionError("Pending Review requires a specialized workflow")

    def _condition_code(self, review_id: UUID) -> str:
        with self._database.transaction() as session:
            condition_code = session.scalar(
                select(PendingReview.condition_code).where(PendingReview.id == review_id)
            )
        if condition_code is None:
            raise ReviewError("Pending Review was not found")
        return condition_code
