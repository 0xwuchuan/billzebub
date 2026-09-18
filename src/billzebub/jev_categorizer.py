"""Apply in-worker Jev Category proposals to spending Transactions.

This is the NAS-primary auto-categorizer. It runs inside the worker after
statement confirmation (including Real-time Claim matches) and on a daily
catch-up for leftover `categorization_needed` Reviews. Below the confidence
floor it leaves Uncategorized and the Review in place.
"""

from __future__ import annotations

import logging
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
from billzebub.persistence.models import AuditActor, AuditActorKind, Category, PendingReview
from billzebub.reviews import PendingReviewStatus

if TYPE_CHECKING:
    from billzebub.persistence.database import Database

logger = logging.getLogger(__name__)

CATEGORIZE_TRANSACTION_JOB = "categorize_transaction"
JEV_CATCH_UP_JOB = "jev_catch_up"
_UNCATEGORIZED = "Uncategorized"
_SPENDING_KINDS = frozenset({TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL})
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


class JevCategorizer:
    """Assign high-confidence Jev Categories through the owner categorization path."""

    def __init__(
        self,
        database: Database,
        proposer: Proposer | None,
        *,
        min_confidence: object | None = None,
    ) -> None:
        del min_confidence
        self._database = database
        self._proposer = proposer
        self._actions = OwnerTransactionActions(database)
        self._history = FinancialHistory(database)

    def pending_transaction_ids(self) -> tuple[UUID, ...]:
        with self._database.transaction() as session:
            return self._pending_transaction_ids_in_session(session)

    def enqueue_pending(self, queue: JobEnqueuer) -> int:
        ids = self.pending_transaction_ids()
        for transaction_id in ids:
            enqueue_transaction_categorization(queue, transaction_id)
        return len(ids)

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
                    proposal = self._propose_in_session(session, snapshot)
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

    def _propose_in_session(self, session: Session, snapshot: TransactionSnapshot) -> Proposal:
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
        return self._proposer.propose(subject_from_snapshot(snapshot), categories)

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


def _log_attempt(transaction_id: UUID, proposal: Proposal) -> None:
    category = (
        proposal.category_name if proposal.action == "apply" and proposal.category_name else "skip"
    )
    logger.info(
        "jev attempt action=%s confidence=%s noul=%s category=%s transaction_id=%s",
        proposal.action,
        _log_unit(proposal.confidence),
        _log_unit(proposal.noul),
        category,
        transaction_id,
    )


def _log_unit(value: Decimal | None) -> str:
    if value is None:
        return "-"
    return format(value, "f")
