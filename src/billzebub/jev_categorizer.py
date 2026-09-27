"""Apply in-worker Jev Category proposals to spending Transactions and Claims.

This is the NAS-primary auto-categorizer. It runs inside the worker after
statement confirmation (including Real-time Claim matches), after a new
claim-only provisional Apple Wallet Real-time Claim, and on a daily catch-up
for leftovers. Below the confidence floor it leaves the row uncategorized.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.claims import ClaimDisposition, ClaimType
from billzebub.financial_history import (
    FinancialHistory,
    FinancialHistoryError,
    TransactionKind,
    TransactionSnapshot,
)
from billzebub.jev import DEFAULT_MODEL, JevCategory, JevError, JevSubject, Proposal, Proposer
from billzebub.jev_attempts import proposal_from_jev_error, record_jev_attempt
from billzebub.owner_transaction_actions import (
    OwnerCategorizationCommand,
    OwnerTransactionActionError,
    OwnerTransactionActions,
)
from billzebub.persistence.models import (
    AuditActor,
    AuditActorKind,
    Category,
    Claim,
    ClaimCategory,
    ClaimDispositionEvent,
    Extraction,
    PendingReview,
    TransactionClaim,
)
from billzebub.reviews import PendingReviewStatus

if TYPE_CHECKING:
    from billzebub.persistence.database import Database

logger = logging.getLogger(__name__)

CATEGORIZE_TRANSACTION_JOB = "categorize_transaction"
CATEGORIZE_CLAIM_JOB = "categorize_claim"
JEV_CATCH_UP_JOB = "jev_catch_up"
APPLE_WALLET_ADAPTER_KEY = "apple_wallet_shortcut"
_UNCATEGORIZED = "Uncategorized"
_SPENDING_KINDS = frozenset({TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL})
_ELIGIBLE_CLAIM_DISPOSITIONS = frozenset(
    {ClaimDisposition.PROVISIONAL.value, ClaimDisposition.UNCONFIRMED.value}
)
DEFAULT_CATCHUP_HOUR = 21
DEFAULT_CATCHUP_TIMEZONE = "Asia/Singapore"
DEFAULT_CATCHUP_CRON = "0 21 * * *"


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


class CategorizerError(ValueError):
    """Categorizer policy rejected a requested operation."""


@dataclass
class JevCatchupScheduler:
    """Due once per local calendar day at or after the configured hour."""

    hour: int = DEFAULT_CATCHUP_HOUR
    timezone: ZoneInfo = field(default_factory=lambda: ZoneInfo(DEFAULT_CATCHUP_TIMEZONE))
    _queued_dates: set[date] = field(default_factory=set)

    def catchup_date(self, now: datetime) -> str | None:
        if not 0 <= self.hour <= 23:
            return None
        local = now.astimezone(self.timezone)
        if local.hour < self.hour:
            return None
        if local.date() in self._queued_dates:
            return None
        self._queued_dates.add(local.date())
        return local.date().isoformat()


def enqueue_transaction_categorization(queue: JobEnqueuer, transaction_id: UUID) -> None:
    queue.enqueue(
        CATEGORIZE_TRANSACTION_JOB,
        {"transaction_id": str(transaction_id)},
        dedupe_key=str(transaction_id),
    )


def enqueue_claim_categorization(queue: JobEnqueuer, claim_id: UUID) -> None:
    queue.enqueue(
        CATEGORIZE_CLAIM_JOB,
        {"claim_id": str(claim_id)},
        dedupe_key=str(claim_id),
    )


def enqueue_accepted_claim(queue: JobEnqueuer) -> Callable[[UUID], None]:
    """Queue Jev for a newly accepted claim-only Apple Wallet Real-time Claim."""

    def enqueue(claim_id: UUID) -> None:
        enqueue_claim_categorization(queue, claim_id)

    return enqueue


def enqueue_jev_catch_up(queue: JobEnqueuer, run_date: str) -> None:
    queue.enqueue(
        JEV_CATCH_UP_JOB,
        {"run_date": run_date},
        dedupe_key=run_date,
    )


def subject_from_snapshot(snapshot: TransactionSnapshot) -> JevSubject:
    return JevSubject(
        counterparty=snapshot.counterparty,
        amount=format(snapshot.posted_amount.amount, "f"),
        currency=snapshot.posted_amount.currency,
        effective_date=snapshot.effective_date.isoformat(),
        kind=snapshot.kind.value,
    )


def subject_from_claim(claim: Claim, *, timezone: ZoneInfo) -> JevSubject:
    """Agent-safe Claim fields. Same shape Jev already receives for Transactions."""
    authorized_amount = claim.authorized_amount
    authorized_currency = claim.authorized_currency
    occurrence_at = claim.occurrence_at
    if authorized_amount is None or authorized_currency is None or occurrence_at is None:
        raise CategorizerError("Claim is missing categorization evidence")
    kind = claim.transaction_kind_hint or TransactionKind.EXPENSE.value
    counterparty = " ".join(claim.raw_description.split())[:300]
    if not counterparty:
        raise CategorizerError("Claim is missing a Counterparty")
    return JevSubject(
        counterparty=counterparty,
        amount=format(authorized_amount, "f"),
        currency=authorized_currency,
        effective_date=occurrence_at.astimezone(timezone).date().isoformat(),
        kind=kind,
    )


class JevCategorizer:
    """Assign high-confidence Jev Categories through the owner categorization path."""

    def __init__(
        self,
        database: Database,
        proposer: Proposer | None,
        *,
        min_confidence: object | None = None,
        reporting_timezone: str = "Asia/Singapore",
    ) -> None:
        del min_confidence
        self._database = database
        self._proposer = proposer
        self._actions = OwnerTransactionActions(database)
        self._history = FinancialHistory(database)
        self._reporting_timezone = ZoneInfo(reporting_timezone)

    def pending_transaction_ids(self) -> tuple[UUID, ...]:
        with self._database.transaction() as session:
            return self._pending_transaction_ids_in_session(session)

    def pending_claim_ids(self) -> tuple[UUID, ...]:
        with self._database.transaction() as session:
            return self._pending_claim_ids_in_session(session)

    def enqueue_pending(self, queue: JobEnqueuer) -> int:
        transaction_ids = self.pending_transaction_ids()
        claim_ids = self.pending_claim_ids()
        for transaction_id in transaction_ids:
            enqueue_transaction_categorization(queue, transaction_id)
        for claim_id in claim_ids:
            enqueue_claim_categorization(queue, claim_id)
        return len(transaction_ids) + len(claim_ids)

    def categorize_transaction(self, transaction_id: UUID) -> TransactionSnapshot | None:
        retry: JevError | None = None
        logged: tuple[UUID, Proposal] | None = None
        updated: TransactionSnapshot | None = None
        try:
            with self._database.transaction() as session:
                snapshot = self._history.current_in_session(session, transaction_id)
                if snapshot.kind not in _SPENDING_KINDS or not self._needs_category(snapshot):
                    return None
                if self._proposer is None:
                    return None
                subject = subject_from_snapshot(snapshot)
                try:
                    proposal = self._propose_for_subject(session, subject)
                except JevError as error:
                    proposal = proposal_from_jev_error(error, model=self._proposer_model())
                    retry = error
                record_jev_attempt(
                    session,
                    transaction_id=snapshot.id,
                    subject=subject,
                    proposal=proposal,
                )
                logged = (snapshot.id, proposal)
                if retry is not None:
                    updated = None
                elif proposal.action != "apply" or proposal.category_id is None:
                    updated = None
                else:
                    try:
                        updated = self._actions.categorize_in_session(
                            session,
                            OwnerCategorizationCommand(
                                transaction_id=snapshot.id,
                                expected_version=snapshot.version,
                                category_id=proposal.category_id,
                                actor_id=self._system_actor_id(session),
                                reason="jev_categorization",
                            ),
                        )
                    except OwnerTransactionActionError as error:
                        raise CategorizerError(str(error)) from error
        except FinancialHistoryError as error:
            raise CategorizerError(str(error)) from error
        if logged is not None:
            _log_attempt(logged[0], logged[1])
        if retry is not None:
            raise retry
        return updated

    def categorize_claim(self, claim_id: UUID) -> UUID | None:
        """Apply the same Choice proposal to one claim-only provisional Apple Wallet row."""
        retry: JevError | None = None
        logged: tuple[UUID, Proposal] | None = None
        applied: UUID | None = None
        with self._database.transaction() as session:
            claim = session.scalar(select(Claim).where(Claim.id == claim_id).with_for_update())
            if claim is None:
                raise CategorizerError("Claim was not found")
            if self._proposer is None or not self._claim_is_eligible(session, claim):
                return None
            subject = subject_from_claim(claim, timezone=self._reporting_timezone)
            try:
                proposal = self._propose_for_subject(session, subject)
            except JevError as error:
                proposal = proposal_from_jev_error(error, model=self._proposer_model())
                retry = error
            record_jev_attempt(
                session,
                claim_id=claim.id,
                subject=subject,
                proposal=proposal,
            )
            logged = (claim.id, proposal)
            if retry is None and proposal.action == "apply" and proposal.category_id is not None:
                self._apply_claim_category(session, claim, proposal)
                applied = proposal.category_id
        if logged is not None:
            _log_attempt(None, logged[1], claim_id=logged[0])
        if retry is not None:
            raise retry
        return applied

    def _propose_for_subject(self, session: Session, subject: JevSubject) -> Proposal:
        if self._proposer is None:
            raise JevError("jev proposer is not configured")
        categories = self._active_categories(session)
        if not categories:
            return Proposal(
                action="skip",
                category_id=None,
                category_name=None,
                confidence=Decimal("0"),
                model=self._proposer_model(),
            )
        return self._proposer.propose(subject, categories)

    @staticmethod
    def _needs_category(snapshot: TransactionSnapshot) -> bool:
        if not snapshot.category_splits:
            return True
        return any(split.category_name == _UNCATEGORIZED for split in snapshot.category_splits)

    @staticmethod
    def _pending_transaction_ids_in_session(session: Session) -> tuple[UUID, ...]:
        ids = session.scalars(
            select(PendingReview.subject_id)
            .where(
                PendingReview.subject_type == "transaction",
                PendingReview.condition_code == "categorization_needed",
                PendingReview.status == PendingReviewStatus.PENDING.value,
            )
            .order_by(PendingReview.created_at, PendingReview.id)
        ).all()
        return tuple(ids)

    @staticmethod
    def _pending_claim_ids_in_session(session: Session) -> tuple[UUID, ...]:
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
        spending_kinds = tuple(kind.value for kind in _SPENDING_KINDS)
        ids = session.scalars(
            select(Claim.id)
            .join(Extraction, Extraction.id == Claim.extraction_id)
            .join(latest_disposition, latest_disposition.c.claim_id == Claim.id)
            .where(
                Claim.claim_type == ClaimType.REAL_TIME.value,
                Extraction.adapter_key == APPLE_WALLET_ADAPTER_KEY,
                latest_disposition.c.disposition.in_(_ELIGIBLE_CLAIM_DISPOSITIONS),
                Claim.authorized_amount.is_not(None),
                Claim.authorized_amount != 0,
                Claim.authorized_currency.is_not(None),
                Claim.occurrence_at.is_not(None),
                or_(
                    Claim.transaction_kind_hint.is_(None),
                    Claim.transaction_kind_hint.in_(spending_kinds),
                ),
                ~Claim.id.in_(select(TransactionClaim.claim_id)),
                ~Claim.id.in_(select(ClaimCategory.claim_id)),
            )
            .order_by(Claim.created_at, Claim.id)
        ).all()
        return tuple(ids)

    def _claim_is_eligible(self, session: Session, claim: Claim) -> bool:
        if claim.claim_type != ClaimType.REAL_TIME.value:
            return False
        authorized_amount = claim.authorized_amount
        if (
            authorized_amount is None
            or authorized_amount == 0
            or claim.authorized_currency is None
            or claim.occurrence_at is None
            or not " ".join(claim.raw_description.split())
        ):
            return False
        kind = claim.transaction_kind_hint or TransactionKind.EXPENSE.value
        if kind not in {item.value for item in _SPENDING_KINDS}:
            return False
        adapter_key = session.scalar(
            select(Extraction.adapter_key).where(Extraction.id == claim.extraction_id)
        )
        if adapter_key != APPLE_WALLET_ADAPTER_KEY:
            return False
        linked = session.scalar(
            select(TransactionClaim.id).where(TransactionClaim.claim_id == claim.id)
        )
        if linked is not None:
            return False
        categorized = session.scalar(
            select(ClaimCategory.id).where(ClaimCategory.claim_id == claim.id)
        )
        if categorized is not None:
            return False
        disposition = session.scalar(
            select(ClaimDispositionEvent.disposition)
            .where(ClaimDispositionEvent.claim_id == claim.id)
            .order_by(
                ClaimDispositionEvent.occurred_at.desc(),
                ClaimDispositionEvent.id.desc(),
            )
            .limit(1)
        )
        return disposition in _ELIGIBLE_CLAIM_DISPOSITIONS

    def _apply_claim_category(self, session: Session, claim: Claim, proposal: Proposal) -> None:
        category_id = proposal.category_id
        authorized_amount = claim.authorized_amount
        authorized_currency = claim.authorized_currency
        if category_id is None or authorized_amount is None or authorized_currency is None:
            raise CategorizerError("Jev apply is missing a Category")
        category = session.get(Category, category_id)
        if (
            category is None
            or not category.active
            or (category.parent_id is None and category.name == _UNCATEGORIZED)
        ):
            raise CategorizerError("Category is not available for categorization")
        amount = abs(authorized_amount)
        if amount <= 0:
            raise CategorizerError("Claim Authorized Amount cannot be categorized")
        session.add(
            ClaimCategory(
                id=uuid7(),
                claim_id=claim.id,
                category_id=category.id,
                amount=amount,
                currency=authorized_currency,
            )
        )

    @staticmethod
    def _active_categories(session: Session) -> tuple[JevCategory, ...]:
        categories = session.scalars(
            select(Category).where(
                Category.active.is_(True),
                or_(Category.parent_id.is_not(None), Category.name != _UNCATEGORIZED),
            )
        ).all()
        return tuple(JevCategory(id=category.id, name=category.name) for category in categories)

    @staticmethod
    def _system_actor_id(session: Session) -> UUID:
        inserted = session.execute(
            insert(AuditActor)
            .values(
                id=uuid7(),
                kind=AuditActorKind.SYSTEM.value,
                label="jev",
                external_key="jev",
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
                AuditActor.external_key == "jev",
            )
        )
        if actor_id is None:
            raise CategorizerError("jev audit actor disappeared")
        return actor_id

    def _proposer_model(self) -> str:
        model = getattr(self._proposer, "model", None)
        return model if isinstance(model, str) and model.strip() else DEFAULT_MODEL


def _log_attempt(
    transaction_id: UUID | None,
    proposal: Proposal,
    *,
    claim_id: UUID | None = None,
) -> None:
    category = (
        proposal.category_name if proposal.action == "apply" and proposal.category_name else "skip"
    )
    logger.info(
        "jev attempt action=%s confidence=%s noul=%s category=%s transaction_id=%s claim_id=%s",
        proposal.action,
        _log_unit(proposal.confidence),
        _log_unit(proposal.noul),
        category,
        transaction_id if transaction_id is not None else "-",
        claim_id if claim_id is not None else "-",
    )


def _log_unit(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return format(value, "f")
