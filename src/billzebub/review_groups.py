"""Pending categorization Reviews grouped by normalized merchant."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from billzebub.financial_history import (
    CategoryAllocation,
    Correction,
    FinancialHistory,
    FinancialHistoryError,
    TransactionKind,
)
from billzebub.merchant_memory import (
    MemoryRule,
    clear_exclusions,
    list_memory_rules,
    refresh_normalized_key,
    remember_exclusion,
)
from billzebub.money import Money
from billzebub.owner_transaction_actions import (
    OwnerCategorizationCommand,
    OwnerTransactionActionError,
    OwnerTransactionActions,
)
from billzebub.persistence.models import Category, PendingReview
from billzebub.recurrings import normalize_counterparty
from billzebub.reviews import PendingReviewStatus

if TYPE_CHECKING:
    from billzebub.persistence.database import Database

_SPENDING_KINDS = frozenset({TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL})


class ReviewGroupError(ValueError):
    """A merchant-group read or mutation was rejected."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class GroupMember:
    transaction_id: UUID
    review_id: UUID
    version: int
    counterparty: str
    amount: str
    currency: str
    effective_date: str
    kind: str


@dataclass(frozen=True, slots=True)
class MerchantGroup:
    normalized_key: str
    label: str
    etag: str
    members: tuple[GroupMember, ...]

    @property
    def count(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class AppliedMerchantGroup:
    normalized_key: str
    label: str
    category_id: UUID
    applied: tuple[tuple[UUID, int], ...]
    excluded_transaction_ids: tuple[UUID, ...]
    memory: MemoryRule | None
    undo_etag: str


@dataclass(frozen=True, slots=True)
class UndoneMerchantGroup:
    normalized_key: str
    restored_transaction_ids: tuple[UUID, ...]
    memory: MemoryRule | None


class MerchantReviewGroups:
    """Group pending categorization Reviews and apply one owner Category to them."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._history = FinancialHistory(database)
        self._actions = OwnerTransactionActions(database)

    def list_groups(self) -> tuple[MerchantGroup, ...]:
        with self._database.transaction() as session:
            return self._list_groups(session)

    def list_rules(self) -> tuple[MemoryRule, ...]:
        with self._database.transaction() as session:
            return list_memory_rules(session)

    def apply(
        self,
        *,
        normalized_key: str,
        category_id: UUID,
        exclude_transaction_ids: tuple[UUID, ...],
        actor_id: UUID,
        if_match: str,
    ) -> AppliedMerchantGroup:
        key = normalized_key.strip()
        with self._database.transaction() as session:
            group = self._group(session, key)
            if group is None:
                raise ReviewGroupError("merchant group was not found", code="missing")
            if if_match != group.etag:
                raise ReviewGroupError("merchant group is stale", code="stale")
            category = session.get(Category, category_id)
            if (
                category is None
                or not category.active
                or (category.parent_id is None and category.name == "Uncategorized")
            ):
                raise ReviewGroupError("Category is not available", code="invalid")
            member_ids = {member.transaction_id for member in group.members}
            excluded = tuple(dict.fromkeys(exclude_transaction_ids))
            unknown = [
                transaction_id for transaction_id in excluded if transaction_id not in member_ids
            ]
            if unknown:
                raise ReviewGroupError(
                    "excluded transaction is not in the merchant group",
                    code="invalid",
                )
            included = [
                member for member in group.members if member.transaction_id not in set(excluded)
            ]
            if not included:
                raise ReviewGroupError("apply requires at least one transaction", code="invalid")
            applied: list[tuple[UUID, int]] = []
            try:
                for member in included:
                    updated = self._actions.categorize_in_session(
                        session,
                        OwnerCategorizationCommand(
                            transaction_id=member.transaction_id,
                            expected_version=member.version,
                            category_id=category.id,
                            actor_id=actor_id,
                            reason="owner_categorization",
                        ),
                    )
                    applied.append((updated.id, updated.version))
            except (OwnerTransactionActionError, FinancialHistoryError) as error:
                raise ReviewGroupError(str(error), code="invalid") from error
            for transaction_id in excluded:
                remember_exclusion(session, transaction_id, key)
            rule = refresh_normalized_key(session, key)
            return AppliedMerchantGroup(
                normalized_key=key,
                label=group.label,
                category_id=category.id,
                applied=tuple(applied),
                excluded_transaction_ids=excluded,
                memory=rule,
                undo_etag=group_etag(key, applied, prefix="merchant-undo"),
            )

    def undo(
        self,
        *,
        normalized_key: str,
        category_id: UUID,
        transactions: tuple[tuple[UUID, int], ...],
        excluded_transaction_ids: tuple[UUID, ...],
        actor_id: UUID,
        if_match: str,
    ) -> UndoneMerchantGroup:
        key = normalized_key.strip()
        pairs = tuple(transactions)
        expected = group_etag(key, pairs, prefix="merchant-undo")
        if if_match != expected:
            raise ReviewGroupError("merchant undo is stale", code="stale")
        with self._database.transaction() as session:
            uncategorized = session.scalar(
                select(Category).where(
                    Category.parent_id.is_(None),
                    Category.name == "Uncategorized",
                )
            )
            if uncategorized is None:
                raise ReviewGroupError("Uncategorized is missing", code="invalid")
            restored: list[UUID] = []
            try:
                for transaction_id, version in pairs:
                    snapshot = self._history.current_in_session(session, transaction_id)
                    if snapshot.version != version:
                        raise ReviewGroupError("merchant undo is stale", code="stale")
                    current_ids = {split.category_id for split in snapshot.category_splits}
                    if current_ids != {category_id}:
                        continue
                    amount = abs(snapshot.posted_amount.amount)
                    self._history.correct_in_session(
                        session,
                        Correction(
                            transaction_id=transaction_id,
                            reason="undo_merchant_apply",
                            category_splits=(
                                CategoryAllocation(
                                    category_id=uncategorized.id,
                                    amount=Money(amount, snapshot.posted_amount.currency),
                                ),
                            ),
                            actor_id=actor_id,
                        ),
                    )
                    restored.append(transaction_id)
            except FinancialHistoryError as error:
                raise ReviewGroupError(str(error), code="invalid") from error
            clear_exclusions(session, set(excluded_transaction_ids))
            rule = refresh_normalized_key(session, key)
            return UndoneMerchantGroup(
                normalized_key=key,
                restored_transaction_ids=tuple(restored),
                memory=rule,
            )

    def _list_groups(self, session: Session) -> tuple[MerchantGroup, ...]:
        grouped: dict[str, list[GroupMember]] = defaultdict(list)
        labels: dict[str, list[str]] = defaultdict(list)
        for review in self._pending_reviews(session):
            try:
                snapshot = self._history.current_in_session(session, review.subject_id)
            except FinancialHistoryError:
                continue
            if snapshot.kind not in _SPENDING_KINDS:
                continue
            key = normalize_counterparty(snapshot.counterparty)
            if not key:
                continue
            amount = snapshot.posted_amount
            grouped[key].append(
                GroupMember(
                    transaction_id=snapshot.id,
                    review_id=review.id,
                    version=snapshot.version,
                    counterparty=snapshot.counterparty,
                    amount=format(amount.amount, "f"),
                    currency=amount.currency,
                    effective_date=snapshot.effective_date.isoformat(),
                    kind=snapshot.kind.value,
                )
            )
            labels[key].append(snapshot.counterparty)
        groups = [
            MerchantGroup(
                normalized_key=key,
                label=_group_label(labels[key]),
                etag=group_etag(
                    key,
                    [(member.transaction_id, member.version) for member in members],
                ),
                members=tuple(
                    sorted(
                        members,
                        key=lambda member: (member.effective_date, str(member.transaction_id)),
                    )
                ),
            )
            for key, members in grouped.items()
            if members
        ]
        groups.sort(key=lambda group: (-group.count, group.label.casefold(), group.normalized_key))
        return tuple(groups)

    def _group(self, session: Session, normalized_key: str) -> MerchantGroup | None:
        if not normalized_key:
            return None
        for group in self._list_groups(session):
            if group.normalized_key == normalized_key:
                return group
        return None

    @staticmethod
    def _pending_reviews(session: Session) -> tuple[PendingReview, ...]:
        return tuple(
            session.scalars(
                select(PendingReview)
                .where(
                    PendingReview.subject_type == "transaction",
                    PendingReview.condition_code == "categorization_needed",
                    PendingReview.status == PendingReviewStatus.PENDING.value,
                )
                .order_by(PendingReview.created_at, PendingReview.id)
            ).all()
        )


def group_etag(
    normalized_key: str,
    pairs: list[tuple[UUID, int]] | tuple[tuple[UUID, int], ...],
    *,
    prefix: str = "merchant-group",
) -> str:
    ordered = sorted(pairs, key=lambda item: str(item[0]))
    body = "|".join(f"{transaction_id}:{version}" for transaction_id, version in ordered)
    digest = hashlib.sha256(f"{prefix}|{normalized_key}|{body}".encode()).hexdigest()[:16]
    return f'"{prefix}:{digest}"'


def _group_label(counterparties: list[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for counterparty in counterparties:
        counts[counterparty] += 1
    return sorted(counts, key=lambda label: (-counts[label], len(label), label.casefold()))[0]
