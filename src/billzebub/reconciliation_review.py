"""Owner-facing display fields for an ambiguous Reconciliation review.

The stored Pending Review context stays the decision contract: candidate count,
statement claim ids, scores, and reason codes. The owner review API overlays
the provisional Real-time Claim and each Statement Claim candidate so a match
screen can render both sides without another request.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from billzebub.persistence.models import Claim, Extraction, FinancialAccount, FinancialAccountAlias
from billzebub.recurrings import normalize_counterparty

_AMBIGUOUS_CONDITION = "reconciliation_ambiguous"
_WALLET_ADAPTER = "apple_wallet_shortcut"
_PAYLAH_ADAPTER = "paylah_shortcut"
_WALLET_SOURCES = frozenset(
    {
        "apple_wallet",
        "apple-wallet",
        "apple-pay",
        "apple_pay",
        "apple pay",
        "wallet",
    }
)
_ADAPTER_ISSUERS = {
    "dbs-credit-card": "dbs",
    "citi-credit-card": "citi",
    "uob-credit-card": "uob",
}
_CRITERIA: dict[str, tuple[str, bool]] = {
    "same_financial_account": ("financial_account", True),
    "amount_exact_posted": ("amount", True),
    "amount_exact_original": ("amount", True),
    "amount_fx_within_reference_band": ("amount", True),
    "amount_mismatch": ("amount", False),
    "amount_fx_reference_missing": ("amount", False),
    "amount_fx_outside_reference_band": ("amount", False),
    "activity_date_exact": ("date", True),
    "activity_date_within_one_day": ("date", True),
    "activity_date_within_two_days": ("date", True),
    "activity_date_within_three_days": ("date", True),
    "activity_date_within_window": ("date", True),
    "counterparty_exact": ("counterparty", True),
    "counterparty_high_overlap": ("counterparty", True),
    "counterparty_partial_overlap": ("counterparty", True),
    "counterparty_low_overlap": ("counterparty", True),
    "counterparty_no_overlap": ("counterparty", False),
    "counterparty_unavailable": ("counterparty", False),
}


def card_last4(value: str | None) -> str | None:
    """Return a card or account last4, never a longer digit run."""
    if value is None:
        return None
    stripped = " ".join(value.split())
    if not stripped:
        return None
    digits = re.sub(r"\D", "", stripped)
    if len(digits) == 4 or 12 <= len(digits) <= 19:
        return digits[-4:]
    return None


def account_last4(identifier: str | None, alias_labels: Sequence[str]) -> str | None:
    """Prefer the statement account identifier, then a Wallet card alias."""
    found = card_last4(identifier)
    if found is not None:
        return found
    for label in alias_labels:
        found = card_last4(label)
        if found is not None:
            return found
    return None


def provisional_source(adapter_key: str | None, validation_report: object) -> str | None:
    """Map a Real-time Extraction onto the owner-facing source name."""
    reported = ""
    if isinstance(validation_report, dict):
        raw = validation_report.get("source")
        if isinstance(raw, str):
            reported = raw.strip().casefold()
    if adapter_key == _WALLET_ADAPTER or reported in _WALLET_SOURCES:
        return "wallet"
    if adapter_key == _PAYLAH_ADAPTER or reported == "paylah":
        return "paylah"
    return None


def statement_issuer(adapter_key: str | None, institution: str | None) -> str | None:
    if adapter_key is not None and adapter_key in _ADAPTER_ISSUERS:
        return _ADAPTER_ISSUERS[adapter_key]
    if institution is not None and institution.strip():
        return institution.strip()
    return None


def signed_amount_delta(
    provisional_amount: Decimal,
    provisional_currency: str,
    candidate_amount: Decimal,
    candidate_currency: str,
) -> str | None:
    """Candidate posted amount minus the provisional amount, in one currency."""
    if provisional_currency != candidate_currency:
        return None
    return format(candidate_amount - provisional_amount, "f")


def signed_day_delta(occurred_on: date, statement_on: date) -> int:
    """Statement comparison date minus the provisional occurrence date, in days."""
    return (statement_on - occurred_on).days


def match_criterion_results(reasons: Sequence[object]) -> list[dict[str, Any]]:
    """Mark each stored match code as passed or failed for its criterion."""
    results: list[dict[str, Any]] = []
    for reason in reasons:
        code = str(reason)
        criterion, passed = _CRITERIA.get(code, ("other", True))
        results.append({"criterion": criterion, "passed": passed, "code": code})
    return results


def occurred_at_payload(instant: datetime | None, timezone: ZoneInfo) -> dict[str, str | None]:
    """Split a Real-time occurrence into the reporting-timezone date and time."""
    if instant is None:
        return {"date": None, "time": None, "timezone": timezone.key}
    aware = instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)
    local = aware.astimezone(timezone)
    return {
        "date": local.date().isoformat(),
        "time": local.strftime("%H:%M:%S"),
        "timezone": timezone.key,
    }


def enrich_ambiguous_match_contexts(
    session: Session,
    reviews: Sequence[Any],
    *,
    reporting_timezone: ZoneInfo,
) -> dict[UUID, dict[str, Any]]:
    """Overlay display fields onto ambiguous-match contexts without dropping keys."""
    ambiguous = [
        review
        for review in reviews
        if review.condition_code == _AMBIGUOUS_CONDITION and review.subject_type == "claim"
    ]
    if not ambiguous:
        return {}

    claim_ids: list[UUID] = []
    for review in ambiguous:
        claim_ids.append(review.subject_id)
        claim_ids.extend(_candidate_ids(review.context))
    unique_ids = tuple(dict.fromkeys(claim_ids))
    claims = session.scalars(select(Claim).where(Claim.id.in_(unique_ids))).all()
    claims_by_id = {claim.id: claim for claim in claims}
    account_ids = tuple({claim.financial_account_id for claim in claims})
    extraction_ids = tuple({claim.extraction_id for claim in claims})
    accounts = (
        {
            account.id: account
            for account in session.scalars(
                select(FinancialAccount).where(FinancialAccount.id.in_(account_ids))
            ).all()
        }
        if account_ids
        else {}
    )
    extractions = (
        {
            extraction.id: extraction
            for extraction in session.scalars(
                select(Extraction).where(Extraction.id.in_(extraction_ids))
            ).all()
        }
        if extraction_ids
        else {}
    )
    aliases_by_account: dict[UUID, list[str]] = {}
    if account_ids:
        alias_rows = session.scalars(
            select(FinancialAccountAlias).where(
                FinancialAccountAlias.financial_account_id.in_(account_ids),
                FinancialAccountAlias.alias_kind == "apple_wallet_card",
            )
        ).all()
        for alias in alias_rows:
            aliases_by_account.setdefault(alias.financial_account_id, []).append(alias.value)

    enriched: dict[UUID, dict[str, Any]] = {}
    for review in ambiguous:
        provisional = claims_by_id.get(review.subject_id)
        context = dict(review.context)
        context["provisional"] = _provisional_payload(
            review.subject_id,
            provisional,
            accounts,
            extractions,
            aliases_by_account,
            reporting_timezone,
        )
        raw_candidates = review.context.get("candidates")
        if isinstance(raw_candidates, list):
            context["candidates"] = [
                _candidate_payload(
                    raw,
                    provisional,
                    claims_by_id,
                    accounts,
                    extractions,
                    aliases_by_account,
                    reporting_timezone,
                )
                if isinstance(raw, dict)
                else raw
                for raw in raw_candidates
            ]
        enriched[review.id] = context
    return enriched


def _candidate_ids(context: object) -> list[UUID]:
    if not isinstance(context, Mapping):
        return []
    raw_candidates = context.get("candidates")
    if not isinstance(raw_candidates, list):
        return []
    ids: list[UUID] = []
    for raw in raw_candidates:
        if not isinstance(raw, Mapping):
            continue
        claim_id = _uuid_or_none(raw.get("statement_claim_id"))
        if claim_id is not None:
            ids.append(claim_id)
    return ids


def _provisional_payload(
    subject_id: UUID,
    claim: Claim | None,
    accounts: Mapping[UUID, FinancialAccount],
    extractions: Mapping[UUID, Extraction],
    aliases_by_account: Mapping[UUID, Sequence[str]],
    reporting_timezone: ZoneInfo,
) -> dict[str, Any]:
    if claim is None or claim.authorized_amount is None or claim.authorized_currency is None:
        extraction = None if claim is None else extractions.get(claim.extraction_id)
        raw_description = None if claim is None else claim.raw_description
        return {
            "claim_id": str(subject_id),
            "counterparty": {
                "raw": raw_description,
                "normalized": (
                    None if raw_description is None else normalize_counterparty(raw_description)
                ),
            },
            "amount": None,
            "currency": None,
            "occurred_at": occurred_at_payload(
                None if claim is None else claim.occurrence_at,
                reporting_timezone,
            ),
            "last4": _last4_for(
                None if claim is None else claim.financial_account_id,
                accounts,
                aliases_by_account,
            ),
            "source": provisional_source(
                None if extraction is None else extraction.adapter_key,
                None if extraction is None else extraction.validation_report,
            ),
        }
    extraction = extractions.get(claim.extraction_id)
    raw_description = claim.raw_description
    return {
        "claim_id": str(claim.id),
        "counterparty": {
            "raw": raw_description,
            "normalized": normalize_counterparty(raw_description),
        },
        "amount": format(claim.authorized_amount, "f"),
        "currency": claim.authorized_currency,
        "occurred_at": occurred_at_payload(claim.occurrence_at, reporting_timezone),
        "last4": _last4_for(claim.financial_account_id, accounts, aliases_by_account),
        "source": provisional_source(
            None if extraction is None else extraction.adapter_key,
            None if extraction is None else extraction.validation_report,
        ),
    }


def _candidate_payload(
    raw: Mapping[str, Any],
    provisional: Claim | None,
    claims_by_id: Mapping[UUID, Claim],
    accounts: Mapping[UUID, FinancialAccount],
    extractions: Mapping[UUID, Extraction],
    aliases_by_account: Mapping[UUID, Sequence[str]],
    reporting_timezone: ZoneInfo,
) -> dict[str, Any]:
    item = dict(raw)
    claim_id = _uuid_or_none(raw.get("statement_claim_id"))
    claim = None if claim_id is None else claims_by_id.get(claim_id)
    reasons = raw.get("reasons")
    reason_list = list(reasons) if isinstance(reasons, list) else []
    item["match_reasons"] = match_criterion_results(reason_list)
    if claim_id is not None:
        item["claim_id"] = str(claim_id)
    if claim is None:
        item.setdefault("raw_description", None)
        item.setdefault("normalized_counterparty", None)
        item.setdefault("amount", None)
        item.setdefault("currency", None)
        item.setdefault("posted_date", None)
        item.setdefault("transaction_date", None)
        item.setdefault("last4", None)
        item.setdefault("statement_id", None)
        item.setdefault("statement_identity", None)
        item.setdefault("statement_label", None)
        item.setdefault("issuer", None)
        item.setdefault("period_start", None)
        item.setdefault("period_end", None)
        item.setdefault("amount_delta", None)
        item.setdefault("day_delta", None)
        return item

    account = accounts.get(claim.financial_account_id)
    extraction = extractions.get(claim.extraction_id)
    raw_description = claim.raw_description
    posted_on = claim.posting_date
    transaction_on = claim.provider_transaction_date
    comparison_on = transaction_on or posted_on
    occurred_on = _occurred_on(provisional, reporting_timezone)
    amount_delta = None
    if (
        provisional is not None
        and provisional.authorized_amount is not None
        and provisional.authorized_currency is not None
        and claim.posted_amount is not None
        and claim.posted_currency is not None
    ):
        amount_delta = signed_amount_delta(
            provisional.authorized_amount,
            provisional.authorized_currency,
            claim.posted_amount,
            claim.posted_currency,
        )
    item.update(
        {
            "raw_description": raw_description,
            "normalized_counterparty": normalize_counterparty(raw_description),
            "amount": None if claim.posted_amount is None else format(claim.posted_amount, "f"),
            "currency": claim.posted_currency,
            "posted_date": None if posted_on is None else posted_on.isoformat(),
            "transaction_date": None if transaction_on is None else transaction_on.isoformat(),
            "last4": _last4_for(claim.financial_account_id, accounts, aliases_by_account),
            "statement_id": None if extraction is None else str(extraction.id),
            "statement_identity": None if extraction is None else extraction.statement_identity,
            "statement_label": None if account is None else account.display_name,
            "issuer": statement_issuer(
                None if extraction is None else extraction.adapter_key,
                None if account is None else account.institution,
            ),
            "period_start": _date_text(None if extraction is None else extraction.period_start),
            "period_end": _date_text(None if extraction is None else extraction.period_end),
            "amount_delta": amount_delta,
            "day_delta": (
                None
                if occurred_on is None or comparison_on is None
                else signed_day_delta(occurred_on, comparison_on)
            ),
        }
    )
    return item


def _last4_for(
    account_id: UUID | None,
    accounts: Mapping[UUID, FinancialAccount],
    aliases_by_account: Mapping[UUID, Sequence[str]],
) -> str | None:
    if account_id is None:
        return None
    account = accounts.get(account_id)
    return account_last4(
        None if account is None else account.statement_account_identifier,
        aliases_by_account.get(account_id, ()),
    )


def _occurred_on(claim: Claim | None, reporting_timezone: ZoneInfo) -> date | None:
    if claim is None or claim.occurrence_at is None:
        return None
    instant = claim.occurrence_at
    aware = instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)
    return aware.astimezone(reporting_timezone).date()


def _date_text(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _uuid_or_none(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
