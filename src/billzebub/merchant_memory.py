"""Unambiguous merchant Category memory consulted before Jev.

A normalized counterparty maps to one Category only when the evidence agrees.
Owner categorizations win over Jev applies at confidence 0.9 or higher. More
than one owner Category, or more than one Jev Category with no owner decision,
leaves no row so the worker still calls Jev.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.persistence.models import (
    AuditActor,
    AuditActorKind,
    Category,
    CategorySplit,
    Claim,
    ClaimCategory,
    CorrectionEvent,
    FinancialTransaction,
    JevCategorizationAttempt,
    MerchantCategoryMemory,
    MerchantMemoryExclusion,
    TransactionClaim,
    TransactionVersion,
)
from billzebub.recurrings import normalize_counterparty

if TYPE_CHECKING:
    from billzebub.persistence.database import Database

MEMORY_REASON = "merchant_memory"
UNDO_REASON = "undo_merchant_apply"
SOURCE_OWNER = "owner"
SOURCE_JEV = "jev"
JEV_MEMORY_MIN_CONFIDENCE = Decimal("0.9")
_UNCATEGORIZED = "Uncategorized"
_SPENDING_KINDS = ("expense", "cash_withdrawal")


class MerchantMemoryError(ValueError):
    """Merchant memory could not be read or written."""


@dataclass(frozen=True, slots=True)
class MemoryRule:
    normalized_key: str
    category_id: UUID
    category_name: str
    source: str


@dataclass(frozen=True, slots=True)
class MemoryBackfillReport:
    rules_before: int
    would_write: int
    would_clear: int
    rules_after: int
    written: int
    cleared: int
    applied: bool


def resolve_memory(
    owner_category_ids: set[UUID],
    jev_category_ids: set[UUID],
) -> tuple[UUID, str] | None:
    """Pick one Category, or nothing when the merchant is ambiguous.

    A single owner Category wins even when Jev seeds disagree. Several owner
    Categories, or several Jev Categories with no owner decision, fall through.
    """
    if len(owner_category_ids) == 1:
        return next(iter(owner_category_ids)), SOURCE_OWNER
    if owner_category_ids:
        return None
    if len(jev_category_ids) == 1:
        return next(iter(jev_category_ids)), SOURCE_JEV
    return None


def format_memory_backfill(report: MemoryBackfillReport) -> str:
    lines = [f"before rules={report.rules_before}"]
    if report.applied:
        lines.append(
            f"after rules={report.rules_after} written={report.written} cleared={report.cleared}"
        )
    else:
        lines.append(f"would_write={report.would_write} would_clear={report.would_clear}")
        lines.append(f"after rules={report.rules_after}")
    return "\n".join(lines)


def refresh_merchant_memory(session: Session, counterparty: str) -> MemoryRule | None:
    """Recompute the rule for one counterparty from current owner and Jev evidence."""
    key = normalize_counterparty(counterparty)
    return refresh_normalized_key(session, key)


def forget_normalized_key(session: Session, normalized_key: str) -> bool:
    """Drop a future rule without recomputing it from historical evidence."""
    key = normalized_key.strip()
    if not key:
        return False
    existing = session.scalar(
        select(MerchantCategoryMemory).where(MerchantCategoryMemory.normalized_key == key)
    )
    if existing is None:
        return False
    session.delete(existing)
    session.flush()
    return True


def refresh_normalized_key(session: Session, normalized_key: str) -> MemoryRule | None:
    key = normalized_key.strip()
    if not key:
        return None
    desired = _desired_for_keys(session, frozenset({key})).get(key)
    _replace_rule(session, key, desired)
    if desired is None:
        return None
    category = session.get(Category, desired[0])
    if category is None:
        return None
    return MemoryRule(
        normalized_key=key,
        category_id=category.id,
        category_name=category.name,
        source=desired[1],
    )


def rule_for_counterparty(session: Session, counterparty: str) -> MemoryRule | None:
    key = normalize_counterparty(counterparty)
    if not key:
        return None
    row = session.scalar(
        select(MerchantCategoryMemory).where(MerchantCategoryMemory.normalized_key == key)
    )
    if row is None:
        return None
    category = session.get(Category, row.category_id)
    if (
        category is None
        or not category.active
        or (category.parent_id is None and category.name == _UNCATEGORIZED)
    ):
        return None
    return MemoryRule(
        normalized_key=row.normalized_key,
        category_id=category.id,
        category_name=category.name,
        source=row.source,
    )


def list_memory_rules(session: Session) -> tuple[MemoryRule, ...]:
    rows = session.execute(
        select(MerchantCategoryMemory, Category)
        .join(Category, Category.id == MerchantCategoryMemory.category_id)
        .order_by(MerchantCategoryMemory.normalized_key, MerchantCategoryMemory.id)
    ).all()
    return tuple(
        MemoryRule(
            normalized_key=memory.normalized_key,
            category_id=category.id,
            category_name=category.name,
            source=memory.source,
        )
        for memory, category in rows
        if category.active and not (category.parent_id is None and category.name == _UNCATEGORIZED)
    )


def is_memory_excluded(session: Session, transaction_id: UUID) -> bool:
    found = session.scalar(
        select(MerchantMemoryExclusion.transaction_id).where(
            MerchantMemoryExclusion.transaction_id == transaction_id
        )
    )
    return found is not None


def remember_exclusion(session: Session, transaction_id: UUID, normalized_key: str) -> None:
    key = normalized_key.strip()
    if not key:
        return
    session.execute(
        insert(MerchantMemoryExclusion)
        .values(
            transaction_id=transaction_id,
            normalized_key=key,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_update(
            index_elements=(MerchantMemoryExclusion.transaction_id,),
            set_={"normalized_key": key},
        )
    )


def clear_exclusion(session: Session, transaction_id: UUID) -> None:
    session.execute(
        delete(MerchantMemoryExclusion).where(
            MerchantMemoryExclusion.transaction_id == transaction_id
        )
    )


def clear_exclusions(session: Session, transaction_ids: set[UUID]) -> None:
    if not transaction_ids:
        return
    session.execute(
        delete(MerchantMemoryExclusion).where(
            MerchantMemoryExclusion.transaction_id.in_(transaction_ids)
        )
    )


def backfill_merchant_memory(database: Database, *, apply: bool) -> MemoryBackfillReport:
    """Rebuild every merchant rule. Dry-run is the default and writes nothing."""
    with database.transaction() as session:
        before_rows = list_memory_rules(session)
        desired = _desired_for_keys(session, None)
        current = {rule.normalized_key: (rule.category_id, rule.source) for rule in before_rows}
        keys = set(desired) | set(current)
        would_write = 0
        would_clear = 0
        for key in keys:
            if desired.get(key) == current.get(key):
                continue
            if key in desired:
                would_write += 1
            else:
                would_clear += 1
        written = 0
        cleared = 0
        if apply:
            for key in sorted(keys):
                if desired.get(key) == current.get(key):
                    continue
                _replace_rule(session, key, desired.get(key))
                if key in desired:
                    written += 1
                else:
                    cleared += 1
            after = len(list_memory_rules(session))
        else:
            after = len(before_rows)
        return MemoryBackfillReport(
            rules_before=len(before_rows),
            would_write=would_write,
            would_clear=would_clear,
            rules_after=after,
            written=written,
            cleared=cleared,
            applied=apply,
        )


def _replace_rule(
    session: Session,
    key: str,
    desired: tuple[UUID, str] | None,
) -> None:
    existing = session.scalar(
        select(MerchantCategoryMemory).where(MerchantCategoryMemory.normalized_key == key)
    )
    if desired is None:
        if existing is not None:
            session.delete(existing)
            session.flush()
        return
    category_id, source = desired
    now = datetime.now(UTC)
    if existing is None:
        session.add(
            MerchantCategoryMemory(
                id=uuid7(),
                normalized_key=key,
                category_id=category_id,
                source=source,
                created_at=now,
                updated_at=now,
            )
        )
    else:
        existing.category_id = category_id
        existing.source = source
        existing.updated_at = now
    session.flush()


def _desired_for_keys(
    session: Session,
    only: frozenset[str] | None,
) -> dict[str, tuple[UUID, str]]:
    owner: dict[str, set[UUID]] = defaultdict(set)
    jev: dict[str, set[UUID]] = defaultdict(set)
    for key, category_id, source in _evidence(session):
        if only is not None and key not in only:
            continue
        if source == SOURCE_OWNER:
            owner[key].add(category_id)
        elif source == SOURCE_JEV:
            jev[key].add(category_id)
    keys = set(owner) | set(jev)
    if only is not None:
        keys |= set(only)
    desired: dict[str, tuple[UUID, str]] = {}
    for key in keys:
        if not key:
            continue
        resolved = resolve_memory(owner.get(key, set()), jev.get(key, set()))
        if resolved is None:
            continue
        category_id, source = resolved
        category = session.get(Category, category_id)
        if (
            category is None
            or not category.active
            or (category.parent_id is None and category.name == _UNCATEGORIZED)
        ):
            continue
        desired[key] = (category.id, source)
    if only is not None:
        return {key: value for key, value in desired.items() if key in only}
    return desired


def _evidence(session: Session) -> list[tuple[str, UUID, str]]:
    found: list[tuple[str, UUID, str]] = []
    for transaction_id, counterparty, category_id in _current_spending(session):
        key = normalize_counterparty(counterparty)
        if not key or category_id is None:
            continue
        source = _transaction_source(session, transaction_id, category_id)
        if source is None:
            continue
        found.append((key, category_id, source))
    for counterparty, category_id in _claim_only_jev(session):
        key = normalize_counterparty(counterparty)
        if not key:
            continue
        found.append((key, category_id, SOURCE_JEV))
    return found


def _current_spending(session: Session) -> list[tuple[UUID, str, UUID | None]]:
    rows = session.execute(
        select(
            FinancialTransaction.id,
            TransactionVersion.counterparty,
            Category.id,
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
    ).all()
    grouped: dict[UUID, list[tuple[str, UUID, str, UUID | None]]] = defaultdict(list)
    for transaction_id, counterparty, category_id, name, parent_id in rows:
        grouped[transaction_id].append((counterparty, category_id, name, parent_id))
    loaded: list[tuple[UUID, str, UUID | None]] = []
    for transaction_id, splits in grouped.items():
        usable = [
            (counterparty, category_id)
            for counterparty, category_id, name, parent_id in splits
            if not (parent_id is None and name == _UNCATEGORIZED)
        ]
        if len(usable) != 1:
            continue
        counterparty, category_id = usable[0]
        loaded.append((transaction_id, counterparty, category_id))
    return loaded


def _transaction_source(session: Session, transaction_id: UUID, category_id: UUID) -> str | None:
    events = session.scalars(
        select(CorrectionEvent)
        .where(CorrectionEvent.transaction_id == transaction_id)
        .order_by(CorrectionEvent.created_at.desc(), CorrectionEvent.id.desc())
    ).all()
    for event in events:
        replacement = _primary_category(session, event.replacement_version_id)
        if replacement != category_id:
            continue
        prior = _primary_category(session, event.prior_version_id)
        if prior == category_id:
            continue
        return _event_source(session, event, category_id)
    return _confirmed_claim_source(session, transaction_id, category_id)


def _event_source(session: Session, event: CorrectionEvent, category_id: UUID) -> str | None:
    if event.reason in {MEMORY_REASON, UNDO_REASON}:
        return None
    actor = session.get(AuditActor, event.actor_id) if event.actor_id is not None else None
    if actor is not None and _is_owner(actor):
        return SOURCE_OWNER
    if event.reason == "jev_categorization" and _jev_applied(
        session,
        category_id=category_id,
        transaction_id=event.transaction_id,
    ):
        return SOURCE_JEV
    return None


def _is_owner(actor: AuditActor) -> bool:
    return actor.kind == AuditActorKind.OWNER


def _confirmed_claim_source(
    session: Session,
    transaction_id: UUID,
    category_id: UUID,
) -> str | None:
    claim_id = session.scalar(
        select(TransactionClaim.claim_id).where(
            TransactionClaim.transaction_id == transaction_id,
            TransactionClaim.role == "real_time",
        )
    )
    if claim_id is None:
        return None
    stored = session.scalar(
        select(ClaimCategory.category_id).where(ClaimCategory.claim_id == claim_id)
    )
    if stored != category_id:
        return None
    if _jev_applied(session, category_id=category_id, claim_id=claim_id):
        return SOURCE_JEV
    return None


def _claim_only_jev(session: Session) -> list[tuple[str, UUID]]:
    rows = session.execute(
        select(Claim.raw_description, ClaimCategory.category_id, Claim.id)
        .join(ClaimCategory, ClaimCategory.claim_id == Claim.id)
        .where(~Claim.id.in_(select(TransactionClaim.claim_id)))
    ).all()
    found: list[tuple[str, UUID]] = []
    for raw_description, category_id, claim_id in rows:
        if not _jev_applied(session, category_id=category_id, claim_id=claim_id):
            continue
        counterparty = " ".join(raw_description.split())[:300]
        if counterparty:
            found.append((counterparty, category_id))
    return found


def _jev_applied(
    session: Session,
    *,
    category_id: UUID,
    transaction_id: UUID | None = None,
    claim_id: UUID | None = None,
) -> bool:
    query = select(JevCategorizationAttempt.id).where(
        JevCategorizationAttempt.action == "apply",
        JevCategorizationAttempt.category_id == category_id,
        JevCategorizationAttempt.choice_confidence >= JEV_MEMORY_MIN_CONFIDENCE,
    )
    if transaction_id is not None:
        query = query.where(JevCategorizationAttempt.transaction_id == transaction_id)
    elif claim_id is not None:
        query = query.where(JevCategorizationAttempt.claim_id == claim_id)
    else:
        return False
    return session.scalar(query.limit(1)) is not None


def _primary_category(session: Session, version_id: UUID) -> UUID | None:
    rows = session.execute(
        select(Category.id, Category.name, Category.parent_id)
        .join(CategorySplit, CategorySplit.category_id == Category.id)
        .where(CategorySplit.transaction_version_id == version_id)
    ).all()
    usable = [
        category_id
        for category_id, name, parent_id in rows
        if not (parent_id is None and name == _UNCATEGORIZED)
    ]
    if len(usable) != 1:
        return None
    category_id = usable[0]
    if not isinstance(category_id, UUID):
        return None
    return category_id
