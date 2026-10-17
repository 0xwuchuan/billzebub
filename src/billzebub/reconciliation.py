"""Deterministically reconcile Real-time and Statement Claims."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.claims import ClaimBook, ClaimDisposition, ClaimType
from billzebub.financial_history import Confirmation, FinancialHistory, TransactionKind
from billzebub.persistence.models import (
    Claim,
    ClaimDispositionEvent,
    Extraction,
    FinancialAccount,
    PendingReview,
    ReconciledClaimPair,
    ReferenceExchangeRate,
    RejectedClaimPair,
    TransactionClaim,
)
from billzebub.reconciliation_review import enrich_ambiguous_match_contexts
from billzebub.reviews import (
    PendingReviewRecord,
    ReviewCondition,
    ReviewDecision,
    ReviewError,
    ReviewInbox,
    ReviewSeverity,
)
from billzebub.statement_adapters.uob_ref_no import strip_uob_statement_ref_no

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


_AUTO_CONFIRM_SCORE = 80
_AUTO_CONFIRM_MARGIN = 15
_REVIEW_SCORE = 60
_DATE_WINDOW_DAYS = 7
_UNCONFIRMED_AFTER = timedelta(days=14)
_AMBIGUOUS_CONDITION = "reconciliation_ambiguous"
_UNCONFIRMED_CONDITION = "real_time_unconfirmed"
_REJECT_ALL = "reject_all"
_ACKNOWLEDGE = "acknowledge"
_TOKEN_PATTERN = re.compile(r"[a-z]+")
_COUNTERPARTY_NOISE = frozenset(
    {
        "card",
        "credit",
        "debit",
        "payment",
        "posted",
        "purchase",
        "sg",
        "sgd",
        "singapore",
        "transaction",
        "visa",
    }
)


class ReconciliationError(ValueError):
    """Reconciliation policy rejected a requested operation."""


@dataclass(frozen=True, slots=True)
class ReconciliationCandidate:
    real_time_claim_id: UUID
    statement_claim_id: UUID
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationConfirmation:
    transaction_id: UUID
    statement_claim_id: UUID
    real_time_claim_id: UUID | None
    source: str


@dataclass(frozen=True, slots=True)
class ReconciliationRun:
    financial_account_id: UUID
    candidates: tuple[ReconciliationCandidate, ...]
    confirmations: tuple[ReconciliationConfirmation, ...]
    ambiguous_review_ids: tuple[UUID, ...]
    unconfirmed_claim_ids: tuple[UUID, ...]
    no_match_real_time_claim_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationDecisionOutcome:
    review: PendingReviewRecord
    confirmation: ReconciliationConfirmation | None
    follow_up: ReconciliationRun


class Reconciliation:
    """Own matching policy, review conditions, and reconciliation history."""

    def __init__(
        self,
        database: Database,
        *,
        reporting_timezone: str = "Asia/Singapore",
    ) -> None:
        self._database = database
        self._history = FinancialHistory(database, reporting_timezone=reporting_timezone)
        self._reporting_timezone = ZoneInfo(reporting_timezone)

    def reconcile_account(
        self,
        financial_account_id: UUID,
        *,
        as_of: datetime | None = None,
    ) -> ReconciliationRun:
        now = self._require_instant(as_of or datetime.now(UTC))
        with self._database.transaction() as session:
            account = session.scalar(
                select(FinancialAccount)
                .where(FinancialAccount.id == financial_account_id)
                .with_for_update()
            )
            if account is None:
                raise ReconciliationError("Financial Account was not found")
            return self._reconcile_account_in_session(session, account, now)

    def decide(
        self, command: ReviewDecision, *, as_of: datetime | None = None
    ) -> ReconciliationDecisionOutcome:
        now = self._require_instant(as_of or datetime.now(UTC))
        with self._database.transaction() as session:
            review = session.scalar(
                select(PendingReview).where(PendingReview.id == command.review_id).with_for_update()
            )
            if review is None:
                raise ReconciliationError("Pending Review was not found")
            if review.subject_type != "claim" or review.condition_code not in {
                _AMBIGUOUS_CONDITION,
                _UNCONFIRMED_CONDITION,
            }:
                raise ReconciliationError("Pending Review is not a Reconciliation decision")
            self._validate_decision(review, command)

            account_id = self._claim_account_id(session, review.subject_id)
            account = session.scalar(
                select(FinancialAccount).where(FinancialAccount.id == account_id).with_for_update()
            )
            if account is None:
                raise ReconciliationError("Financial Account was not found")

            confirmation: ReconciliationConfirmation | None = None
            if review.condition_code == _AMBIGUOUS_CONDITION:
                confirmation = self._decide_ambiguous_pair(session, review, command)
            elif command.choice != _ACKNOWLEDGE:
                raise ReviewError("decision is not permitted for this Pending Review")

            resolved = ReviewInbox.decide_in_session(session, command)
            follow_up = self._reconcile_account_in_session(session, account, now)
            enriched = enrich_ambiguous_match_contexts(
                session,
                (review,),
                reporting_timezone=self._reporting_timezone,
            ).get(review.id)
            if enriched is not None:
                resolved = replace(resolved, context=enriched)
            return ReconciliationDecisionOutcome(
                review=resolved,
                confirmation=confirmation,
                follow_up=follow_up,
            )

    def _reconcile_account_in_session(
        self,
        session: Session,
        account: FinancialAccount,
        now: datetime,
    ) -> ReconciliationRun:
        claims = session.scalars(
            select(Claim)
            .where(Claim.financial_account_id == account.id)
            .order_by(Claim.created_at, Claim.id)
        ).all()
        dispositions = self._current_dispositions(session, tuple(claim.id for claim in claims))
        claimed_ids = set(
            session.scalars(
                select(TransactionClaim.claim_id)
                .join(Claim, Claim.id == TransactionClaim.claim_id)
                .where(Claim.financial_account_id == account.id)
            ).all()
        )
        rejected_pairs: set[tuple[UUID, UUID]] = {
            (real_time_claim_id, statement_claim_id)
            for real_time_claim_id, statement_claim_id in session.execute(
                select(
                    RejectedClaimPair.real_time_claim_id,
                    RejectedClaimPair.statement_claim_id,
                )
                .join(Claim, Claim.id == RejectedClaimPair.real_time_claim_id)
                .where(Claim.financial_account_id == account.id)
            ).all()
        }

        statement_claims = tuple(
            claim
            for claim in claims
            if claim.claim_type == ClaimType.STATEMENT.value
            and claim.id not in claimed_ids
            and dispositions.get(claim.id) is ClaimDisposition.PROVISIONAL
        )
        real_time_claims = tuple(
            claim
            for claim in claims
            if claim.claim_type == ClaimType.REAL_TIME.value
            and claim.id not in claimed_ids
            and dispositions.get(claim.id)
            in {ClaimDisposition.PROVISIONAL, ClaimDisposition.UNCONFIRMED}
        )
        candidates = tuple(
            candidate
            for statement in statement_claims
            for real_time in real_time_claims
            if (candidate := self._score(session, real_time, statement, rejected_pairs)) is not None
        )
        by_statement = self._rank_by(candidates, "statement")
        by_real_time = self._rank_by(candidates, "real_time")
        automatic = tuple(
            candidate
            for candidate in candidates
            if self._is_automatic(candidate, by_statement, by_real_time)
        )

        confirmations: list[ReconciliationConfirmation] = []
        consumed_statement_ids: set[UUID] = set()
        consumed_real_time_ids: set[UUID] = set()
        for candidate in automatic:
            snapshot = self._history.confirm_in_session(
                session,
                self._confirmation_for(
                    candidate.statement_claim_id, candidate.real_time_claim_id, claims
                ),
            )
            self._record_pair(
                session,
                candidate,
                transaction_id=snapshot.id,
                source="automatic",
            )
            confirmations.append(
                ReconciliationConfirmation(
                    transaction_id=snapshot.id,
                    statement_claim_id=candidate.statement_claim_id,
                    real_time_claim_id=candidate.real_time_claim_id,
                    source="automatic",
                )
            )
            consumed_statement_ids.add(candidate.statement_claim_id)
            consumed_real_time_ids.add(candidate.real_time_claim_id)

        ambiguous_ids_by_real_time: dict[UUID, tuple[ReconciliationCandidate, ...]] = {}
        held_statement_ids: set[UUID] = set()
        for real_time in real_time_claims:
            if real_time.id in consumed_real_time_ids:
                continue
            ranked = tuple(
                candidate
                for candidate in by_real_time.get(real_time.id, ())
                if candidate.statement_claim_id not in consumed_statement_ids
                and candidate.score >= _REVIEW_SCORE
            )
            if ranked:
                ambiguous_ids_by_real_time[real_time.id] = ranked
                held_statement_ids.update(candidate.statement_claim_id for candidate in ranked)

        ambiguous_review_ids: list[UUID] = []
        for real_time in real_time_claims:
            ranked = ambiguous_ids_by_real_time.get(real_time.id, ())
            review = ReviewInbox.synchronize_in_session(
                session,
                self._ambiguous_condition(real_time.id, ranked),
                active=bool(ranked),
            )
            if review is not None and review.status.value == "pending":
                ambiguous_review_ids.append(review.id)

        for statement in statement_claims:
            if statement.id in consumed_statement_ids or statement.id in held_statement_ids:
                continue
            snapshot = self._history.confirm_in_session(
                session,
                self._confirmation_for(statement.id, None, claims),
            )
            confirmations.append(
                ReconciliationConfirmation(
                    transaction_id=snapshot.id,
                    statement_claim_id=statement.id,
                    real_time_claim_id=None,
                    source="statement_only",
                )
            )
            consumed_statement_ids.add(statement.id)

        history_end = self._statement_history_end(session, account.id)
        unconfirmed_claim_ids: list[UUID] = []
        no_match_real_time_claim_ids: list[UUID] = []
        for real_time in real_time_claims:
            if real_time.id in consumed_real_time_ids or real_time.id in ambiguous_ids_by_real_time:
                ReviewInbox.synchronize_in_session(
                    session,
                    self._unconfirmed_condition(real_time.id, history_end),
                    active=False,
                )
                continue

            disposition = dispositions[real_time.id]
            if self._horizon_elapsed(real_time, history_end):
                if disposition is ClaimDisposition.PROVISIONAL:
                    ClaimBook.mark_unconfirmed_in_session(
                        session,
                        real_time.id,
                        reason_code="confirmation_horizon_elapsed",
                    )
                unconfirmed_claim_ids.append(real_time.id)
                ReviewInbox.synchronize_in_session(
                    session,
                    self._unconfirmed_condition(real_time.id, history_end),
                    active=True,
                )
            else:
                no_match_real_time_claim_ids.append(real_time.id)
                ReviewInbox.synchronize_in_session(
                    session,
                    self._unconfirmed_condition(real_time.id, history_end),
                    active=False,
                )

        return ReconciliationRun(
            financial_account_id=account.id,
            candidates=tuple(sorted(candidates, key=self._candidate_sort_key)),
            confirmations=tuple(confirmations),
            ambiguous_review_ids=tuple(ambiguous_review_ids),
            unconfirmed_claim_ids=tuple(unconfirmed_claim_ids),
            no_match_real_time_claim_ids=tuple(no_match_real_time_claim_ids),
        )

    def _decide_ambiguous_pair(
        self,
        session: Session,
        review: PendingReview,
        command: ReviewDecision,
    ) -> ReconciliationConfirmation | None:
        candidates = self._review_candidates(review)
        if command.choice == _REJECT_ALL:
            for review_candidate in candidates:
                session.execute(
                    insert(RejectedClaimPair)
                    .values(
                        id=uuid7(),
                        real_time_claim_id=review.subject_id,
                        statement_claim_id=review_candidate.statement_claim_id,
                        reason_code="review_reject_all",
                        review_id=review.id,
                        actor_id=command.actor_id,
                    )
                    .on_conflict_do_nothing(
                        index_elements=(
                            RejectedClaimPair.real_time_claim_id,
                            RejectedClaimPair.statement_claim_id,
                        )
                    )
                )
            return None

        statement_id = self._statement_choice(command.choice)
        candidate = next(
            (entry for entry in candidates if entry.statement_claim_id == statement_id),
            None,
        )
        if candidate is None:
            raise ReviewError("decision is not permitted for this Pending Review")
        statement = session.scalar(select(Claim).where(Claim.id == statement_id).with_for_update())
        real_time = session.scalar(
            select(Claim).where(Claim.id == review.subject_id).with_for_update()
        )
        if statement is None or real_time is None:
            raise ReconciliationError("Reconciliation Claim was not found")
        if statement.financial_account_id != real_time.financial_account_id:
            raise ReconciliationError("Reconciliation Claims must share a Financial Account")
        if self._claim_is_linked(session, statement.id) or self._claim_is_linked(
            session, real_time.id
        ):
            raise ReconciliationError("Reconciliation Claim is no longer eligible")

        snapshot = self._history.confirm_in_session(
            session,
            self._confirmation_for(statement.id, real_time.id, (statement, real_time)),
        )
        self._record_pair(
            session,
            candidate,
            transaction_id=snapshot.id,
            source="review",
            review_id=review.id,
            actor_id=command.actor_id,
        )
        return ReconciliationConfirmation(
            transaction_id=snapshot.id,
            statement_claim_id=statement.id,
            real_time_claim_id=real_time.id,
            source="review",
        )

    @staticmethod
    def _rank_by(
        candidates: tuple[ReconciliationCandidate, ...],
        side: str,
    ) -> dict[UUID, tuple[ReconciliationCandidate, ...]]:
        grouped: dict[UUID, list[ReconciliationCandidate]] = defaultdict(list)
        for candidate in candidates:
            claim_id = (
                candidate.statement_claim_id
                if side == "statement"
                else candidate.real_time_claim_id
            )
            grouped[claim_id].append(candidate)
        return {
            claim_id: tuple(sorted(entries, key=Reconciliation._candidate_sort_key))
            for claim_id, entries in grouped.items()
        }

    @staticmethod
    def _candidate_sort_key(candidate: ReconciliationCandidate) -> tuple[int, str, str]:
        return (
            -candidate.score,
            str(candidate.statement_claim_id),
            str(candidate.real_time_claim_id),
        )

    @staticmethod
    def _is_automatic(
        candidate: ReconciliationCandidate,
        by_statement: dict[UUID, tuple[ReconciliationCandidate, ...]],
        by_real_time: dict[UUID, tuple[ReconciliationCandidate, ...]],
    ) -> bool:
        statement_ranked = by_statement[candidate.statement_claim_id]
        real_time_ranked = by_real_time[candidate.real_time_claim_id]
        return (
            statement_ranked[0] == candidate
            and real_time_ranked[0] == candidate
            and candidate.score >= _AUTO_CONFIRM_SCORE
            and Reconciliation._margin(statement_ranked) >= _AUTO_CONFIRM_MARGIN
            and Reconciliation._margin(real_time_ranked) >= _AUTO_CONFIRM_MARGIN
        )

    @staticmethod
    def _margin(candidates: tuple[ReconciliationCandidate, ...]) -> int:
        if len(candidates) < 2:
            return 100
        return candidates[0].score - candidates[1].score

    def _score(
        self,
        session: Session,
        real_time: Claim,
        statement: Claim,
        rejected_pairs: set[tuple[UUID, UUID]],
    ) -> ReconciliationCandidate | None:
        if (real_time.id, statement.id) in rejected_pairs:
            return None
        if real_time.financial_account_id != statement.financial_account_id:
            return None
        if real_time.authorized_amount is None or real_time.authorized_currency is None:
            return None
        if statement.posted_amount is None or statement.posted_currency is None:
            return None
        if real_time.occurrence_at is None:
            return None

        activity_date = real_time.occurrence_at.astimezone(self._reporting_timezone).date()
        statement_date = statement.provider_transaction_date or statement.posting_date
        if statement_date is None:
            return None
        date_delta = abs((statement_date - activity_date).days)
        if date_delta > _DATE_WINDOW_DAYS:
            return None
        if (real_time.authorized_amount > 0) != (statement.posted_amount > 0):
            return None

        amount_score, amount_reason = self._amount_compatibility(
            session, real_time, statement, statement_date
        )
        if amount_score is None:
            return None
        date_score, date_reason = self._date_compatibility(date_delta)
        counterparty_score, counterparty_reason = self._counterparty_compatibility(
            real_time.raw_description,
            statement.raw_description,
        )
        return ReconciliationCandidate(
            real_time_claim_id=real_time.id,
            statement_claim_id=statement.id,
            score=amount_score + date_score + counterparty_score,
            reasons=(
                "same_financial_account",
                amount_reason,
                date_reason,
                counterparty_reason,
            ),
        )

    def _amount_compatibility(
        self,
        session: Session,
        real_time: Claim,
        statement: Claim,
        statement_date: date,
    ) -> tuple[int | None, str]:
        assert real_time.authorized_amount is not None
        assert real_time.authorized_currency is not None
        assert statement.posted_amount is not None
        assert statement.posted_currency is not None
        if real_time.authorized_currency == statement.posted_currency:
            if real_time.authorized_amount == statement.posted_amount:
                return 50, "amount_exact_posted"
            return None, "amount_mismatch"
        if (
            statement.original_amount is not None
            and statement.original_currency == real_time.authorized_currency
            and statement.original_amount == real_time.authorized_amount
        ):
            return 50, "amount_exact_original"

        reference_rate = self._reference_rate(
            session,
            statement_date,
            real_time.authorized_currency,
            statement.posted_currency,
        )
        if reference_rate is None:
            return None, "amount_fx_reference_missing"
        observed_rate = abs(statement.posted_amount / real_time.authorized_amount)
        relative_difference = abs(observed_rate - reference_rate) / reference_rate
        if relative_difference > Decimal("0.10"):
            return None, "amount_fx_outside_reference_band"
        return 35, "amount_fx_within_reference_band"

    @staticmethod
    def _reference_rate(
        session: Session,
        rate_date: date,
        base_currency: str,
        quote_currency: str,
    ) -> Decimal | None:
        direct = session.scalar(
            select(ReferenceExchangeRate.rate).where(
                ReferenceExchangeRate.rate_date == rate_date,
                ReferenceExchangeRate.base_currency == base_currency,
                ReferenceExchangeRate.quote_currency == quote_currency,
            )
        )
        if direct is not None:
            return direct
        inverse = session.scalar(
            select(ReferenceExchangeRate.rate).where(
                ReferenceExchangeRate.rate_date == rate_date,
                ReferenceExchangeRate.base_currency == quote_currency,
                ReferenceExchangeRate.quote_currency == base_currency,
            )
        )
        return Decimal(1) / inverse if inverse is not None else None

    @staticmethod
    def _date_compatibility(delta: int) -> tuple[int, str]:
        if delta == 0:
            return 25, "activity_date_exact"
        if delta == 1:
            return 20, "activity_date_within_one_day"
        if delta == 2:
            return 15, "activity_date_within_two_days"
        if delta == 3:
            return 10, "activity_date_within_three_days"
        return 5, "activity_date_within_window"

    @staticmethod
    def _counterparty_compatibility(
        real_time_description: str, statement_description: str
    ) -> tuple[int, str]:
        real_time_tokens = Reconciliation._counterparty_tokens(real_time_description)
        statement_tokens = Reconciliation._counterparty_tokens(statement_description)
        if not real_time_tokens or not statement_tokens:
            return 0, "counterparty_unavailable"
        if real_time_tokens == statement_tokens:
            return 25, "counterparty_exact"
        overlap = len(real_time_tokens & statement_tokens) / len(
            real_time_tokens | statement_tokens
        )
        if overlap >= 0.75:
            return 20, "counterparty_high_overlap"
        if overlap >= 0.5:
            return 15, "counterparty_partial_overlap"
        if overlap >= 0.25:
            return 8, "counterparty_low_overlap"
        return 0, "counterparty_no_overlap"

    @staticmethod
    def _counterparty_tokens(value: str) -> frozenset[str]:
        normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        return frozenset(
            token
            for token in _TOKEN_PATTERN.findall(normalized.casefold())
            if len(token) > 1 and token not in _COUNTERPARTY_NOISE
        )

    def _statement_history_end(self, session: Session, financial_account_id: UUID) -> date | None:
        periods = session.scalars(
            select(Extraction.period_end)
            .where(
                Extraction.financial_account_id == financial_account_id,
                Extraction.status == "accepted",
                Extraction.period_end.is_not(None),
            )
            .order_by(Extraction.period_end.desc())
            .limit(1)
        ).all()
        return periods[0] if periods else None

    def _horizon_elapsed(self, real_time: Claim, history_end: date | None) -> bool:
        if history_end is None or real_time.occurrence_at is None:
            return False
        occurrence_date = real_time.occurrence_at.astimezone(self._reporting_timezone).date()
        return history_end >= occurrence_date + _UNCONFIRMED_AFTER

    @staticmethod
    def _current_dispositions(
        session: Session,
        claim_ids: tuple[UUID, ...],
    ) -> dict[UUID, ClaimDisposition]:
        if not claim_ids:
            return {}
        events = session.scalars(
            select(ClaimDispositionEvent)
            .where(ClaimDispositionEvent.claim_id.in_(claim_ids))
            .order_by(
                ClaimDispositionEvent.claim_id,
                ClaimDispositionEvent.occurred_at,
                ClaimDispositionEvent.id,
            )
        ).all()
        return {event.claim_id: ClaimDisposition(event.disposition) for event in events}

    @staticmethod
    def _claim_is_linked(session: Session, claim_id: UUID) -> bool:
        return (
            session.scalar(select(TransactionClaim.id).where(TransactionClaim.claim_id == claim_id))
            is not None
        )

    @staticmethod
    def _claim_account_id(session: Session, claim_id: UUID) -> UUID:
        account_id = session.scalar(select(Claim.financial_account_id).where(Claim.id == claim_id))
        if account_id is None:
            raise ReconciliationError("Reconciliation Claim was not found")
        return account_id

    @staticmethod
    def _confirmation_for(
        statement_claim_id: UUID,
        real_time_claim_id: UUID | None,
        claims: Sequence[Claim],
    ) -> Confirmation:
        statement = next(claim for claim in claims if claim.id == statement_claim_id)
        kind = Reconciliation._statement_kind(statement)
        normalized = strip_uob_statement_ref_no(" ".join(statement.raw_description.split()))
        counterparty = normalized[:300]
        return Confirmation(
            statement_claim_id=statement_claim_id,
            real_time_claim_id=real_time_claim_id,
            kind=kind,
            counterparty=counterparty,
        )

    @staticmethod
    def _statement_kind(statement: Claim) -> TransactionKind:
        if statement.posted_amount is None:
            raise ReconciliationError("Statement Claim has no Posted Amount")
        if statement.transaction_kind_hint is not None:
            try:
                hinted = TransactionKind(statement.transaction_kind_hint)
            except ValueError:
                hinted = None
            if hinted is TransactionKind.TRANSFER:
                return hinted
            if hinted in {TransactionKind.EXPENSE, TransactionKind.CASH_WITHDRAWAL}:
                if statement.posted_amount < 0:
                    return hinted
            elif hinted is not None and statement.posted_amount > 0:
                return hinted
        return TransactionKind.EXPENSE if statement.posted_amount < 0 else TransactionKind.INCOME

    @staticmethod
    def _ambiguous_condition(
        real_time_claim_id: UUID,
        candidates: tuple[ReconciliationCandidate, ...],
    ) -> ReviewCondition:
        choices = (
            *(f"match:{candidate.statement_claim_id}" for candidate in candidates),
            _REJECT_ALL,
        )
        return ReviewCondition(
            subject_type="claim",
            subject_id=real_time_claim_id,
            condition_code=_AMBIGUOUS_CONDITION,
            severity=ReviewSeverity.BLOCKING,
            allowed_decisions=choices,
            context={
                "candidate_count": len(candidates),
                "candidates": [
                    {
                        "statement_claim_id": str(candidate.statement_claim_id),
                        "score": candidate.score,
                        "reasons": list(candidate.reasons),
                    }
                    for candidate in candidates
                ],
            },
        )

    @staticmethod
    def _unconfirmed_condition(
        real_time_claim_id: UUID,
        history_end: date | None,
    ) -> ReviewCondition:
        return ReviewCondition(
            subject_type="claim",
            subject_id=real_time_claim_id,
            condition_code=_UNCONFIRMED_CONDITION,
            severity=ReviewSeverity.ATTENTION,
            allowed_decisions=(_ACKNOWLEDGE,),
            context={
                "statement_history_end": history_end.isoformat()
                if history_end is not None
                else None,
            },
        )

    @staticmethod
    def _review_candidates(review: PendingReview) -> tuple[ReconciliationCandidate, ...]:
        raw_candidates: Any = review.context.get("candidates")
        if not isinstance(raw_candidates, list):
            raise ReconciliationError("Reconciliation Pending Review is malformed")
        candidates: list[ReconciliationCandidate] = []
        for raw in raw_candidates:
            if not isinstance(raw, dict):
                raise ReconciliationError("Reconciliation Pending Review is malformed")
            try:
                statement_id = UUID(str(raw["statement_claim_id"]))
                score = int(raw["score"])
                reasons = tuple(str(reason) for reason in raw["reasons"])
            except (KeyError, TypeError, ValueError) as error:
                raise ReconciliationError("Reconciliation Pending Review is malformed") from error
            if not 0 <= score <= 100 or not reasons:
                raise ReconciliationError("Reconciliation Pending Review is malformed")
            candidates.append(
                ReconciliationCandidate(
                    real_time_claim_id=review.subject_id,
                    statement_claim_id=statement_id,
                    score=score,
                    reasons=reasons,
                )
            )
        if not candidates:
            raise ReconciliationError("Reconciliation Pending Review is malformed")
        return tuple(candidates)

    @staticmethod
    def _validate_decision(review: PendingReview, command: ReviewDecision) -> None:
        if review.status != "pending":
            raise ReviewError("Pending Review is no longer Pending")
        if command.expected_version != review.version:
            raise ReviewError("Pending Review version is stale")
        if command.choice not in review.allowed_decisions:
            raise ReviewError("decision is not permitted for this Pending Review")

    @staticmethod
    def _statement_choice(choice: str) -> UUID:
        prefix = "match:"
        if not choice.startswith(prefix):
            raise ReviewError("decision is not permitted for this Pending Review")
        try:
            return UUID(choice.removeprefix(prefix))
        except ValueError as error:
            raise ReviewError("decision is not permitted for this Pending Review") from error

    @staticmethod
    def _record_pair(
        session: Session,
        candidate: ReconciliationCandidate,
        *,
        transaction_id: UUID,
        source: str,
        review_id: UUID | None = None,
        actor_id: UUID | None = None,
    ) -> None:
        session.add(
            ReconciledClaimPair(
                id=uuid7(),
                real_time_claim_id=candidate.real_time_claim_id,
                statement_claim_id=candidate.statement_claim_id,
                transaction_id=transaction_id,
                score=candidate.score,
                reasons=list(candidate.reasons),
                decision_source=source,
                review_id=review_id,
                actor_id=actor_id,
            )
        )
        session.flush()

    @staticmethod
    def _require_instant(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("reconciliation time must include a timezone")
        return value
