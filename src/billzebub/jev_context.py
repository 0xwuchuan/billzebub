"""Similar confirmed Transactions attached to Jev state.

The list follows the TypeSafe basic_memory shape: one named list on the state
object, agent-safe fields only, no Transaction ids.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from billzebub.jev import JevSubject, SimilarConfirmed
from billzebub.persistence.models import (
    Category,
    CategorySplit,
    FinancialTransaction,
    TransactionVersion,
)
from billzebub.recurrings import normalize_counterparty

SIMILAR_LIMIT = 8
_UNCATEGORIZED = "Uncategorized"
_SPENDING_KINDS = ("expense", "cash_withdrawal")


@dataclass(frozen=True, slots=True)
class _Candidate:
    counterparty: str
    normalized_counterparty: str
    amount: str
    currency: str
    kind: str
    category: str
    effective_date: str


def similar_confirmed(
    session: Session,
    subject: JevSubject,
    *,
    exclude_transaction_id: UUID | None = None,
    limit: int = SIMILAR_LIMIT,
) -> tuple[SimilarConfirmed, ...]:
    """Top confirmed spends, same merchant first, then kind and amount."""
    bounded = max(0, min(limit, 10))
    if bounded == 0:
        return ()
    candidates = _candidates(session, exclude_transaction_id)
    subject_key = normalize_counterparty(subject.counterparty)
    ranked = sorted(
        candidates,
        key=lambda candidate: _rank(candidate, subject, subject_key),
        reverse=True,
    )
    return tuple(
        SimilarConfirmed(
            counterparty=candidate.counterparty,
            normalized_counterparty=candidate.normalized_counterparty,
            amount=candidate.amount,
            currency=candidate.currency,
            kind=candidate.kind,
            category=candidate.category,
        )
        for candidate in ranked[:bounded]
    )


def similarity_rank(
    *,
    subject_key: str,
    subject_kind: str,
    subject_amount: str,
    candidate_key: str,
    candidate_kind: str,
    candidate_amount: str,
) -> tuple[int, float, int, Decimal]:
    """Sort key. Higher is closer. Same normalized merchant outranks the rest."""
    same_merchant = int(bool(subject_key) and candidate_key == subject_key)
    overlap = _jaccard(subject_key, candidate_key)
    same_kind = int(candidate_kind == subject_kind)
    return (same_merchant, overlap, same_kind, -_amount_gap(subject_amount, candidate_amount))


def _rank(
    candidate: _Candidate,
    subject: JevSubject,
    subject_key: str,
) -> tuple[int, float, int, Decimal, str]:
    score = similarity_rank(
        subject_key=subject_key,
        subject_kind=subject.kind,
        subject_amount=subject.amount,
        candidate_key=candidate.normalized_counterparty,
        candidate_kind=candidate.kind,
        candidate_amount=candidate.amount,
    )
    return (*score, candidate.effective_date)


def _candidates(session: Session, exclude_transaction_id: UUID | None) -> list[_Candidate]:
    query = (
        select(
            FinancialTransaction.id,
            TransactionVersion.counterparty,
            TransactionVersion.posted_amount,
            TransactionVersion.posted_currency,
            TransactionVersion.kind,
            TransactionVersion.effective_date,
            Category.name,
            Category.parent_id,
        )
        .join(
            TransactionVersion,
            (TransactionVersion.transaction_id == FinancialTransaction.id)
            & (TransactionVersion.version == FinancialTransaction.current_version),
        )
        .join(CategorySplit, CategorySplit.transaction_version_id == TransactionVersion.id)
        .join(Category, Category.id == CategorySplit.category_id)
        .where(TransactionVersion.kind.in_(_SPENDING_KINDS))
    )
    if exclude_transaction_id is not None:
        query = query.where(FinancialTransaction.id != exclude_transaction_id)
    rows = session.execute(query).all()
    parent_ids = {parent_id for *_rest, parent_id in rows if parent_id is not None}
    parents = _parent_names(session, parent_ids)
    grouped: dict[UUID, list[tuple[str, Decimal, str, str, date, str, UUID | None]]] = defaultdict(
        list
    )
    for (
        transaction_id,
        counterparty,
        posted_amount,
        posted_currency,
        kind,
        effective_date,
        name,
        parent_id,
    ) in rows:
        grouped[transaction_id].append(
            (counterparty, posted_amount, posted_currency, kind, effective_date, name, parent_id)
        )
    loaded: list[_Candidate] = []
    for splits in grouped.values():
        usable = [
            split for split in splits if not (split[6] is None and split[5] == _UNCATEGORIZED)
        ]
        names = {split[5] for split in usable}
        if len(names) != 1:
            continue
        (
            counterparty,
            posted_amount,
            posted_currency,
            kind,
            effective_date,
            name,
            parent_id,
        ) = usable[0]
        parent = parents.get(parent_id) if parent_id is not None else None
        category = f"{parent} > {name}" if parent else name
        loaded.append(
            _Candidate(
                counterparty=counterparty,
                normalized_counterparty=normalize_counterparty(counterparty),
                amount=format(posted_amount, "f"),
                currency=posted_currency,
                kind=kind,
                category=category,
                effective_date=effective_date.isoformat(),
            )
        )
    return loaded


def _parent_names(session: Session, parent_ids: set[UUID]) -> dict[UUID, str]:
    if not parent_ids:
        return {}
    rows = session.execute(
        select(Category.id, Category.name).where(Category.id.in_(parent_ids))
    ).all()
    names: dict[UUID, str] = {}
    for category_id, name in rows:
        names[category_id] = name
    return names


def _jaccard(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _amount_gap(left: str, right: str) -> Decimal:
    try:
        return abs(abs(Decimal(left)) - abs(Decimal(right)))
    except (InvalidOperation, ValueError):
        return Decimal("999999999")
