"""Owner-authored Transaction actions that preserve Financial History."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

from billzebub.financial_history import (
    CategoryAllocation,
    Correction,
    FinancialHistory,
    FinancialHistoryError,
    TransactionKind,
    TransactionSnapshot,
)
from billzebub.money import Money
from billzebub.persistence.models import Category

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class OwnerTransactionActionError(ValueError):
    """An owner action would violate the current Transaction's invariants."""


@dataclass(frozen=True, slots=True)
class OwnerCategorizationCommand:
    transaction_id: UUID
    expected_version: int
    category_id: UUID
    actor_id: UUID


class OwnerTransactionActions:
    """Apply the small set of owner actions that change effective Transaction facts."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._history = FinancialHistory(database)

    def categorize(self, command: OwnerCategorizationCommand) -> TransactionSnapshot:
        with self._database.transaction() as session:
            return self._categorize_in_session(session, command)

    def _categorize_in_session(
        self,
        session: Session,
        command: OwnerCategorizationCommand,
    ) -> TransactionSnapshot:
        snapshot = self._history.current_in_session(session, command.transaction_id)
        if snapshot.version != command.expected_version:
            raise OwnerTransactionActionError("Transaction version is stale")
        if snapshot.kind not in {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}:
            raise OwnerTransactionActionError("only an Expense can be categorized")
        category = session.get(Category, command.category_id)
        if category is None or not category.active or self._is_uncategorized(category):
            raise OwnerTransactionActionError("Category is not available for categorization")
        try:
            return self._history.correct_in_session(
                session,
                Correction(
                    transaction_id=command.transaction_id,
                    reason="owner_categorization",
                    category_splits=(
                        CategoryAllocation(
                            category_id=category.id,
                            amount=Money(
                                abs(snapshot.posted_amount.amount),
                                snapshot.posted_amount.currency,
                            ),
                        ),
                    ),
                    actor_id=command.actor_id,
                ),
            )
        except FinancialHistoryError as error:
            raise OwnerTransactionActionError(str(error)) from error

    @staticmethod
    def _is_uncategorized(category: Category) -> bool:
        return category.parent_id is None and category.name == "Uncategorized"
