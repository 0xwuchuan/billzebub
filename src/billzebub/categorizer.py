"""Deterministic Expense categorization with explicit confidence and owner memory."""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.financial_history import (
    CategorySplitRecord,
    FinancialHistory,
    FinancialHistoryError,
    TransactionKind,
    TransactionSnapshot,
)
from billzebub.money import Money
from billzebub.owner_transaction_actions import (
    OwnerCategorizationCommand,
    OwnerTransactionActionError,
    OwnerTransactionActions,
)
from billzebub.persistence.models import (
    AuditActor,
    AuditActorKind,
    Category,
    CounterpartyCategoryMap,
)
from billzebub.reviews import ReviewCondition, ReviewInbox, ReviewSeverity

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class JobEnqueuer(Protocol):
    def enqueue(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        dedupe_key: str | None = None,
        max_attempts: int = 5,
        available_at: datetime | None = None,
    ) -> object: ...


CATEGORIZE_TRANSACTION_JOB = "categorize_transaction"
LEARNED_CONFIDENCE = Decimal("1.000")
CATEGORY_NAME_CONFIDENCE = Decimal("1.000")
KEYWORD_CONFIDENCE = Decimal("0.950")
ABSTAIN_CONFIDENCE = Decimal("0.000")
DEFAULT_MIN_CONFIDENCE = Decimal("1.000")
_UNCATEGORIZED = "Uncategorized"
_OWNER_SOURCE = "owner_categorization"
_KEYWORD_RULES: dict[str, frozenset[str]] = {
    "Dining": frozenset({"restaurant", "cafe", "coffee", "bakery", "diner", "eatery", "bistro"}),
    "Gifts": frozenset({"gift", "gifts", "florist", "flowers"}),
    "Groceries": frozenset({"grocery", "groceries", "grocer", "supermarket"}),
    "Health": frozenset({"pharmacy", "clinic", "hospital", "dental", "dentist", "medical"}),
    "Shopping": frozenset({"shopping", "mall", "boutique", "apparel"}),
    "Transport": frozenset({"taxi", "transit", "bus", "mrt", "parking", "rideshare"}),
    "Utilities": frozenset(
        {"utility", "utilities", "electric", "electricity", "water", "broadband", "internet"}
    ),
}


class CategorizerError(ValueError):
    """Categorizer policy rejected a requested operation."""


@dataclass(frozen=True, slots=True)
class CategoryHint:
    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class CategorizerProposal:
    category_id: UUID | None
    category_name: str | None
    confidence: Decimal
    source: str
    normalized_key: str

    @property
    def assigns(self) -> bool:
        return self.category_id is not None


def normalize_counterparty_key(value: str) -> str:
    """Collapse a Counterparty into a stable lookup key without inventing aliases."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(normalized.casefold().split())[:300]


def propose(
    *,
    counterparty: str,
    categories: Sequence[CategoryHint],
    learned: Mapping[str, UUID],
) -> CategorizerProposal:
    """Return one Category or abstain. Never guess when more than one Category fits."""
    key = normalize_counterparty_key(counterparty)
    active = {hint.id: hint for hint in categories if hint.name != _UNCATEGORIZED}
    if not key or not active:
        return CategorizerProposal(None, None, ABSTAIN_CONFIDENCE, "unknown", key)

    learned_id = learned.get(key)
    learned_hint = active.get(learned_id) if learned_id is not None else None
    if learned_hint is not None:
        return CategorizerProposal(
            learned_hint.id,
            learned_hint.name,
            LEARNED_CONFIDENCE,
            "learned_map",
            key,
        )

    tokens = frozenset(key.split())
    matches: dict[UUID, tuple[Decimal, str]] = {}
    by_name = {hint.name: hint for hint in active.values()}
    for hint in active.values():
        name_tokens = frozenset(normalize_counterparty_key(hint.name).split())
        if name_tokens and name_tokens <= tokens:
            matches[hint.id] = (CATEGORY_NAME_CONFIDENCE, "category_name")
    for category_name, keywords in _KEYWORD_RULES.items():
        named = by_name.get(category_name)
        if named is None or named.id in matches:
            continue
        if tokens & keywords:
            matches[named.id] = (KEYWORD_CONFIDENCE, "keyword_rule")

    if len(matches) == 1:
        category_id, (confidence, source) = next(iter(matches.items()))
        hint = active[category_id]
        return CategorizerProposal(hint.id, hint.name, confidence, source, key)
    if len(matches) > 1:
        return CategorizerProposal(None, None, ABSTAIN_CONFIDENCE, "ambiguous", key)
    return CategorizerProposal(None, None, ABSTAIN_CONFIDENCE, "unknown", key)


def enqueue_transaction_categorization(queue: JobEnqueuer, transaction_id: UUID) -> None:
    queue.enqueue(
        CATEGORIZE_TRANSACTION_JOB,
        {"transaction_id": str(transaction_id)},
        dedupe_key=str(transaction_id),
    )


def remember_owner_mapping(
    session: Session,
    *,
    counterparty: str,
    category_id: UUID,
    actor_id: UUID,
) -> None:
    key = normalize_counterparty_key(counterparty)
    if not key:
        return
    now = datetime.now(UTC)
    session.execute(
        insert(CounterpartyCategoryMap)
        .values(
            id=uuid7(),
            normalized_key=key,
            category_id=category_id,
            source=_OWNER_SOURCE,
            actor_id=actor_id,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=(CounterpartyCategoryMap.normalized_key,),
            set_={
                "category_id": category_id,
                "source": _OWNER_SOURCE,
                "actor_id": actor_id,
                "updated_at": now,
            },
        )
    )


class AutoCategorizer:
    """Assign high-confidence Categories through the owner categorization path."""

    def __init__(
        self,
        database: Database,
        *,
        min_confidence: Decimal = DEFAULT_MIN_CONFIDENCE,
        enabled: bool = True,
    ) -> None:
        self._database = database
        self._min_confidence = min_confidence
        self._enabled = enabled
        self._actions = OwnerTransactionActions(database)
        self._history = FinancialHistory(database)

    def propose_for_counterparty(self, counterparty: str) -> CategorizerProposal:
        with self._database.transaction() as session:
            return self.propose_in_session(session, counterparty)

    def propose_in_session(self, session: Session, counterparty: str) -> CategorizerProposal:
        return propose(
            counterparty=counterparty,
            categories=self._active_categories(session),
            learned=self._learned_map(session),
        )

    def projected_split(
        self,
        session: Session,
        *,
        kind: TransactionKind,
        counterparty: str,
        amount: Money,
    ) -> tuple[CategorySplitRecord, ...]:
        spending = kind in {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}
        if not self._enabled or not spending:
            return ()
        proposal = self.propose_in_session(session, counterparty)
        if not self._should_assign(proposal) or proposal.category_id is None:
            return ()
        if proposal.category_name is None or amount.amount == 0:
            return ()
        return (
            CategorySplitRecord(
                category_id=proposal.category_id,
                category_name=proposal.category_name,
                amount=Money(abs(amount.amount), amount.currency),
            ),
        )

    def categorize_transaction(self, transaction_id: UUID) -> TransactionSnapshot | None:
        try:
            with self._database.transaction() as session:
                snapshot = self._history.current_in_session(session, transaction_id)
                return self._categorize_snapshot_in_session(session, snapshot)
        except FinancialHistoryError as error:
            raise CategorizerError(str(error)) from error

    def _categorize_snapshot_in_session(
        self,
        session: Session,
        snapshot: TransactionSnapshot,
    ) -> TransactionSnapshot | None:
        if not self._enabled:
            return None
        if snapshot.kind not in {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}:
            return None
        if not self._needs_category(snapshot):
            return None
        proposal = self.propose_in_session(session, snapshot.counterparty)
        if not self._should_assign(proposal) or proposal.category_id is None:
            self._record_abstention(session, snapshot.id, proposal)
            return None
        try:
            return self._actions.categorize_in_session(
                session,
                OwnerCategorizationCommand(
                    transaction_id=snapshot.id,
                    expected_version=snapshot.version,
                    category_id=proposal.category_id,
                    actor_id=self._system_actor_id(session),
                    reason="auto_categorization",
                    learn=False,
                ),
            )
        except OwnerTransactionActionError as error:
            raise CategorizerError(str(error)) from error

    def _should_assign(self, proposal: CategorizerProposal) -> bool:
        return proposal.assigns and proposal.confidence >= self._min_confidence

    def _record_abstention(
        self,
        session: Session,
        transaction_id: UUID,
        proposal: CategorizerProposal,
    ) -> None:
        ReviewInbox.synchronize_in_session(
            session,
            ReviewCondition(
                subject_type="transaction",
                subject_id=transaction_id,
                condition_code="categorization_needed",
                severity=ReviewSeverity.ATTENTION,
                allowed_decisions=("categorize",),
                context={
                    "confidence": format(proposal.confidence, "f"),
                    "source": proposal.source,
                    "normalized_key": proposal.normalized_key,
                },
            ),
            active=True,
        )

    @staticmethod
    def _needs_category(snapshot: TransactionSnapshot) -> bool:
        if not snapshot.category_splits:
            return True
        return any(split.category_name == _UNCATEGORIZED for split in snapshot.category_splits)

    @staticmethod
    def _active_categories(session: Session) -> tuple[CategoryHint, ...]:
        categories = session.scalars(
            select(Category).where(
                Category.active.is_(True),
                or_(Category.parent_id.is_not(None), Category.name != _UNCATEGORIZED),
            )
        ).all()
        return tuple(CategoryHint(id=category.id, name=category.name) for category in categories)

    @staticmethod
    def _learned_map(session: Session) -> dict[str, UUID]:
        rows = session.execute(
            select(CounterpartyCategoryMap.normalized_key, CounterpartyCategoryMap.category_id)
        ).all()
        learned: dict[str, UUID] = {}
        for key, category_id in rows:
            learned[key] = category_id
        return learned

    @staticmethod
    def _system_actor_id(session: Session) -> UUID:
        inserted = session.execute(
            insert(AuditActor)
            .values(
                id=uuid7(),
                kind=AuditActorKind.SYSTEM.value,
                label="categorizer",
                external_key="categorizer",
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
                AuditActor.external_key == "categorizer",
            )
        )
        if actor_id is None:
            raise CategorizerError("categorizer audit actor disappeared")
        return actor_id
