"""Roll Category Split spend up to a two-level Category hierarchy."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, cast, func, or_, select

from billzebub.money import Money
from billzebub.persistence.models import (
    Category,
    CategorySplit,
    Claim,
    ClaimCategory,
    ClaimDispositionEvent,
    FinancialTransaction,
    TransactionClaim,
    TransactionVersion,
)

if TYPE_CHECKING:
    from billzebub.persistence.database import Database

_SPENDING_KINDS = ("expense", "cash_withdrawal")
_PROVISIONAL_DISPOSITIONS = ("provisional", "unconfirmed")


class CategorySpendError(ValueError):
    """A Category spend request is outside the reporting window."""


@dataclass(frozen=True, slots=True)
class SpendCategory:
    id: UUID
    name: str
    parent_id: UUID | None


@dataclass(frozen=True, slots=True)
class SpendAmount:
    category_id: UUID
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class CategorySpendNode:
    id: UUID
    name: str
    parent_id: UUID | None
    direct: Money
    total: Money
    children: tuple[CategorySpendNode, ...] = ()


@dataclass(frozen=True, slots=True)
class CategorySpendReport:
    month: str
    items: tuple[CategorySpendNode, ...]


class CategorySpend:
    """Sum current spending Category Splits and categorized provisional Claims."""

    def __init__(self, database: Database, *, reporting_timezone: str = "Asia/Singapore") -> None:
        self._database = database
        self._timezone = reporting_timezone
        ZoneInfo(reporting_timezone)

    def for_month(self, month: str) -> CategorySpendReport:
        start, end = month_bounds(month)
        with self._database.transaction() as session:
            categories = tuple(
                SpendCategory(id=category.id, name=category.name, parent_id=category.parent_id)
                for category in session.scalars(select(Category))
            )
            amounts = [
                SpendAmount(
                    category_id=category_id,
                    amount=amount,
                    currency=currency,
                )
                for category_id, amount, currency in session.execute(
                    select(
                        CategorySplit.category_id,
                        CategorySplit.amount,
                        CategorySplit.currency,
                    )
                    .join(
                        TransactionVersion,
                        TransactionVersion.id == CategorySplit.transaction_version_id,
                    )
                    .join(
                        FinancialTransaction,
                        and_(
                            FinancialTransaction.id == TransactionVersion.transaction_id,
                            FinancialTransaction.current_version == TransactionVersion.version,
                        ),
                    )
                    .where(
                        TransactionVersion.kind.in_(_SPENDING_KINDS),
                        TransactionVersion.effective_date >= start,
                        TransactionVersion.effective_date < end,
                    )
                )
            ]
            occurrence_date = cast(func.timezone(self._timezone, Claim.occurrence_at), Date)
            latest_disposition = (
                select(
                    ClaimDispositionEvent.claim_id.label("claim_id"),
                    ClaimDispositionEvent.disposition.label("disposition"),
                )
                .distinct(ClaimDispositionEvent.claim_id)
                .order_by(
                    ClaimDispositionEvent.claim_id,
                    ClaimDispositionEvent.occurred_at.desc(),
                    ClaimDispositionEvent.id.desc(),
                )
                .subquery()
            )
            amounts.extend(
                SpendAmount(
                    category_id=category_id,
                    amount=amount,
                    currency=currency,
                )
                for category_id, amount, currency in session.execute(
                    select(
                        ClaimCategory.category_id,
                        ClaimCategory.amount,
                        ClaimCategory.currency,
                    )
                    .join(Claim, Claim.id == ClaimCategory.claim_id)
                    .join(latest_disposition, latest_disposition.c.claim_id == Claim.id)
                    .where(
                        Claim.claim_type == "real_time",
                        latest_disposition.c.disposition.in_(_PROVISIONAL_DISPOSITIONS),
                        ~Claim.id.in_(select(TransactionClaim.claim_id)),
                        or_(
                            Claim.transaction_kind_hint.is_(None),
                            Claim.transaction_kind_hint.in_(_SPENDING_KINDS),
                        ),
                        occurrence_date >= start,
                        occurrence_date < end,
                    )
                )
            )
        return assemble_category_spend(categories, amounts, month=month)


def month_bounds(month: str) -> tuple[date, date]:
    """Return the half-open reporting-month window for ``YYYY-MM``."""
    if len(month) != 7 or month[4] != "-":
        raise CategorySpendError("month must be YYYY-MM")
    try:
        year = int(month[:4])
        month_number = int(month[5:])
    except ValueError as error:
        raise CategorySpendError("month must be YYYY-MM") from error
    if not 1 <= month_number <= 12:
        raise CategorySpendError("month must be YYYY-MM")
    start = date(year, month_number, 1)
    if month_number == 12:
        return start, date(year + 1, 1, 1)
    return start, date(year, month_number + 1, 1)


def assemble_category_spend(
    categories: Sequence[SpendCategory],
    amounts: Sequence[SpendAmount],
    *,
    month: str,
) -> CategorySpendReport:
    """Parent total is its direct splits plus the sum of its children.

    A child total is that child's own splits. Amounts deeper than two levels
    fold into the intermediate child so they still roll up to the root.
    """
    by_id = {category.id: category for category in categories}
    direct: dict[tuple[UUID, UUID | None, str], Decimal] = defaultdict(lambda: Decimal(0))
    for amount in amounts:
        if amount.amount <= 0:
            continue
        bucket = _bucket(amount.category_id, by_id)
        if bucket is None:
            continue
        root_id, child_id = bucket
        currency = amount.currency.upper()
        direct[(root_id, child_id, currency)] += amount.amount

    currencies_for_root: dict[UUID, set[str]] = defaultdict(set)
    for root_id, _child_id, currency in direct:
        currencies_for_root[root_id].add(currency)

    items: list[CategorySpendNode] = []
    for root_id, currencies in currencies_for_root.items():
        root = by_id[root_id]
        for currency in currencies:
            own = direct.get((root_id, None, currency), Decimal(0))
            children: list[CategorySpendNode] = []
            child_ids = {
                child_id
                for (candidate_root, child_id, candidate_currency) in direct
                if candidate_root == root_id
                and candidate_currency == currency
                and child_id is not None
            }
            for child_id in child_ids:
                child = by_id[child_id]
                child_amount = direct[(root_id, child_id, currency)]
                if child_amount == 0:
                    continue
                money = Money(child_amount, currency)
                children.append(
                    CategorySpendNode(
                        id=child.id,
                        name=child.name,
                        parent_id=root.id,
                        direct=money,
                        total=money,
                    )
                )
            children.sort(key=lambda node: (-node.total.amount, node.name, str(node.id)))
            child_sum = sum((node.total.amount for node in children), start=Decimal(0))
            total_amount = own + child_sum
            if total_amount == 0:
                continue
            items.append(
                CategorySpendNode(
                    id=root.id,
                    name=root.name,
                    parent_id=None,
                    direct=Money(own, currency),
                    total=Money(total_amount, currency),
                    children=tuple(children),
                )
            )
    items.sort(key=lambda node: (-node.total.amount, node.total.currency, node.name, str(node.id)))
    return CategorySpendReport(month=month, items=tuple(items))


def _bucket(
    category_id: UUID,
    by_id: dict[UUID, SpendCategory],
) -> tuple[UUID, UUID | None] | None:
    category = by_id.get(category_id)
    if category is None:
        return None
    if category.parent_id is None:
        return category.id, None
    parent = by_id.get(category.parent_id)
    if parent is None:
        return None
    if parent.parent_id is None:
        return parent.id, category.id
    if parent.parent_id not in by_id:
        return None
    return parent.parent_id, parent.id
