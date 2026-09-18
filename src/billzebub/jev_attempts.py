"""Append-only Jev categorization attempts for owner review."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.jev import JevError, JevSubject, Proposal, safe_error_message
from billzebub.persistence.models import JevCategorizationAttempt

_CONTEXT_KEY = "jev_attempt"


def record_jev_attempt(
    session: Session,
    *,
    transaction_id: UUID,
    subject: JevSubject,
    proposal: Proposal,
) -> JevCategorizationAttempt:
    """Persist one agent-safe Jev proposal (apply or skip). Never store secrets."""
    apply = proposal.action == "apply"
    row = JevCategorizationAttempt(
        id=uuid7(),
        transaction_id=transaction_id,
        model=_required_text(proposal.model, fallback="jev", maximum=120),
        counterparty=_required_text(subject.counterparty, maximum=300),
        amount=_decimal_amount(subject.amount),
        currency=_required_text(subject.currency, maximum=3).upper(),
        effective_date=_iso_date(subject.effective_date),
        kind=_required_text(subject.kind, maximum=30),
        choice=_optional_text(proposal.choice, maximum=120),
        choice_confidence=proposal.confidence,
        noul=proposal.noul,
        action="apply" if apply else "skip",
        category_id=proposal.category_id if apply else None,
        category_name=_optional_text(proposal.category_name, maximum=120) if apply else None,
        error_class=_optional_text(proposal.error_class, maximum=120),
        error_message=_optional_text(proposal.error_message, maximum=500),
    )
    session.add(row)
    session.flush()
    return row


def latest_jev_attempts(
    session: Session,
    transaction_ids: Iterable[UUID],
) -> dict[UUID, JevCategorizationAttempt]:
    ids = tuple(dict.fromkeys(transaction_ids))
    if not ids:
        return {}
    rows = session.scalars(
        select(JevCategorizationAttempt)
        .where(JevCategorizationAttempt.transaction_id.in_(ids))
        .distinct(JevCategorizationAttempt.transaction_id)
        .order_by(
            JevCategorizationAttempt.transaction_id,
            JevCategorizationAttempt.attempted_at.desc(),
            JevCategorizationAttempt.id.desc(),
        )
    ).all()
    return {row.transaction_id: row for row in rows}


def attempt_owner_context(row: JevCategorizationAttempt) -> dict[str, Any]:
    return {
        "model": row.model,
        "attempted_at": row.attempted_at.isoformat(),
        "action": row.action,
        "choice": row.choice,
        "choice_confidence": _wire_unit(row.choice_confidence),
        "noul": _wire_unit(row.noul),
        "category_id": str(row.category_id) if row.category_id is not None else None,
        "category_name": row.category_name,
        "error_class": row.error_class,
        "error_message": row.error_message,
        "counterparty": row.counterparty,
        "amount": format(row.amount, "f"),
        "currency": row.currency,
        "effective_date": row.effective_date.isoformat(),
        "kind": row.kind,
    }


def merge_jev_attempt_context(
    context: Mapping[str, Any],
    row: JevCategorizationAttempt | None,
) -> dict[str, Any]:
    merged = dict(context)
    if row is not None:
        merged[_CONTEXT_KEY] = attempt_owner_context(row)
    return merged


def proposal_from_jev_error(error: JevError, *, model: str) -> Proposal:
    cause = error.__cause__ if error.__cause__ is not None else error
    return Proposal(
        action="skip",
        category_id=None,
        category_name=None,
        confidence=Decimal("0"),
        model=model,
        error_class=type(cause).__name__[:120],
        error_message=safe_error_message(cause),
    )


def _required_text(value: str, *, maximum: int, fallback: str | None = None) -> str:
    trimmed = " ".join(value.split())
    if not trimmed and fallback is not None:
        trimmed = fallback
    if not trimmed:
        raise ValueError("Jev attempt field is required")
    return trimmed[:maximum]


def _optional_text(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    trimmed = " ".join(value.split())
    return trimmed[:maximum] if trimmed else None


def _decimal_amount(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError("Jev attempt amount is invalid") from error
    if not amount.is_finite():
        raise ValueError("Jev attempt amount is invalid")
    return amount


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("Jev attempt effective date is invalid") from error


def _wire_unit(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")
