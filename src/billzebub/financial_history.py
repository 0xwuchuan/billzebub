"""Confirm trusted Transactions and maintain their balanced financial history."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute
from uuid6 import uuid7

from billzebub.claims import ClaimBook, ClaimDisposition, ClaimType
from billzebub.money import Money
from billzebub.persistence.models import (
    Category,
    CategorySplit,
    Claim,
    ClaimDispositionEvent,
    CorrectionEvent,
    FinancialAccount,
    FinancialTransaction,
    Journal,
    LedgerAccount,
    LedgerPosting,
    OffsetAllocation,
    TransactionClaim,
    TransactionVersion,
)
from billzebub.reviews import (
    ReviewCondition,
    ReviewInbox,
    ReviewSeverity,
    categorization_needed_context,
)

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class TransactionKind(StrEnum):
    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"
    REFUND = "refund"
    REIMBURSEMENT = "reimbursement"
    CASH_WITHDRAWAL = "cash_withdrawal"


class PostingDirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class FinancialHistoryError(ValueError):
    """Financial history policy rejected a requested operation."""


@dataclass(frozen=True, slots=True)
class CategoryAllocation:
    category_id: UUID
    amount: Money


@dataclass(frozen=True, slots=True)
class Confirmation:
    statement_claim_id: UUID
    kind: TransactionKind
    counterparty: str
    real_time_claim_id: UUID | None = None
    actor_id: UUID | None = None
    category_splits: tuple[CategoryAllocation, ...] = ()


@dataclass(frozen=True, slots=True)
class Correction:
    transaction_id: UUID
    reason: str
    kind: TransactionKind | None = None
    posted_amount: Money | None = None
    effective_date: date | None = None
    counterparty: str | None = None
    category_splits: tuple[CategoryAllocation, ...] | None = None
    actor_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class OffsetAllocationCommand:
    offset_transaction_id: UUID
    expense_transaction_id: UUID
    amount: Money
    actor_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class OffsetAllocationRecord:
    id: UUID
    offset_transaction_id: UUID
    expense_transaction_id: UUID
    amount: Money


@dataclass(frozen=True, slots=True)
class CategorySplitRecord:
    category_id: UUID
    category_name: str
    amount: Money


@dataclass(frozen=True, slots=True)
class TransactionSnapshot:
    id: UUID
    version_id: UUID
    version: int
    financial_account_id: UUID
    kind: TransactionKind
    posted_amount: Money
    authorized_amount: Money | None
    effective_date: date
    counterparty: str
    category_splits: tuple[CategorySplitRecord, ...]


@dataclass(frozen=True, slots=True)
class PostingRecord:
    direction: PostingDirection
    amount: Money
    ledger_account_code: str


@dataclass(frozen=True, slots=True)
class JournalRecord:
    id: UUID
    journal_type: str
    reverses_journal_id: UUID | None
    postings: tuple[PostingRecord, ...]

    @property
    def is_balanced(self) -> bool:
        balances: dict[str, Decimal] = defaultdict(Decimal)
        for posting in self.postings:
            multiplier = Decimal(1) if posting.direction is PostingDirection.DEBIT else Decimal(-1)
            balances[posting.amount.currency] += multiplier * posting.amount.amount
        return bool(self.postings) and all(amount == 0 for amount in balances.values())


@dataclass(frozen=True, slots=True)
class TransactionAudit:
    transaction_id: UUID
    versions: tuple[TransactionSnapshot, ...]
    journals: tuple[JournalRecord, ...]


class FinancialHistory:
    """Own confirmation and ledger policy behind one transactional interface."""

    def __init__(
        self,
        database: Database,
        *,
        reporting_timezone: str = "Asia/Singapore",
    ) -> None:
        self._database = database
        self._reporting_timezone = ZoneInfo(reporting_timezone)

    def confirm(self, command: Confirmation) -> TransactionSnapshot:
        with self._database.transaction() as session:
            return self.confirm_in_session(session, command)

    def confirm_in_session(
        self,
        session: Session,
        command: Confirmation,
    ) -> TransactionSnapshot:
        """Confirm a Transaction within a caller-owned database transaction."""
        if not command.counterparty.strip():
            raise FinancialHistoryError("a Counterparty is required")

        statement = self._locked_claim(session, command.statement_claim_id)
        if statement.claim_type != ClaimType.STATEMENT.value:
            raise FinancialHistoryError("confirmation requires a Statement Claim")

        existing = session.scalar(
            select(TransactionClaim).where(TransactionClaim.claim_id == statement.id)
        )
        if existing is not None:
            return self._current_snapshot(session, existing.transaction_id)

        real_time: Claim | None = None
        if command.real_time_claim_id is not None:
            real_time = self._locked_claim(session, command.real_time_claim_id)
            if real_time.claim_type != ClaimType.REAL_TIME.value:
                raise FinancialHistoryError("real-time evidence must be a Real-time Claim")
            if real_time.financial_account_id != statement.financial_account_id:
                raise FinancialHistoryError("all Claims must use the same Financial Account")

        self._require_confirmable(session, statement.id)
        if real_time is not None:
            self._require_confirmable(session, real_time.id)
        posted = self._posted_money(statement)
        self._validate_kind_direction(command.kind, posted)

        transaction_id = uuid7()
        version_id = uuid7()
        transaction = FinancialTransaction(
            id=transaction_id,
            financial_account_id=statement.financial_account_id,
            current_version=1,
        )
        session.add(transaction)
        session.flush()

        authorized = self._authorized_money(real_time) if real_time else None
        effective_date = self._effective_date(statement, real_time)
        version = TransactionVersion(
            id=version_id,
            transaction_id=transaction_id,
            version=1,
            kind=command.kind.value,
            posted_amount=posted.amount,
            posted_currency=posted.currency,
            authorized_amount=authorized.amount if authorized else None,
            authorized_currency=authorized.currency if authorized else None,
            effective_date=effective_date,
            occurrence_at=real_time.occurrence_at if real_time else None,
            provider_transaction_date=statement.provider_transaction_date,
            posting_date=statement.posting_date,
            counterparty=command.counterparty.strip(),
            actor_id=command.actor_id,
        )
        session.add(version)
        session.add(
            TransactionClaim(
                id=uuid7(),
                transaction_id=transaction_id,
                claim_id=statement.id,
                role=ClaimType.STATEMENT.value,
            )
        )
        if real_time is not None:
            session.add(
                TransactionClaim(
                    id=uuid7(),
                    transaction_id=transaction_id,
                    claim_id=real_time.id,
                    role=ClaimType.REAL_TIME.value,
                )
            )
        session.flush()

        splits = self._category_splits(
            session,
            version,
            command.kind,
            posted,
            command.category_splits,
        )
        self._write_journal(
            session,
            version,
            statement.financial_account_id,
            command.kind,
            posted,
            splits,
            journal_type="confirmation",
        )
        ClaimBook.confirm_in_session(
            session,
            statement.id,
            reason_code="transaction_confirmed",
            actor_id=command.actor_id,
        )
        if real_time is not None:
            ClaimBook.confirm_in_session(
                session,
                real_time.id,
                reason_code="transaction_confirmed",
                actor_id=command.actor_id,
            )
        self._sync_categorization_review(session, transaction.id, command.kind, splits)
        session.flush()
        return self._snapshot(session, transaction, version)

    def correct(self, command: Correction) -> TransactionSnapshot:
        with self._database.transaction() as session:
            return self.correct_in_session(session, command)

    def correct_in_session(
        self,
        session: Session,
        command: Correction,
    ) -> TransactionSnapshot:
        """Apply a Correction within a caller-owned database transaction."""
        if not command.reason.strip():
            raise FinancialHistoryError("a Correction reason is required")
        if command.counterparty is not None and not command.counterparty.strip():
            raise FinancialHistoryError("a Counterparty cannot be empty")

        transaction = session.scalar(
            select(FinancialTransaction)
            .where(FinancialTransaction.id == command.transaction_id)
            .with_for_update()
        )
        if transaction is None:
            raise FinancialHistoryError("Transaction was not found")
        prior = session.scalar(
            select(TransactionVersion).where(
                TransactionVersion.transaction_id == transaction.id,
                TransactionVersion.version == transaction.current_version,
            )
        )
        if prior is None:
            raise FinancialHistoryError("Transaction current version is missing")

        kind = command.kind or TransactionKind(prior.kind)
        posted = command.posted_amount or Money(prior.posted_amount, prior.posted_currency)
        self._validate_kind_direction(kind, posted)
        self._validate_existing_allocations(session, transaction.id, kind, posted)
        allocations = command.category_splits
        if allocations is None:
            allocations = self._preserved_allocations(session, prior, kind, posted)

        replacement = TransactionVersion(
            id=uuid7(),
            transaction_id=transaction.id,
            version=prior.version + 1,
            kind=kind.value,
            posted_amount=posted.amount,
            posted_currency=posted.currency,
            authorized_amount=prior.authorized_amount,
            authorized_currency=prior.authorized_currency,
            effective_date=command.effective_date or prior.effective_date,
            occurrence_at=prior.occurrence_at,
            provider_transaction_date=prior.provider_transaction_date,
            posting_date=prior.posting_date,
            counterparty=(command.counterparty or prior.counterparty).strip(),
            supersedes_version_id=prior.id,
            actor_id=command.actor_id,
        )
        session.add(replacement)
        session.flush()
        splits = self._category_splits(session, replacement, kind, posted, allocations)

        prior_journal = session.scalar(
            select(Journal)
            .where(
                Journal.transaction_version_id == prior.id,
                Journal.journal_type.in_(("confirmation", "correction_replacement")),
            )
            .order_by(Journal.created_at.desc(), Journal.id.desc())
            .limit(1)
        )
        if prior_journal is None:
            raise FinancialHistoryError("prior effective journal is missing")
        self._reverse_journal(session, replacement, prior_journal)
        self._write_journal(
            session,
            replacement,
            transaction.financial_account_id,
            kind,
            posted,
            splits,
            journal_type="correction_replacement",
        )
        session.add(
            CorrectionEvent(
                id=uuid7(),
                transaction_id=transaction.id,
                prior_version_id=prior.id,
                replacement_version_id=replacement.id,
                reason=command.reason.strip(),
                actor_id=command.actor_id,
            )
        )
        transaction.current_version = replacement.version
        self._sync_categorization_review(session, transaction.id, kind, splits)
        session.flush()
        return self._snapshot(session, transaction, replacement)

    def allocate_offset(self, command: OffsetAllocationCommand) -> OffsetAllocationRecord:
        if command.amount.amount <= 0:
            raise FinancialHistoryError("an Offset Allocation amount must be positive")
        if command.offset_transaction_id == command.expense_transaction_id:
            raise FinancialHistoryError("an Offset Allocation requires two Transactions")

        with self._database.transaction() as session:
            transaction_ids = sorted(
                (command.offset_transaction_id, command.expense_transaction_id),
                key=str,
            )
            transactions = session.scalars(
                select(FinancialTransaction)
                .where(FinancialTransaction.id.in_(transaction_ids))
                .order_by(FinancialTransaction.id)
                .with_for_update()
            ).all()
            by_id = {transaction.id: transaction for transaction in transactions}
            if len(by_id) != 2:
                raise FinancialHistoryError("Offset Allocation Transaction was not found")
            offset_transaction = by_id[command.offset_transaction_id]
            expense_transaction = by_id[command.expense_transaction_id]
            offset_version = self._version_for(session, offset_transaction)
            expense_version = self._version_for(session, expense_transaction)
            if TransactionKind(offset_version.kind) not in {
                TransactionKind.REFUND,
                TransactionKind.REIMBURSEMENT,
            }:
                raise FinancialHistoryError(
                    "Offset Allocation source must be a Refund or Reimbursement"
                )
            if TransactionKind(expense_version.kind) not in {
                TransactionKind.EXPENSE,
                TransactionKind.CASH_WITHDRAWAL,
            }:
                raise FinancialHistoryError("Offset Allocation target must be an Expense")
            if (
                command.amount.currency != offset_version.posted_currency
                or command.amount.currency != expense_version.posted_currency
            ):
                raise FinancialHistoryError(
                    "Offset Allocation currency must match both Transactions"
                )

            allocated_from_offset = self._allocated_total(
                session,
                OffsetAllocation.offset_transaction_id,
                offset_transaction.id,
            )
            allocated_to_expense = self._allocated_total(
                session,
                OffsetAllocation.expense_transaction_id,
                expense_transaction.id,
            )
            if allocated_from_offset + command.amount.amount > abs(offset_version.posted_amount):
                raise FinancialHistoryError("Offset Allocation exceeds the available offset")
            if allocated_to_expense + command.amount.amount > abs(expense_version.posted_amount):
                raise FinancialHistoryError("Offset Allocation exceeds the available Expense")

            allocation = OffsetAllocation(
                id=uuid7(),
                offset_transaction_id=offset_transaction.id,
                expense_transaction_id=expense_transaction.id,
                amount=command.amount.amount,
                currency=command.amount.currency,
                actor_id=command.actor_id,
            )
            session.add(allocation)
            session.flush()
            self._write_offset_journal(session, offset_version, allocation)
            return OffsetAllocationRecord(
                id=allocation.id,
                offset_transaction_id=allocation.offset_transaction_id,
                expense_transaction_id=allocation.expense_transaction_id,
                amount=Money(allocation.amount, allocation.currency),
            )

    def get(self, transaction_id: UUID) -> TransactionSnapshot:
        with self._database.transaction() as session:
            return self.current_in_session(session, transaction_id)

    def current_in_session(self, session: Session, transaction_id: UUID) -> TransactionSnapshot:
        """Return and lock the current effective Transaction version."""
        transaction = session.scalar(
            select(FinancialTransaction)
            .where(FinancialTransaction.id == transaction_id)
            .with_for_update()
        )
        if transaction is None:
            raise FinancialHistoryError("Transaction was not found")
        return self._snapshot(session, transaction, self._version_for(session, transaction))

    def audit(self, transaction_id: UUID) -> TransactionAudit:
        with self._database.transaction() as session:
            transaction = session.get(FinancialTransaction, transaction_id)
            if transaction is None:
                raise FinancialHistoryError("Transaction was not found")
            versions = session.scalars(
                select(TransactionVersion)
                .where(TransactionVersion.transaction_id == transaction_id)
                .order_by(TransactionVersion.version)
            ).all()
            snapshots = tuple(self._snapshot(session, transaction, version) for version in versions)
            version_ids = [version.id for version in versions]
            journals = session.scalars(
                select(Journal)
                .where(Journal.transaction_version_id.in_(version_ids))
                .order_by(Journal.created_at, Journal.id)
            ).all()
            return TransactionAudit(
                transaction_id=transaction_id,
                versions=snapshots,
                journals=tuple(self._journal_record(session, journal) for journal in journals),
            )

    @staticmethod
    def _version_for(
        session: Session,
        transaction: FinancialTransaction,
    ) -> TransactionVersion:
        version = session.scalar(
            select(TransactionVersion).where(
                TransactionVersion.transaction_id == transaction.id,
                TransactionVersion.version == transaction.current_version,
            )
        )
        if version is None:
            raise FinancialHistoryError("Transaction current version is missing")
        return version

    @staticmethod
    def _allocated_total(
        session: Session,
        transaction_column: InstrumentedAttribute[UUID],
        transaction_id: UUID,
    ) -> Decimal:
        amounts = session.scalars(
            select(OffsetAllocation.amount).where(transaction_column == transaction_id)
        ).all()
        return sum(amounts, Decimal(0))

    @classmethod
    def _validate_existing_allocations(
        cls,
        session: Session,
        transaction_id: UUID,
        replacement_kind: TransactionKind,
        replacement_amount: Money,
    ) -> None:
        as_offset = session.scalars(
            select(OffsetAllocation).where(OffsetAllocation.offset_transaction_id == transaction_id)
        ).all()
        as_expense = session.scalars(
            select(OffsetAllocation).where(
                OffsetAllocation.expense_transaction_id == transaction_id
            )
        ).all()
        if as_offset:
            if replacement_kind not in {
                TransactionKind.REFUND,
                TransactionKind.REIMBURSEMENT,
            }:
                raise FinancialHistoryError(
                    "a Transaction with Offset Allocations must remain an offset"
                )
            if any(allocation.currency != replacement_amount.currency for allocation in as_offset):
                raise FinancialHistoryError("Correction cannot change an allocated currency")
            if sum((allocation.amount for allocation in as_offset), Decimal(0)) > abs(
                replacement_amount.amount
            ):
                raise FinancialHistoryError("Correction would overallocate the offset")
        if as_expense:
            if replacement_kind not in {
                TransactionKind.EXPENSE,
                TransactionKind.CASH_WITHDRAWAL,
            }:
                raise FinancialHistoryError(
                    "a Transaction targeted by Offset Allocations must remain an Expense"
                )
            if any(allocation.currency != replacement_amount.currency for allocation in as_expense):
                raise FinancialHistoryError("Correction cannot change an allocated currency")
            if sum((allocation.amount for allocation in as_expense), Decimal(0)) > abs(
                replacement_amount.amount
            ):
                raise FinancialHistoryError("Correction would overallocate the Expense")

    @staticmethod
    def _locked_claim(session: Session, claim_id: UUID) -> Claim:
        claim = session.scalar(select(Claim).where(Claim.id == claim_id).with_for_update())
        if claim is None:
            raise FinancialHistoryError("Claim was not found")
        return claim

    @staticmethod
    def _require_confirmable(session: Session, claim_id: UUID) -> None:
        event = session.scalar(
            select(ClaimDispositionEvent)
            .where(ClaimDispositionEvent.claim_id == claim_id)
            .order_by(ClaimDispositionEvent.occurred_at.desc(), ClaimDispositionEvent.id.desc())
            .limit(1)
        )
        if event is None:
            raise FinancialHistoryError("Claim has no Claim Disposition")
        disposition = ClaimDisposition(event.disposition)
        if disposition not in {ClaimDisposition.PROVISIONAL, ClaimDisposition.UNCONFIRMED}:
            raise FinancialHistoryError(f"{disposition.value.title()} Claim cannot be confirmed")

    @staticmethod
    def _posted_money(statement: Claim) -> Money:
        if statement.posted_amount is None or statement.posted_currency is None:
            raise FinancialHistoryError("Statement Claim has no Posted Amount")
        return Money(statement.posted_amount, statement.posted_currency)

    @staticmethod
    def _authorized_money(real_time: Claim) -> Money:
        if real_time.authorized_amount is None or real_time.authorized_currency is None:
            raise FinancialHistoryError("Real-time Claim has no Authorized Amount")
        return Money(real_time.authorized_amount, real_time.authorized_currency)

    def _effective_date(self, statement: Claim, real_time: Claim | None) -> date:
        if real_time is not None and real_time.occurrence_at is not None:
            return real_time.occurrence_at.astimezone(self._reporting_timezone).date()
        if statement.provider_transaction_date is not None:
            return statement.provider_transaction_date
        if statement.posting_date is None:
            raise FinancialHistoryError("Statement Claim has no posting date")
        return statement.posting_date

    @staticmethod
    def _validate_kind_direction(kind: TransactionKind, amount: Money) -> None:
        negative_kinds = {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}
        positive_kinds = {
            TransactionKind.INCOME,
            TransactionKind.REFUND,
            TransactionKind.REIMBURSEMENT,
        }
        if kind in negative_kinds and amount.amount >= 0:
            raise FinancialHistoryError(f"{kind.value} requires a negative Posted Amount")
        if kind in positive_kinds and amount.amount <= 0:
            raise FinancialHistoryError(f"{kind.value} requires a positive Posted Amount")

    @staticmethod
    def _uncategorized(session: Session) -> Category:
        category = session.scalar(
            select(Category).where(Category.parent_id.is_(None), Category.name == "Uncategorized")
        )
        if category is None:
            category = Category(id=uuid7(), name="Uncategorized", active=True, sort_order=0)
            session.add(category)
            session.flush()
        return category

    @staticmethod
    def _sync_categorization_review(
        session: Session,
        transaction_id: UUID,
        kind: TransactionKind,
        splits: tuple[CategorySplit, ...],
    ) -> None:
        uncategorized_id = session.scalar(
            select(Category.id).where(
                Category.parent_id.is_(None),
                Category.name == "Uncategorized",
            )
        )
        needs_categorization = (
            kind in {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}
            and uncategorized_id is not None
            and any(split.category_id == uncategorized_id for split in splits)
        )
        ReviewInbox.synchronize_in_session(
            session,
            ReviewCondition(
                subject_type="transaction",
                subject_id=transaction_id,
                condition_code="categorization_needed",
                severity=ReviewSeverity.ATTENTION,
                allowed_decisions=("categorize",),
                context=(
                    FinancialHistory._categorization_review_context(session, transaction_id)
                    if needs_categorization
                    else {}
                ),
            ),
            active=needs_categorization,
        )

    @staticmethod
    def _categorization_review_context(session: Session, transaction_id: UUID) -> dict[str, object]:
        transaction = session.get(FinancialTransaction, transaction_id)
        if transaction is None:
            return {"transaction_id": str(transaction_id)}
        version = session.scalar(
            select(TransactionVersion).where(
                TransactionVersion.transaction_id == transaction.id,
                TransactionVersion.version == transaction.current_version,
            )
        )
        account = session.get(FinancialAccount, transaction.financial_account_id)
        if version is None or account is None:
            return {"transaction_id": str(transaction_id)}
        posted = Money(version.posted_amount, version.posted_currency)
        amount = posted
        if (
            posted.amount == 0
            and version.authorized_amount is not None
            and version.authorized_currency is not None
        ):
            amount = Money(version.authorized_amount, version.authorized_currency)
        return categorization_needed_context(
            transaction_id=transaction.id,
            counterparty=version.counterparty,
            amount=format(amount.amount, "f"),
            currency=amount.currency,
            account=account.display_name,
            financial_account_id=account.id,
            effective_date=version.effective_date.isoformat(),
            version=version.version,
            kind=version.kind,
        )

    @staticmethod
    def _preserved_allocations(
        session: Session,
        prior: TransactionVersion,
        replacement_kind: TransactionKind,
        replacement_amount: Money,
    ) -> tuple[CategoryAllocation, ...]:
        spending_kinds = {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}
        if replacement_kind not in spending_kinds:
            return ()
        if TransactionKind(prior.kind) not in spending_kinds:
            return ()
        if (
            replacement_amount.amount != prior.posted_amount
            or replacement_amount.currency != prior.posted_currency
        ):
            raise FinancialHistoryError(
                "a changed Expense amount requires replacement Category Splits"
            )
        splits = session.scalars(
            select(CategorySplit)
            .where(CategorySplit.transaction_version_id == prior.id)
            .order_by(CategorySplit.id)
        ).all()
        return tuple(
            CategoryAllocation(
                category_id=split.category_id,
                amount=Money(split.amount, split.currency),
            )
            for split in splits
        )

    def _category_splits(
        self,
        session: Session,
        version: TransactionVersion,
        kind: TransactionKind,
        posted: Money,
        allocations: tuple[CategoryAllocation, ...],
    ) -> tuple[CategorySplit, ...]:
        spending_kinds = {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}
        if kind not in spending_kinds:
            if allocations:
                raise FinancialHistoryError("only an Expense can have Category Splits")
            return ()
        if not allocations:
            default_category = self._uncategorized(session)
            allocations = (
                CategoryAllocation(
                    category_id=default_category.id,
                    amount=Money(abs(posted.amount), posted.currency),
                ),
            )

        if len({allocation.category_id for allocation in allocations}) != len(allocations):
            raise FinancialHistoryError("a Category may appear only once in Category Splits")
        if any(
            allocation.amount.currency != posted.currency or allocation.amount.amount <= 0
            for allocation in allocations
        ):
            raise FinancialHistoryError(
                "Category Splits require positive amounts in the Posted Amount currency"
            )
        if sum((allocation.amount.amount for allocation in allocations), Decimal(0)) != abs(
            posted.amount
        ):
            raise FinancialHistoryError("Category Splits must equal the Expense Posted Amount")

        splits: list[CategorySplit] = []
        for allocation in allocations:
            category = session.get(Category, allocation.category_id)
            if category is None or not category.active:
                raise FinancialHistoryError("Category Split references an unavailable Category")
            split = CategorySplit(
                id=uuid7(),
                transaction_version_id=version.id,
                category_id=allocation.category_id,
                amount=allocation.amount.amount,
                currency=allocation.amount.currency,
            )
            session.add(split)
            splits.append(split)
        session.flush()
        return tuple(splits)

    @staticmethod
    def _reverse_journal(
        session: Session,
        replacement: TransactionVersion,
        prior_journal: Journal,
    ) -> Journal:
        reversal = Journal(
            id=uuid7(),
            transaction_version_id=replacement.id,
            journal_type="correction_reversal",
            reverses_journal_id=prior_journal.id,
        )
        session.add(reversal)
        session.flush()
        prior_postings = session.scalars(
            select(LedgerPosting)
            .where(LedgerPosting.journal_id == prior_journal.id)
            .order_by(LedgerPosting.id)
        ).all()
        if not prior_postings:
            raise FinancialHistoryError("prior journal has no postings")
        for posting in prior_postings:
            reverse_direction = (
                PostingDirection.CREDIT
                if PostingDirection(posting.direction) is PostingDirection.DEBIT
                else PostingDirection.DEBIT
            )
            session.add(
                LedgerPosting(
                    id=uuid7(),
                    journal_id=reversal.id,
                    ledger_account_id=posting.ledger_account_id,
                    direction=reverse_direction.value,
                    amount=posting.amount,
                    currency=posting.currency,
                )
            )
        session.flush()
        return reversal

    def _write_offset_journal(
        self,
        session: Session,
        offset_version: TransactionVersion,
        allocation: OffsetAllocation,
    ) -> Journal:
        journal = Journal(
            id=uuid7(),
            transaction_version_id=offset_version.id,
            journal_type="offset_allocation",
            offset_allocation_id=allocation.id,
        )
        session.add(journal)
        session.flush()
        unallocated = self._ledger_account(
            session,
            code="system:offset_unallocated",
            account_type="offset_unallocated",
            name="Offset Unallocated",
        )
        allocated = self._ledger_account(
            session,
            code="system:offset_allocated",
            account_type="offset_allocated",
            name="Offset Allocated",
        )
        for account, direction in (
            (unallocated, PostingDirection.DEBIT),
            (allocated, PostingDirection.CREDIT),
        ):
            session.add(
                LedgerPosting(
                    id=uuid7(),
                    journal_id=journal.id,
                    ledger_account_id=account.id,
                    direction=direction.value,
                    amount=allocation.amount,
                    currency=allocation.currency,
                )
            )
        session.flush()
        return journal

    def _write_journal(
        self,
        session: Session,
        version: TransactionVersion,
        financial_account_id: UUID,
        kind: TransactionKind,
        posted: Money,
        splits: tuple[CategorySplit, ...],
        *,
        journal_type: str,
    ) -> Journal:
        journal = Journal(
            id=uuid7(),
            transaction_version_id=version.id,
            journal_type=journal_type,
        )
        session.add(journal)
        session.flush()
        financial = self._ledger_account(
            session,
            code=f"financial:{financial_account_id}",
            account_type="financial",
            name="Tracked Financial Account",
            financial_account_id=financial_account_id,
        )
        magnitude = abs(posted.amount)

        postings: list[tuple[LedgerAccount, PostingDirection, Decimal]] = []
        if kind in {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}:
            for split in splits:
                category = self._ledger_account(
                    session,
                    code=f"category:{split.category_id}",
                    account_type="category",
                    name="Expense Category",
                    category_id=split.category_id,
                )
                postings.append((category, PostingDirection.DEBIT, split.amount))
            postings.append((financial, PostingDirection.CREDIT, magnitude))
        else:
            counterpart_type = {
                TransactionKind.INCOME: "income",
                TransactionKind.TRANSFER: "transfer",
                TransactionKind.REFUND: "offset_unallocated",
                TransactionKind.REIMBURSEMENT: "offset_unallocated",
            }[kind]
            counterpart = self._ledger_account(
                session,
                code=f"system:{counterpart_type}",
                account_type=counterpart_type,
                name=counterpart_type.replace("_", " ").title(),
            )
            if posted.amount > 0:
                postings.extend(
                    [
                        (financial, PostingDirection.DEBIT, magnitude),
                        (counterpart, PostingDirection.CREDIT, magnitude),
                    ]
                )
            else:
                postings.extend(
                    [
                        (counterpart, PostingDirection.DEBIT, magnitude),
                        (financial, PostingDirection.CREDIT, magnitude),
                    ]
                )

        for account, direction, amount in postings:
            session.add(
                LedgerPosting(
                    id=uuid7(),
                    journal_id=journal.id,
                    ledger_account_id=account.id,
                    direction=direction.value,
                    amount=amount,
                    currency=posted.currency,
                )
            )
        session.flush()
        return journal

    @staticmethod
    def _ledger_account(
        session: Session,
        *,
        code: str,
        account_type: str,
        name: str,
        financial_account_id: UUID | None = None,
        category_id: UUID | None = None,
    ) -> LedgerAccount:
        account = session.scalar(select(LedgerAccount).where(LedgerAccount.code == code))
        if account is None:
            account = LedgerAccount(
                id=uuid7(),
                code=code,
                account_type=account_type,
                name=name,
                financial_account_id=financial_account_id,
                category_id=category_id,
            )
            session.add(account)
            session.flush()
        return account

    def _current_snapshot(self, session: Session, transaction_id: UUID) -> TransactionSnapshot:
        transaction = session.get(FinancialTransaction, transaction_id)
        if transaction is None:
            raise FinancialHistoryError("Transaction was not found")
        version = session.scalar(
            select(TransactionVersion).where(
                TransactionVersion.transaction_id == transaction_id,
                TransactionVersion.version == transaction.current_version,
            )
        )
        if version is None:
            raise FinancialHistoryError("Transaction current version is missing")
        return self._snapshot(session, transaction, version)

    @staticmethod
    def _snapshot(
        session: Session,
        transaction: FinancialTransaction,
        version: TransactionVersion,
    ) -> TransactionSnapshot:
        split_rows = session.execute(
            select(CategorySplit, Category.name)
            .join(Category, Category.id == CategorySplit.category_id)
            .where(CategorySplit.transaction_version_id == version.id)
            .order_by(CategorySplit.id)
        ).all()
        return TransactionSnapshot(
            id=transaction.id,
            version_id=version.id,
            version=version.version,
            financial_account_id=transaction.financial_account_id,
            kind=TransactionKind(version.kind),
            posted_amount=Money(version.posted_amount, version.posted_currency),
            authorized_amount=(
                Money(version.authorized_amount, version.authorized_currency)
                if version.authorized_amount is not None and version.authorized_currency is not None
                else None
            ),
            effective_date=version.effective_date,
            counterparty=version.counterparty,
            category_splits=tuple(
                CategorySplitRecord(
                    category_id=split.category_id,
                    category_name=category_name,
                    amount=Money(split.amount, split.currency),
                )
                for split, category_name in split_rows
            ),
        )

    @staticmethod
    def _journal_record(session: Session, journal: Journal) -> JournalRecord:
        rows = session.execute(
            select(LedgerPosting, LedgerAccount.code)
            .join(LedgerAccount, LedgerAccount.id == LedgerPosting.ledger_account_id)
            .where(LedgerPosting.journal_id == journal.id)
            .order_by(LedgerPosting.id)
        ).all()
        return JournalRecord(
            id=journal.id,
            journal_type=journal.journal_type,
            reverses_journal_id=journal.reverses_journal_id,
            postings=tuple(
                PostingRecord(
                    direction=PostingDirection(posting.direction),
                    amount=Money(posting.amount, posting.currency),
                    ledger_account_code=account_code,
                )
                for posting, account_code in rows
            ),
        )
