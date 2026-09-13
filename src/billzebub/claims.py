"""Immutable Claim content and append-only Claim Disposition history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.money import Money
from billzebub.persistence.models import (
    Claim,
    ClaimDispositionEvent,
    ClaimSourceLocator,
    Extraction,
)

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class ClaimType(StrEnum):
    REAL_TIME = "real_time"
    STATEMENT = "statement"


class ClaimDisposition(StrEnum):
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    EXCLUDED = "excluded"


class InvalidClaimError(ValueError):
    """Claim content is incomplete or inconsistent."""


class ClaimNotFoundError(LookupError):
    """No Claim exists for the requested identifier."""


class InvalidClaimTransitionError(ValueError):
    """A requested Claim Disposition transition is not permitted."""


@dataclass(frozen=True, slots=True)
class ClaimDraft:
    claim_type: ClaimType
    financial_account_id: UUID
    source_artifact_id: UUID
    extraction_id: UUID
    raw_description: str
    authorized_amount: Money | None = None
    posted_amount: Money | None = None
    original_amount: Money | None = None
    occurrence_at: datetime | None = None
    provider_transaction_date: date | None = None
    posting_date: date | None = None
    transaction_kind_hint: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    id: UUID
    claim_type: ClaimType
    financial_account_id: UUID
    source_artifact_id: UUID
    extraction_id: UUID
    raw_description: str
    authorized_amount: Money | None
    posted_amount: Money | None
    original_amount: Money | None
    occurrence_at: datetime | None
    provider_transaction_date: date | None
    posting_date: date | None
    transaction_kind_hint: str | None


@dataclass(frozen=True, slots=True)
class ClaimLocatorRecord:
    page_number: int
    line_number: int
    text_start: int
    text_end: int
    text_sha256: str | None


@dataclass(frozen=True, slots=True)
class DispositionRecord:
    id: UUID
    claim_id: UUID
    disposition: ClaimDisposition
    reason_code: str
    occurred_at: datetime


_ALLOWED_TRANSITIONS: dict[ClaimDisposition, frozenset[ClaimDisposition]] = {
    ClaimDisposition.PROVISIONAL: frozenset(
        {
            ClaimDisposition.CONFIRMED,
            ClaimDisposition.UNCONFIRMED,
            ClaimDisposition.EXCLUDED,
        }
    ),
    ClaimDisposition.UNCONFIRMED: frozenset({ClaimDisposition.CONFIRMED}),
    ClaimDisposition.CONFIRMED: frozenset(),
    ClaimDisposition.EXCLUDED: frozenset(),
}


class ClaimBook:
    """Record immutable Claims and append conclusions without rewriting evidence."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def record(self, draft: ClaimDraft) -> ClaimRecord:
        self._validate_draft(draft)
        claim_id = uuid7()
        with self._database.transaction() as session:
            extraction = session.get(Extraction, draft.extraction_id)
            if extraction is None or extraction.status != "accepted":
                raise InvalidClaimError("Claims require an accepted Extraction")
            if extraction.artifact_id != draft.source_artifact_id:
                raise InvalidClaimError("Claim Source Artifact must match its Extraction")

            claim = Claim(
                id=claim_id,
                claim_type=draft.claim_type.value,
                financial_account_id=draft.financial_account_id,
                source_artifact_id=draft.source_artifact_id,
                extraction_id=draft.extraction_id,
                raw_description=draft.raw_description,
                authorized_amount=(
                    draft.authorized_amount.amount if draft.authorized_amount else None
                ),
                authorized_currency=(
                    draft.authorized_amount.currency if draft.authorized_amount else None
                ),
                posted_amount=draft.posted_amount.amount if draft.posted_amount else None,
                posted_currency=draft.posted_amount.currency if draft.posted_amount else None,
                original_amount=draft.original_amount.amount if draft.original_amount else None,
                original_currency=draft.original_amount.currency if draft.original_amount else None,
                occurrence_at=draft.occurrence_at,
                provider_transaction_date=draft.provider_transaction_date,
                posting_date=draft.posting_date,
                transaction_kind_hint=draft.transaction_kind_hint,
            )
            session.add(claim)
            session.add(
                ClaimDispositionEvent(
                    id=uuid7(),
                    claim_id=claim_id,
                    disposition=ClaimDisposition.PROVISIONAL.value,
                    reason_code="claim_recorded",
                )
            )
        return self._record_from_model(claim)

    def for_extraction(self, extraction_id: UUID) -> tuple[ClaimRecord, ...]:
        with self._database.transaction() as session:
            claims = session.scalars(
                select(Claim)
                .where(Claim.extraction_id == extraction_id)
                .order_by(Claim.created_at, Claim.id)
            ).all()
            return tuple(self._record_from_model(claim) for claim in claims)

    def source_locator(self, claim_id: UUID) -> ClaimLocatorRecord:
        with self._database.transaction() as session:
            locator = session.scalar(
                select(ClaimSourceLocator).where(ClaimSourceLocator.claim_id == claim_id)
            )
            if locator is None:
                raise ClaimNotFoundError(str(claim_id))
            return ClaimLocatorRecord(
                page_number=locator.page_number,
                line_number=locator.line_number,
                text_start=locator.text_start,
                text_end=locator.text_end,
                text_sha256=locator.text_sha256,
            )

    def current_disposition(self, claim_id: UUID) -> ClaimDisposition:
        with self._database.transaction() as session:
            event = self._latest_event(session, claim_id)
            return ClaimDisposition(event.disposition)

    def disposition_history(self, claim_id: UUID) -> tuple[DispositionRecord, ...]:
        with self._database.transaction() as session:
            if session.get(Claim, claim_id) is None:
                raise ClaimNotFoundError(str(claim_id))
            events = session.scalars(
                select(ClaimDispositionEvent)
                .where(ClaimDispositionEvent.claim_id == claim_id)
                .order_by(ClaimDispositionEvent.occurred_at, ClaimDispositionEvent.id)
            ).all()
            return tuple(self._disposition_from_model(event) for event in events)

    def mark_unconfirmed(
        self,
        claim_id: UUID,
        *,
        reason_code: str,
        actor_id: UUID | None = None,
    ) -> DispositionRecord:
        with self._database.transaction() as session:
            event = self.mark_unconfirmed_in_session(
                session,
                claim_id,
                reason_code=reason_code,
                actor_id=actor_id,
            )
        return self._disposition_from_model(event)

    @classmethod
    def mark_unconfirmed_in_session(
        cls,
        session: Session,
        claim_id: UUID,
        *,
        reason_code: str,
        actor_id: UUID | None = None,
    ) -> ClaimDispositionEvent:
        """Conclude a Claim within a caller-owned database transaction."""
        return cls._transition(
            session,
            claim_id,
            ClaimDisposition.UNCONFIRMED,
            reason_code,
            actor_id,
        )

    def exclude(
        self,
        claim_id: UUID,
        *,
        reason_code: str,
        actor_id: UUID | None = None,
    ) -> DispositionRecord:
        with self._database.transaction() as session:
            event = self._transition(
                session,
                claim_id,
                ClaimDisposition.EXCLUDED,
                reason_code,
                actor_id,
            )
        return self._disposition_from_model(event)

    @classmethod
    def confirm_in_session(
        cls,
        session: Session,
        claim_id: UUID,
        *,
        reason_code: str,
        actor_id: UUID | None = None,
    ) -> ClaimDispositionEvent:
        return cls._transition(
            session,
            claim_id,
            ClaimDisposition.CONFIRMED,
            reason_code,
            actor_id,
        )

    @staticmethod
    def _transition(
        session: Session,
        claim_id: UUID,
        target: ClaimDisposition,
        reason_code: str,
        actor_id: UUID | None,
    ) -> ClaimDispositionEvent:
        claim = session.scalar(select(Claim).where(Claim.id == claim_id).with_for_update())
        if claim is None:
            raise ClaimNotFoundError(str(claim_id))
        current_event = ClaimBook._latest_event(session, claim_id)
        current = ClaimDisposition(current_event.disposition)
        if target not in _ALLOWED_TRANSITIONS[current]:
            raise InvalidClaimTransitionError(
                f"cannot move Claim from {current.value.title()} to {target.value.title()}"
            )
        if not reason_code.strip():
            raise InvalidClaimTransitionError("a disposition reason code is required")
        event = ClaimDispositionEvent(
            id=uuid7(),
            claim_id=claim_id,
            disposition=target.value,
            reason_code=reason_code,
            actor_id=actor_id,
        )
        session.add(event)
        session.flush()
        return event

    @staticmethod
    def _latest_event(session: Session, claim_id: UUID) -> ClaimDispositionEvent:
        event = session.scalar(
            select(ClaimDispositionEvent)
            .where(ClaimDispositionEvent.claim_id == claim_id)
            .order_by(
                ClaimDispositionEvent.occurred_at.desc(),
                ClaimDispositionEvent.id.desc(),
            )
            .limit(1)
        )
        if event is None:
            raise ClaimNotFoundError(str(claim_id))
        return event

    @staticmethod
    def _validate_draft(draft: ClaimDraft) -> None:
        if not draft.raw_description.strip():
            raise InvalidClaimError("a raw description is required")
        if draft.claim_type is ClaimType.REAL_TIME:
            if draft.authorized_amount is None or draft.occurrence_at is None:
                raise InvalidClaimError(
                    "a Real-time Claim requires Authorized Amount and occurrence time"
                )
            if draft.occurrence_at.utcoffset() is None:
                raise InvalidClaimError("occurrence time must include a timezone")
            if draft.posted_amount is not None:
                raise InvalidClaimError("a Real-time Claim cannot assert a Posted Amount")
        elif draft.claim_type is ClaimType.STATEMENT:
            if draft.posted_amount is None or draft.posting_date is None:
                raise InvalidClaimError("a Statement Claim requires Posted Amount and posting date")
            if draft.authorized_amount is not None:
                raise InvalidClaimError("a Statement Claim cannot assert an Authorized Amount")
        if draft.authorized_amount and draft.authorized_amount.amount == 0:
            raise InvalidClaimError("Claim amounts cannot be zero")
        if draft.posted_amount and draft.posted_amount.amount == 0:
            raise InvalidClaimError("Claim amounts cannot be zero")
        if draft.original_amount and draft.original_amount.amount == 0:
            raise InvalidClaimError("Claim amounts cannot be zero")

    @staticmethod
    def _record_from_model(claim: Claim) -> ClaimRecord:
        return ClaimRecord(
            id=claim.id,
            claim_type=ClaimType(claim.claim_type),
            financial_account_id=claim.financial_account_id,
            source_artifact_id=claim.source_artifact_id,
            extraction_id=claim.extraction_id,
            raw_description=claim.raw_description,
            authorized_amount=(
                Money(claim.authorized_amount, claim.authorized_currency)
                if claim.authorized_amount is not None and claim.authorized_currency is not None
                else None
            ),
            posted_amount=(
                Money(claim.posted_amount, claim.posted_currency)
                if claim.posted_amount is not None and claim.posted_currency is not None
                else None
            ),
            original_amount=(
                Money(claim.original_amount, claim.original_currency)
                if claim.original_amount is not None and claim.original_currency is not None
                else None
            ),
            occurrence_at=claim.occurrence_at,
            provider_transaction_date=claim.provider_transaction_date,
            posting_date=claim.posting_date,
            transaction_kind_hint=claim.transaction_kind_hint,
        )

    @staticmethod
    def _disposition_from_model(event: ClaimDispositionEvent) -> DispositionRecord:
        return DispositionRecord(
            id=event.id,
            claim_id=event.claim_id,
            disposition=ClaimDisposition(event.disposition),
            reason_code=event.reason_code,
            occurred_at=event.occurred_at,
        )
