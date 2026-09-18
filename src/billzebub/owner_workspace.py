"""Owner-only read projections for the Transaction and Pending Review workspace."""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from billzebub.claims import ClaimDisposition, ClaimType
from billzebub.financial_history import CategorySplitRecord, TransactionKind
from billzebub.money import Money
from billzebub.persistence.models import (
    Category,
    CategorySplit,
    Claim,
    ClaimDispositionEvent,
    FinancialAccount,
    FinancialTransaction,
    PendingReview,
    TransactionClaim,
    TransactionVersion,
)
from billzebub.reviews import PendingReviewStatus, ReviewSeverity

if TYPE_CHECKING:
    from billzebub.persistence.database import Database

_ELIGIBLE_REAL_TIME_DISPOSITIONS = frozenset(
    {ClaimDisposition.PROVISIONAL.value, ClaimDisposition.UNCONFIRMED.value}
)


class OwnerWorkspaceError(ValueError):
    """An owner workspace resource was malformed or could not be found."""


@dataclass(frozen=True, slots=True)
class OwnerReviewSummary:
    id: UUID
    condition_code: str
    severity: ReviewSeverity
    version: int
    allowed_decisions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OwnerTransaction:
    id: UUID
    version: int
    financial_account_id: UUID
    financial_account_name: str
    counterparty: str
    posted_amount: Money
    authorized_amount: Money | None
    effective_date: str
    kind: TransactionKind
    category_splits: tuple[CategorySplitRecord, ...]
    reviews: tuple[OwnerReviewSummary, ...]


@dataclass(frozen=True, slots=True)
class OwnerTransactionPage:
    items: tuple[OwnerTransaction, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class OwnerReview:
    id: UUID
    subject_type: str
    subject_id: UUID
    condition_code: str
    severity: ReviewSeverity
    status: PendingReviewStatus
    version: int
    allowed_decisions: tuple[str, ...]
    context: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OwnerReviewPage:
    items: tuple[OwnerReview, ...]
    next_cursor: str | None


class OwnerWorkspace:
    """Own compact, current-state browser projections without exposing a table API."""

    def __init__(
        self,
        database: Database,
        *,
        reporting_timezone: str = "Asia/Singapore",
    ) -> None:
        self._database = database
        self._reporting_timezone = ZoneInfo(reporting_timezone)

    def list_transactions(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        financial_account_id: UUID | None = None,
        kind: TransactionKind | None = None,
        needs_review: bool | None = None,
    ) -> OwnerTransactionPage:
        if not 1 <= limit <= 100:
            raise OwnerWorkspaceError("Transaction page limit must be between 1 and 100")
        position = self._decode_transaction_cursor(cursor) if cursor is not None else None
        with self._database.transaction() as session:
            confirmed = self._confirmed_transactions(
                session,
                position=position,
                limit=limit + 1,
                financial_account_id=financial_account_id,
                kind=kind,
                needs_review=needs_review,
            )
            provisional = self._provisional_claims(
                session,
                position=position,
                limit=limit + 1,
                financial_account_id=financial_account_id,
                kind=kind,
                needs_review=needs_review,
            )
            combined = _sort_activity((*confirmed, *provisional))
            page_items = combined[:limit]
            next_cursor = None
            if len(combined) > limit and page_items:
                last = page_items[-1]
                next_cursor = self._encode_transaction_cursor(last.effective_date, last.id)
            return OwnerTransactionPage(items=page_items, next_cursor=next_cursor)

    def get_transaction(self, transaction_id: UUID) -> OwnerTransaction:
        with self._database.transaction() as session:
            row = session.execute(
                select(FinancialTransaction, TransactionVersion, FinancialAccount)
                .join(
                    TransactionVersion,
                    and_(
                        TransactionVersion.transaction_id == FinancialTransaction.id,
                        TransactionVersion.version == FinancialTransaction.current_version,
                    ),
                )
                .join(
                    FinancialAccount,
                    FinancialAccount.id == FinancialTransaction.financial_account_id,
                )
                .where(FinancialTransaction.id == transaction_id)
            ).one_or_none()
            if row is not None:
                return self._transactions_from_models(session, [row])[0]
            provisional = self._provisional_claims(session, claim_id=transaction_id, limit=1)
            if provisional:
                return provisional[0]
            raise OwnerWorkspaceError("Transaction was not found")

    def list_reviews(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        review_status: PendingReviewStatus = PendingReviewStatus.PENDING,
    ) -> OwnerReviewPage:
        if not 1 <= limit <= 100:
            raise OwnerWorkspaceError("Pending Review page limit must be between 1 and 100")
        position = self._decode_review_cursor(cursor) if cursor is not None else None
        with self._database.transaction() as session:
            statement = (
                select(PendingReview)
                .where(PendingReview.status == review_status.value)
                .order_by(PendingReview.created_at, PendingReview.id)
                .limit(limit + 1)
            )
            if position is not None:
                created_at, review_id = position
                statement = statement.where(
                    or_(
                        PendingReview.created_at > created_at,
                        and_(
                            PendingReview.created_at == created_at,
                            PendingReview.id > review_id,
                        ),
                    )
                )
            reviews = session.scalars(statement).all()
            page_reviews = reviews[:limit]
            next_cursor = None
            if len(reviews) > limit and page_reviews:
                last = page_reviews[-1]
                next_cursor = self._encode_review_cursor(last.created_at.isoformat(), last.id)
            return OwnerReviewPage(
                items=tuple(self._review(review) for review in page_reviews),
                next_cursor=next_cursor,
            )

    def get_review(self, review_id: UUID) -> OwnerReview:
        with self._database.transaction() as session:
            review = session.get(PendingReview, review_id)
            if review is None:
                raise OwnerWorkspaceError("Pending Review was not found")
            return self._review(review)

    def _confirmed_transactions(
        self,
        session: Session,
        *,
        position: tuple[date, UUID] | None = None,
        limit: int,
        financial_account_id: UUID | None = None,
        kind: TransactionKind | None = None,
        needs_review: bool | None = None,
    ) -> tuple[OwnerTransaction, ...]:
        statement = (
            select(FinancialTransaction, TransactionVersion, FinancialAccount)
            .join(
                TransactionVersion,
                and_(
                    TransactionVersion.transaction_id == FinancialTransaction.id,
                    TransactionVersion.version == FinancialTransaction.current_version,
                ),
            )
            .join(
                FinancialAccount,
                FinancialAccount.id == FinancialTransaction.financial_account_id,
            )
            .order_by(TransactionVersion.effective_date.desc(), FinancialTransaction.id.desc())
            .limit(limit)
        )
        if financial_account_id is not None:
            statement = statement.where(
                FinancialTransaction.financial_account_id == financial_account_id
            )
        if kind is not None:
            statement = statement.where(TransactionVersion.kind == kind.value)
        if needs_review is not None:
            has_pending_review = (
                select(PendingReview.id)
                .where(
                    PendingReview.subject_type == "transaction",
                    PendingReview.subject_id == FinancialTransaction.id,
                    PendingReview.status == PendingReviewStatus.PENDING.value,
                )
                .exists()
            )
            statement = statement.where(has_pending_review if needs_review else ~has_pending_review)
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
        return self._transactions_from_models(session, session.execute(statement).all())

    def _provisional_claims(
        self,
        session: Session,
        *,
        position: tuple[date, UUID] | None = None,
        limit: int,
        financial_account_id: UUID | None = None,
        kind: TransactionKind | None = None,
        needs_review: bool | None = None,
        claim_id: UUID | None = None,
    ) -> tuple[OwnerTransaction, ...]:
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
        statement = (
            select(Claim, FinancialAccount)
            .join(FinancialAccount, FinancialAccount.id == Claim.financial_account_id)
            .join(latest_disposition, latest_disposition.c.claim_id == Claim.id)
            .where(
                Claim.claim_type == ClaimType.REAL_TIME.value,
                latest_disposition.c.disposition.in_(_ELIGIBLE_REAL_TIME_DISPOSITIONS),
                Claim.authorized_amount.is_not(None),
                Claim.authorized_currency.is_not(None),
                Claim.occurrence_at.is_not(None),
                ~Claim.id.in_(select(TransactionClaim.claim_id)),
            )
        )
        if claim_id is not None:
            statement = statement.where(Claim.id == claim_id)
        if financial_account_id is not None:
            statement = statement.where(Claim.financial_account_id == financial_account_id)
        if needs_review is not None:
            has_pending_review = (
                select(PendingReview.id)
                .where(
                    PendingReview.subject_type == "claim",
                    PendingReview.subject_id == Claim.id,
                    PendingReview.status == PendingReviewStatus.PENDING.value,
                )
                .exists()
            )
            statement = statement.where(has_pending_review if needs_review else ~has_pending_review)
        rows = session.execute(statement).all()
        items = self._claims_from_models(session, rows)
        if kind is not None:
            items = tuple(item for item in items if item.kind == kind)
        if position is not None:
            effective_date, item_id = position
            cursor_date = effective_date.isoformat()
            items = tuple(
                item
                for item in items
                if item.effective_date < cursor_date
                or (item.effective_date == cursor_date and item.id < item_id)
            )
        return _sort_activity(items)[:limit]

    def _claims_from_models(
        self,
        session: Session,
        rows: Sequence[Row[tuple[Claim, FinancialAccount]]],
    ) -> tuple[OwnerTransaction, ...]:
        if not rows:
            return ()
        claim_ids = [claim.id for claim, _account in rows]
        reviews_by_claim: dict[UUID, list[OwnerReviewSummary]] = defaultdict(list)
        reviews = session.scalars(
            select(PendingReview)
            .where(
                PendingReview.subject_type == "claim",
                PendingReview.subject_id.in_(claim_ids),
                PendingReview.status == PendingReviewStatus.PENDING.value,
            )
            .order_by(PendingReview.created_at, PendingReview.id)
        ).all()
        for review in reviews:
            reviews_by_claim[review.subject_id].append(
                OwnerReviewSummary(
                    id=review.id,
                    condition_code=review.condition_code,
                    severity=ReviewSeverity(review.severity),
                    version=review.version,
                    allowed_decisions=tuple(review.allowed_decisions),
                )
            )
        items: list[OwnerTransaction] = []
        for claim, account in rows:
            if (
                claim.authorized_amount is None
                or claim.authorized_currency is None
                or claim.occurrence_at is None
            ):
                continue
            authorized = Money(claim.authorized_amount, claim.authorized_currency)
            kind = _claim_kind(claim.transaction_kind_hint)
            counterparty = _counterparty(claim.raw_description)
            items.append(
                OwnerTransaction(
                    id=claim.id,
                    version=1,
                    financial_account_id=account.id,
                    financial_account_name=account.display_name,
                    counterparty=counterparty,
                    posted_amount=Money.parse("0", authorized.currency),
                    authorized_amount=authorized,
                    effective_date=self._claim_effective_date(claim).isoformat(),
                    kind=kind,
                    category_splits=(),
                    reviews=tuple(reviews_by_claim[claim.id]),
                )
            )
        return tuple(items)

    def _claim_effective_date(self, claim: Claim) -> date:
        if claim.occurrence_at is None:
            raise OwnerWorkspaceError("Real-time Claim is missing occurrence time")
        return claim.occurrence_at.astimezone(self._reporting_timezone).date()

    @classmethod
    def _transactions_from_models(
        cls,
        session: Session,
        rows: Sequence[Row[tuple[FinancialTransaction, TransactionVersion, FinancialAccount]]],
    ) -> tuple[OwnerTransaction, ...]:
        if not rows:
            return ()
        version_ids = [version.id for _transaction, version, _account in rows]
        transaction_ids = [transaction.id for transaction, _version, _account in rows]
        splits_by_version: dict[UUID, list[CategorySplitRecord]] = defaultdict(list)
        split_rows = session.execute(
            select(CategorySplit, Category)
            .join(Category, Category.id == CategorySplit.category_id)
            .where(CategorySplit.transaction_version_id.in_(version_ids))
            .order_by(CategorySplit.transaction_version_id, CategorySplit.id)
        ).all()
        for split, category in split_rows:
            splits_by_version[split.transaction_version_id].append(
                CategorySplitRecord(
                    category_id=category.id,
                    category_name=category.name,
                    amount=Money(split.amount, split.currency),
                )
            )
        reviews_by_transaction: dict[UUID, list[OwnerReviewSummary]] = defaultdict(list)
        reviews = session.scalars(
            select(PendingReview)
            .where(
                PendingReview.subject_type == "transaction",
                PendingReview.subject_id.in_(transaction_ids),
                PendingReview.status == PendingReviewStatus.PENDING.value,
            )
            .order_by(PendingReview.created_at, PendingReview.id)
        ).all()
        for review in reviews:
            reviews_by_transaction[review.subject_id].append(
                OwnerReviewSummary(
                    id=review.id,
                    condition_code=review.condition_code,
                    severity=ReviewSeverity(review.severity),
                    version=review.version,
                    allowed_decisions=tuple(review.allowed_decisions),
                )
            )
        return tuple(
            OwnerTransaction(
                id=transaction.id,
                version=version.version,
                financial_account_id=account.id,
                financial_account_name=account.display_name,
                counterparty=version.counterparty,
                posted_amount=Money(version.posted_amount, version.posted_currency),
                authorized_amount=(
                    Money(version.authorized_amount, version.authorized_currency)
                    if version.authorized_amount is not None
                    and version.authorized_currency is not None
                    else None
                ),
                effective_date=version.effective_date.isoformat(),
                kind=TransactionKind(version.kind),
                category_splits=tuple(splits_by_version[version.id]),
                reviews=tuple(reviews_by_transaction[transaction.id]),
            )
            for transaction, version, account in rows
        )

    @staticmethod
    def _review(review: PendingReview) -> OwnerReview:
        return OwnerReview(
            id=review.id,
            subject_type=review.subject_type,
            subject_id=review.subject_id,
            condition_code=review.condition_code,
            severity=ReviewSeverity(review.severity),
            status=PendingReviewStatus(review.status),
            version=review.version,
            allowed_decisions=tuple(review.allowed_decisions),
            context=dict(review.context),
            created_at=review.created_at,
            updated_at=review.updated_at,
        )

    @staticmethod
    def _encode_transaction_cursor(effective_date: str, transaction_id: UUID) -> str:
        return _encode_cursor(
            {"effective_date": effective_date, "transaction_id": str(transaction_id)}
        )

    @staticmethod
    def _decode_transaction_cursor(cursor: str) -> tuple[Any, UUID]:
        payload = _decode_cursor(cursor)
        try:
            return date.fromisoformat(payload["effective_date"]), UUID(payload["transaction_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise OwnerWorkspaceError("Transaction cursor is invalid") from error

    @staticmethod
    def _encode_review_cursor(created_at: str, review_id: UUID) -> str:
        return _encode_cursor({"created_at": created_at, "review_id": str(review_id)})

    @staticmethod
    def _decode_review_cursor(cursor: str) -> tuple[datetime, UUID]:
        payload = _decode_cursor(cursor)
        try:
            created_at = datetime.fromisoformat(payload["created_at"])
            if created_at.tzinfo is None or created_at.utcoffset() is None:
                raise ValueError
            return created_at, UUID(payload["review_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise OwnerWorkspaceError("Pending Review cursor is invalid") from error


def _sort_activity(items: Sequence[OwnerTransaction]) -> tuple[OwnerTransaction, ...]:
    return tuple(sorted(items, key=lambda item: (item.effective_date, item.id), reverse=True))


def _counterparty(raw_description: str) -> str:
    return " ".join(raw_description.split())[:300]


def _claim_kind(hint: str | None) -> TransactionKind:
    if hint is None:
        return TransactionKind.EXPENSE
    try:
        return TransactionKind(hint)
    except ValueError:
        return TransactionKind.EXPENSE


def _encode_cursor(payload: dict[str, str]) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def _decode_cursor(cursor: str) -> dict[str, str]:
    if not cursor or len(cursor) > 512:
        raise OwnerWorkspaceError("cursor is invalid")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, json.JSONDecodeError) as error:
        raise OwnerWorkspaceError("cursor is invalid") from error
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
    ):
        raise OwnerWorkspaceError("cursor is invalid")
    return payload
