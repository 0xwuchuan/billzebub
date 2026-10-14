"""Apply in-worker Jev Category proposals to spending Transactions and Claims.

This is the NAS-primary auto-categorizer. It runs inside the worker after
statement confirmation (including Real-time Claim matches), after a new
claim-only provisional Apple Wallet Real-time Claim, and on a daily catch-up
for leftovers. Below the confidence floor it leaves the row uncategorized.
"""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol
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
from billzebub.jev import (
    DEFAULT_MODEL,
    SKIP_EMPTY_CATALOG,
    JevCategory,
    JevError,
    JevSubject,
    Proposal,
    Proposer,
)
from billzebub.jev_attempts import proposal_from_jev_error, record_jev_attempt
from billzebub.jev_context import similar_confirmed
from billzebub.merchant_memory import (
    MEMORY_REASON,
    is_memory_excluded,
    refresh_merchant_memory,
    rule_for_counterparty,
)
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
    DurableJob,
    Extraction,
    JobStatus,
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
CATEGORIZE_MAX_ATTEMPTS = 8
JEV_RETRY_BASE_SECONDS = 30
JEV_RETRY_CAP = timedelta(minutes=30)
_CATEGORIZE_KINDS = (CATEGORIZE_TRANSACTION_JOB, CATEGORIZE_CLAIM_JOB)
_JEV_UNAVAILABLE = "jev_unavailable"


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


def jev_retry_delay(
    attempt: int,
    *,
    random_unit: Callable[[], float] | None = None,
) -> timedelta:
    """Equal-jitter exponential delay after a failed categorize attempt.

    ``attempt`` is 1-based. The full delay is ``min(30 min, 30s * 2**(attempt-1))``.
    Jitter keeps half of that and adds ``U(0, 1)`` times the other half, so a
    timeout or ``jev_unavailable`` waits somewhere in ``[full/2, full]``.
    """
    exponent = max(attempt, 1) - 1
    full_seconds = min(JEV_RETRY_CAP.total_seconds(), JEV_RETRY_BASE_SECONDS * (2**exponent))
    unit = random.random() if random_unit is None else random_unit()
    if unit < 0:
        unit = 0.0
    elif unit > 1:
        unit = 1.0
    delay_seconds = full_seconds * 0.5 + unit * full_seconds * 0.5
    return timedelta(seconds=delay_seconds)


def enqueue_transaction_categorization(queue: JobEnqueuer, transaction_id: UUID) -> None:
    queue.enqueue(
        CATEGORIZE_TRANSACTION_JOB,
        {"transaction_id": str(transaction_id)},
        dedupe_key=str(transaction_id),
        max_attempts=CATEGORIZE_MAX_ATTEMPTS,
    )


def enqueue_claim_categorization(queue: JobEnqueuer, claim_id: UUID) -> None:
    queue.enqueue(
        CATEGORIZE_CLAIM_JOB,
        {"claim_id": str(claim_id)},
        dedupe_key=str(claim_id),
        max_attempts=CATEGORIZE_MAX_ATTEMPTS,
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


@dataclass(frozen=True, slots=True)
class JevRequeueReport:
    """Counts printed by ``billzebub jev requeue-failed`` and the nightly catch-up."""

    failed_before: int
    active_before: int
    would_requeue: int
    failed_after: int
    active_after: int
    requeued: int
    applied: bool


def format_jev_requeue(report: JevRequeueReport) -> str:
    lines = [f"before failed={report.failed_before} active={report.active_before}"]
    if not report.applied:
        lines.append(f"would_requeue={report.would_requeue}")
    lines.append(
        f"after failed={report.failed_after} active={report.active_after} "
        f"requeued={report.requeued}"
    )
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class _FailedSubject:
    kind: str
    dedupe_key: str
    payload: dict[str, Any]


def requeue_failed_categorizations(
    database: Database,
    queue: JobEnqueuer,
    *,
    apply: bool,
) -> JevRequeueReport:
    """Requeue failed categorize jobs whose last error is ``jev_unavailable``.

    Dry-run counts only. Apply enqueues a new job with the same dedupe key, so
    a subject that is already queued or running is left alone.
    """
    with database.transaction() as session:
        failed_rows = _failed_unavailable_jobs(session)
        subjects = _failed_subjects(failed_rows)
        active = _active_subject_keys(session, subjects)
        failed_before = len(failed_rows)
        active_before = len(active)
        pending = [
            subject for subject in subjects if (subject.kind, subject.dedupe_key) not in active
        ]
    requeued = 0
    if apply:
        for subject in pending:
            enqueued = queue.enqueue(
                subject.kind,
                subject.payload,
                dedupe_key=subject.dedupe_key,
                max_attempts=CATEGORIZE_MAX_ATTEMPTS,
            )
            if not getattr(enqueued, "duplicate", False):
                requeued += 1
        with database.transaction() as session:
            failed_after_rows = _failed_unavailable_jobs(session)
            failed_after = len(failed_after_rows)
            active_after = len(_active_subject_keys(session, _failed_subjects(failed_after_rows)))
    else:
        failed_after = failed_before
        active_after = active_before
    return JevRequeueReport(
        failed_before=failed_before,
        active_before=active_before,
        would_requeue=len(pending),
        failed_after=failed_after,
        active_after=active_after,
        requeued=requeued,
        applied=apply,
    )


def _failed_unavailable_jobs(session: Any) -> list[DurableJob]:
    return list(
        session.scalars(
            select(DurableJob).where(
                DurableJob.kind.in_(_CATEGORIZE_KINDS),
                DurableJob.status == JobStatus.FAILED,
                DurableJob.last_error_code == _JEV_UNAVAILABLE,
            )
        ).all()
    )


def _failed_subjects(rows: list[DurableJob]) -> list[_FailedSubject]:
    subjects: list[_FailedSubject] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        dedupe_key = _categorize_dedupe_key(row)
        if dedupe_key is None:
            continue
        identity = (row.kind, dedupe_key)
        if identity in seen:
            continue
        seen.add(identity)
        subjects.append(
            _FailedSubject(kind=row.kind, dedupe_key=dedupe_key, payload=dict(row.payload))
        )
    return subjects


def _categorize_dedupe_key(row: DurableJob) -> str | None:
    if row.dedupe_key:
        return row.dedupe_key
    payload_key = "transaction_id" if row.kind == CATEGORIZE_TRANSACTION_JOB else "claim_id"
    value = row.payload.get(payload_key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _active_subject_keys(session: Any, subjects: list[_FailedSubject]) -> set[tuple[str, str]]:
    if not subjects:
        return set()
    wanted = {(subject.kind, subject.dedupe_key) for subject in subjects}
    rows = session.scalars(
        select(DurableJob).where(
            DurableJob.kind.in_({kind for kind, _dedupe in wanted}),
            DurableJob.dedupe_key.in_({dedupe for _kind, dedupe in wanted}),
            DurableJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
    ).all()
    return {
        (row.kind, row.dedupe_key)
        for row in rows
        if row.dedupe_key is not None and (row.kind, row.dedupe_key) in wanted
    }


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
        requeued = requeue_failed_categorizations(self._database, queue, apply=True).requeued
        return len(transaction_ids) + len(claim_ids) + requeued

    def categorize_transaction(self, transaction_id: UUID) -> TransactionSnapshot | None:
        retry: JevError | None = None
        logged: tuple[UUID, Proposal] | None = None
        updated: TransactionSnapshot | None = None
        try:
            with self._database.transaction() as session:
                snapshot = self._history.current_in_session(session, transaction_id)
                if snapshot.kind not in _SPENDING_KINDS or not self._needs_category(snapshot):
                    return None
                remembered = self._apply_merchant_memory(session, snapshot)
                if remembered is not None:
                    return remembered
                if self._proposer is None:
                    return None
                subject = subject_from_snapshot(snapshot)
                subject = replace(
                    subject,
                    similar_confirmed_transactions=similar_confirmed(
                        session,
                        subject,
                        exclude_transaction_id=snapshot.id,
                    ),
                )
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
            if not self._claim_is_eligible(session, claim):
                return None
            subject = subject_from_claim(claim, timezone=self._reporting_timezone)
            remembered = rule_for_counterparty(session, subject.counterparty)
            if remembered is not None:
                self._apply_claim_category(
                    session,
                    claim,
                    Proposal(
                        action="apply",
                        category_id=remembered.category_id,
                        category_name=remembered.category_name,
                        confidence=Decimal("1"),
                        model=self._proposer_model(),
                    ),
                )
                return remembered.category_id
            if self._proposer is None:
                return None
            subject = replace(
                subject,
                similar_confirmed_transactions=similar_confirmed(session, subject),
            )
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
                if proposal.confidence >= Decimal("0.9"):
                    refresh_merchant_memory(session, subject.counterparty)
        if logged is not None:
            _log_attempt(None, logged[1], claim_id=logged[0])
        if retry is not None:
            raise retry
        return applied

    def _apply_merchant_memory(
        self,
        session: Session,
        snapshot: TransactionSnapshot,
    ) -> TransactionSnapshot | None:
        if is_memory_excluded(session, snapshot.id):
            return None
        rule = rule_for_counterparty(session, snapshot.counterparty)
        if rule is None:
            return None
        try:
            return self._actions.categorize_in_session(
                session,
                OwnerCategorizationCommand(
                    transaction_id=snapshot.id,
                    expected_version=snapshot.version,
                    category_id=rule.category_id,
                    actor_id=self._system_actor_id(session),
                    reason=MEMORY_REASON,
                ),
            )
        except OwnerTransactionActionError as error:
            raise CategorizerError(str(error)) from error

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
                skip_reason=SKIP_EMPTY_CATALOG,
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
        categories = session.scalars(select(Category).where(Category.active.is_(True))).all()
        by_id = {category.id: category for category in categories}
        missing_parent_ids = [
            category.parent_id
            for category in categories
            if category.parent_id is not None and category.parent_id not in by_id
        ]
        if missing_parent_ids:
            parents = session.scalars(
                select(Category).where(Category.id.in_(missing_parent_ids))
            ).all()
            for missing_parent in parents:
                by_id[missing_parent.id] = missing_parent
        loaded: list[JevCategory] = []
        for category in categories:
            if category.parent_id is None and category.name == _UNCATEGORIZED:
                continue
            parent = by_id.get(category.parent_id) if category.parent_id is not None else None
            loaded.append(
                JevCategory(
                    id=category.id,
                    name=category.name,
                    parent_id=category.parent_id,
                    parent_name=parent.name if parent is not None else None,
                    description=category.description,
                )
            )
        return tuple(loaded)

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
