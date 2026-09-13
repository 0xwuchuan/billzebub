"""Project only agent-safe Transaction resources and scoped mutations."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from billzebub.financial_history import (
    CategoryAllocation,
    Correction,
    FinancialHistory,
    FinancialHistoryError,
    TransactionKind,
    TransactionSnapshot,
)
from billzebub.idempotency import IdempotencyBook, IdempotencyError
from billzebub.money import Money
from billzebub.persistence.models import (
    Category,
    CategorySplit,
    FinancialTransaction,
    PendingReview,
    TransactionVersion,
)
from billzebub.reviews import ReviewCondition, ReviewInbox, ReviewSeverity

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class AgentFacadeError(ValueError):
    """An agent-safe request was invalid, stale, or not permitted."""


class ProposalType(StrEnum):
    CORRECTION = "correction"
    RECONCILIATION = "reconciliation"
    COUNTERPARTY_CHANGE = "counterparty_change"
    CATEGORY_SPLIT = "category_split"


@dataclass(frozen=True, slots=True)
class AgentCategory:
    id: UUID
    name: str
    parent_id: UUID | None

    def to_wire(self) -> dict[str, str | None]:
        return {
            "id": str(self.id),
            "name": self.name,
            "parent_id": str(self.parent_id) if self.parent_id is not None else None,
        }


@dataclass(frozen=True, slots=True)
class AgentCategoryAllocation:
    category: AgentCategory
    amount: Money

    def to_wire(self) -> dict[str, object]:
        return {"category": self.category.to_wire(), "amount": self.amount.to_wire()}


@dataclass(frozen=True, slots=True)
class AgentTransaction:
    id: UUID
    version: int
    counterparty: str
    amount: Money
    effective_date: date
    kind: TransactionKind
    categories: tuple[AgentCategoryAllocation, ...]
    review_choices: tuple[str, ...]

    def to_wire(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "version": self.version,
            "counterparty": self.counterparty,
            "amount": self.amount.to_wire(),
            "effective_date": self.effective_date.isoformat(),
            "kind": self.kind.value,
            "categories": [category.to_wire() for category in self.categories],
            "review_choices": list(self.review_choices),
        }


@dataclass(frozen=True, slots=True)
class AgentTransactionPage:
    items: tuple[AgentTransaction, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AgentReview:
    transaction_id: UUID
    choices: tuple[str, ...]

    def to_wire(self) -> dict[str, object]:
        return {"transaction_id": str(self.transaction_id), "choices": list(self.choices)}


@dataclass(frozen=True, slots=True)
class CategorizationCommand:
    transaction_id: UUID
    expected_version: int
    category_id: UUID
    actor_id: UUID


@dataclass(frozen=True, slots=True)
class ProposalCommand:
    transaction_id: UUID
    expected_version: int
    proposal_type: ProposalType
    summary: str
    actor_id: UUID


@dataclass(frozen=True, slots=True)
class AgentMutation:
    body: dict[str, Any]
    replayed: bool


class AgentFacade:
    """The sole seam through which an external agent reaches finance data."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._history = FinancialHistory(database)
        self._idempotency = IdempotencyBook(database)

    def list_transactions(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> AgentTransactionPage:
        if not 1 <= limit <= 100:
            raise AgentFacadeError("transaction page limit must be between 1 and 100")
        position = self._decode_cursor(cursor) if cursor is not None else None
        with self._database.transaction() as session:
            statement = (
                select(FinancialTransaction, TransactionVersion)
                .join(
                    TransactionVersion,
                    and_(
                        TransactionVersion.transaction_id == FinancialTransaction.id,
                        TransactionVersion.version == FinancialTransaction.current_version,
                    ),
                )
                .order_by(TransactionVersion.effective_date.desc(), FinancialTransaction.id.desc())
                .limit(limit + 1)
            )
            if position is not None:
                effective_date, transaction_id = position
                statement = statement.where(
                    or_(
                        TransactionVersion.effective_date < effective_date,
                        and_(
                            TransactionVersion.effective_date == effective_date,
                            FinancialTransaction.id < transaction_id,
                        ),
                    )
                )
            rows = session.execute(statement).all()
            page_rows = rows[:limit]
            items = tuple(
                self._transaction_from_models(session, transaction, version)
                for transaction, version in page_rows
            )
            next_cursor = None
            if len(rows) > limit and page_rows:
                last_transaction, last_version = page_rows[-1]
                next_cursor = self._encode_cursor(last_version.effective_date, last_transaction.id)
            return AgentTransactionPage(items=items, next_cursor=next_cursor)

    def get_transaction(self, transaction_id: UUID) -> AgentTransaction:
        with self._database.transaction() as session:
            transaction, version = self._current_models(session, transaction_id)
            return self._transaction_from_models(session, transaction, version)

    def list_categories(self) -> tuple[AgentCategory, ...]:
        with self._database.transaction() as session:
            categories = session.scalars(
                select(Category)
                .where(
                    Category.active.is_(True),
                    or_(Category.parent_id.is_not(None), Category.name != "Uncategorized"),
                )
                .order_by(Category.parent_id, Category.sort_order, Category.name, Category.id)
            ).all()
            return tuple(self._category(category) for category in categories)

    def list_reviews(self) -> tuple[AgentReview, ...]:
        with self._database.transaction() as session:
            reviews = session.scalars(
                select(PendingReview)
                .where(
                    PendingReview.subject_type == "transaction",
                    PendingReview.condition_code == "categorization_needed",
                    PendingReview.status == "pending",
                )
                .order_by(PendingReview.created_at, PendingReview.id)
            ).all()
            return tuple(
                AgentReview(
                    transaction_id=review.subject_id,
                    choices=tuple(review.allowed_decisions),
                )
                for review in reviews
            )

    def categorize(
        self,
        command: CategorizationCommand,
        *,
        principal: str,
        idempotency_key: str,
    ) -> AgentMutation:
        request = {
            "transaction_id": str(command.transaction_id),
            "expected_version": command.expected_version,
            "category_id": str(command.category_id),
        }

        def apply(session: Session) -> tuple[int, dict[str, Any]]:
            snapshot = self._history.current_in_session(session, command.transaction_id)
            if snapshot.version != command.expected_version:
                raise AgentFacadeError("Transaction version is stale")
            if snapshot.kind not in {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}:
                raise AgentFacadeError("only an Expense can be categorized")
            category = session.get(Category, command.category_id)
            if category is None or not category.active or self._is_uncategorized(category):
                raise AgentFacadeError("Category is not available for categorization")
            updated = self._history.correct_in_session(
                session,
                Correction(
                    transaction_id=command.transaction_id,
                    reason="agent_categorization",
                    category_splits=(
                        CategoryAllocation(
                            category_id=category.id,
                            amount=Money(
                                abs(snapshot.posted_amount.amount), snapshot.posted_amount.currency
                            ),
                        ),
                    ),
                    actor_id=command.actor_id,
                ),
            )
            return 200, self._wire_snapshot(session, updated)

        try:
            result = self._idempotency.execute(
                principal=principal,
                operation="agent.categorize",
                key=idempotency_key,
                request=request,
                action=apply,
            )
        except (FinancialHistoryError, IdempotencyError) as error:
            raise AgentFacadeError(str(error)) from error
        return AgentMutation(body=result.body, replayed=result.replayed)

    def propose(
        self,
        command: ProposalCommand,
        *,
        principal: str,
        idempotency_key: str,
    ) -> AgentMutation:
        summary = " ".join(command.summary.split())
        if not summary or len(summary) > 500:
            raise AgentFacadeError("proposal summary must contain at most 500 characters")
        request = {
            "transaction_id": str(command.transaction_id),
            "expected_version": command.expected_version,
            "proposal_type": command.proposal_type.value,
            "summary": summary,
        }

        def apply(session: Session) -> tuple[int, dict[str, Any]]:
            snapshot = self._history.current_in_session(session, command.transaction_id)
            if snapshot.version != command.expected_version:
                raise AgentFacadeError("Transaction version is stale")
            review = ReviewInbox.synchronize_in_session(
                session,
                ReviewCondition(
                    subject_type="transaction",
                    subject_id=command.transaction_id,
                    condition_code=f"agent_proposal:{command.proposal_type.value}",
                    severity=ReviewSeverity.ATTENTION,
                    allowed_decisions=("accept", "reject"),
                    context={
                        "proposal_type": command.proposal_type.value,
                        "summary": summary,
                        "expected_transaction_version": snapshot.version,
                    },
                ),
                active=True,
            )
            if review is None:
                raise AgentFacadeError("proposal review was not created")
            return 202, {
                "transaction_id": str(command.transaction_id),
                "proposal_type": command.proposal_type.value,
                "status": "pending",
            }

        try:
            result = self._idempotency.execute(
                principal=principal,
                operation=f"agent.propose.{command.proposal_type.value}",
                key=idempotency_key,
                request=request,
                action=apply,
            )
        except (FinancialHistoryError, IdempotencyError) as error:
            raise AgentFacadeError(str(error)) from error
        return AgentMutation(body=result.body, replayed=result.replayed)

    @staticmethod
    def _current_models(
        session: Session,
        transaction_id: UUID,
    ) -> tuple[FinancialTransaction, TransactionVersion]:
        transaction = session.get(FinancialTransaction, transaction_id)
        if transaction is None:
            raise AgentFacadeError("Transaction was not found")
        version = session.scalar(
            select(TransactionVersion).where(
                TransactionVersion.transaction_id == transaction.id,
                TransactionVersion.version == transaction.current_version,
            )
        )
        if version is None:
            raise AgentFacadeError("Transaction current version is missing")
        return transaction, version

    @classmethod
    def _transaction_from_models(
        cls,
        session: Session,
        transaction: FinancialTransaction,
        version: TransactionVersion,
    ) -> AgentTransaction:
        split_rows = session.execute(
            select(CategorySplit, Category)
            .join(Category, Category.id == CategorySplit.category_id)
            .where(CategorySplit.transaction_version_id == version.id)
            .order_by(CategorySplit.id)
        ).all()
        review = session.scalar(
            select(PendingReview)
            .where(
                PendingReview.subject_type == "transaction",
                PendingReview.subject_id == transaction.id,
                PendingReview.condition_code == "categorization_needed",
                PendingReview.status == "pending",
            )
            .order_by(PendingReview.created_at.desc(), PendingReview.id.desc())
            .limit(1)
        )
        return AgentTransaction(
            id=transaction.id,
            version=version.version,
            counterparty=version.counterparty,
            amount=Money(version.posted_amount, version.posted_currency),
            effective_date=version.effective_date,
            kind=TransactionKind(version.kind),
            categories=tuple(
                AgentCategoryAllocation(
                    category=cls._category(category),
                    amount=Money(split.amount, split.currency),
                )
                for split, category in split_rows
            ),
            review_choices=tuple(review.allowed_decisions) if review is not None else (),
        )

    @classmethod
    def _wire_snapshot(
        cls,
        session: Session,
        snapshot: TransactionSnapshot,
    ) -> dict[str, Any]:
        transaction, version = cls._current_models(session, snapshot.id)
        return cls._transaction_from_models(session, transaction, version).to_wire()

    @staticmethod
    def _category(category: Category) -> AgentCategory:
        return AgentCategory(id=category.id, name=category.name, parent_id=category.parent_id)

    @staticmethod
    def _is_uncategorized(category: Category) -> bool:
        return category.parent_id is None and category.name == "Uncategorized"

    @staticmethod
    def _encode_cursor(effective_date: date, transaction_id: UUID) -> str:
        payload = json.dumps(
            {"effective_date": effective_date.isoformat(), "transaction_id": str(transaction_id)},
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(payload).decode().rstrip("=")

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[date, UUID]:
        if not cursor or len(cursor) > 512:
            raise AgentFacadeError("transaction cursor is invalid")
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
            return date.fromisoformat(payload["effective_date"]), UUID(payload["transaction_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise AgentFacadeError("transaction cursor is invalid") from error
