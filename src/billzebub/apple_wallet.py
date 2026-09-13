"""Fail-closed ingestion of the observed Apple Wallet Shortcut payload."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.artifact_capture import ArtifactArrivalInput, ArtifactCapture
from billzebub.financial_account_aliases import FinancialAccountAliases
from billzebub.persistence.models import (
    Claim,
    ClaimDispositionEvent,
    Extraction,
    PendingReview,
    ReviewEvent,
)
from billzebub.reviews import ReviewCondition, ReviewInbox, ReviewSeverity

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class AppleWalletCaptureStatus(StrEnum):
    ACCEPTED = "accepted"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True, slots=True)
class AppleWalletCaptureOutcome:
    status: AppleWalletCaptureStatus
    duplicate: bool


@dataclass(frozen=True, slots=True)
class _Payload:
    schema_version: str
    name: str
    merchant: str
    card: str
    amount: str
    date: str


class AppleWalletIngestion:
    """Preserve every authenticated Apple Wallet delivery before deriving a Claim."""

    _ADAPTER_KEY = "apple_wallet_shortcut"
    _PARSER_VERSION = "1"
    _SUPPORTED_SCHEMA_VERSION = "probe-2"
    _EXPECTED_FIELDS = frozenset({"schema_version", "name", "merchant", "card", "amount", "date"})
    _AMOUNT = re.compile(r"^\$(?P<amount>(?:0|[1-9]\d{0,2}(?:,\d{3})*|[1-9]\d*)(?:\.\d{2})?)$")
    _DATE_FORMAT = "%d %b %Y at %I:%M %p"
    _UNMAPPED_CARD_CONDITION = "apple_wallet_unmapped_card"

    def __init__(
        self,
        database: Database,
        artifacts: ArtifactCapture,
        aliases: FinancialAccountAliases,
        *,
        timezone: ZoneInfo,
    ) -> None:
        self._database = database
        self._artifacts = artifacts
        self._aliases = aliases
        self._timezone = timezone

    def ingest(
        self,
        body: bytes,
        *,
        received_at: datetime,
        actor_id: UUID | None,
    ) -> AppleWalletCaptureOutcome:
        """Record exact request bytes, then derive at most one eligible Real-time Claim."""
        artifact = self._artifacts.capture_bytes(
            body,
            ArtifactArrivalInput(
                source_type="apple_wallet_shortcut",
                media_type="application/json",
                received_at=received_at,
                metadata={"adapter_key": self._ADAPTER_KEY},
            ),
        )
        payload, failure_code = self._payload(body)
        if payload is None:
            return self._persist_failure(artifact.id, None, failure_code)

        try:
            account = self._aliases.resolve_apple_wallet_card(payload.card)
        except ValueError:
            return self._persist_failure(artifact.id, None, "invalid_card_label")
        if account is None:
            return self._persist_failure(artifact.id, None, "unmapped_card")

        amount = self._amount(payload.amount)
        if amount is None:
            return self._persist_failure(artifact.id, account.id, "invalid_amount")
        occurrence_at = self._occurrence_at(payload.date)
        if occurrence_at is None:
            return self._persist_failure(artifact.id, account.id, "invalid_occurrence_time")

        return self._persist_claim(
            artifact.id,
            account.id,
            account.default_currency,
            payload,
            amount,
            occurrence_at,
            artifact.sha256,
            actor_id,
        )

    def _payload(self, body: bytes) -> tuple[_Payload | None, str]:
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "invalid_json"
        if not isinstance(decoded, dict) or set(decoded) != self._EXPECTED_FIELDS:
            return None, "invalid_payload_shape"
        if any(not isinstance(decoded[field], str) for field in self._EXPECTED_FIELDS):
            return None, "invalid_payload_shape"
        values = {field: decoded[field].strip() for field in self._EXPECTED_FIELDS}
        if any(not value or len(value) > 500 for value in values.values()):
            return None, "invalid_payload_values"
        if values["schema_version"] != self._SUPPORTED_SCHEMA_VERSION:
            return None, "unsupported_schema_version"
        return _Payload(**values), ""

    def _amount(self, value: str) -> Decimal | None:
        match = self._AMOUNT.fullmatch(value)
        if match is None:
            return None
        try:
            amount = Decimal(match.group("amount").replace(",", ""))
        except InvalidOperation:
            return None
        if not amount.is_finite() or amount <= 0:
            return None
        return amount

    def _occurrence_at(self, value: str) -> datetime | None:
        try:
            parsed = datetime.strptime(value, self._DATE_FORMAT)  # noqa: DTZ007
        except ValueError:
            return None
        return parsed.replace(tzinfo=self._timezone)

    def _persist_claim(
        self,
        artifact_id: UUID,
        account_id: UUID,
        currency: str,
        payload: _Payload,
        amount: Decimal,
        occurrence_at: datetime,
        candidate_hash: str,
        actor_id: UUID | None,
    ) -> AppleWalletCaptureOutcome:
        with self._database.transaction() as session:
            existing = self._existing(session, artifact_id, account_id)
            if existing is not None:
                return self._outcome_from_existing(session, existing)

            extraction = Extraction(
                id=uuid7(),
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key=self._ADAPTER_KEY,
                parser_version=self._PARSER_VERSION,
                status="accepted",
                statement_currency=currency,
                candidate_row_count=1,
                claim_count=1,
                candidate_hash=candidate_hash,
                validation_report={
                    "payload_schema_version": payload.schema_version,
                    "amount_currency_source": "financial_account_default",
                    "occurrence_timezone_source": "configured_apple_wallet_timezone",
                },
                accepted_at=datetime.now(UTC),
            )
            session.add(extraction)
            session.flush()
            claim = Claim(
                id=uuid7(),
                claim_type="real_time",
                financial_account_id=account_id,
                source_artifact_id=artifact_id,
                extraction_id=extraction.id,
                raw_description=f"{payload.merchant} — {payload.name}",
                authorized_amount=-amount,
                authorized_currency=currency,
                occurrence_at=occurrence_at,
                transaction_kind_hint="expense",
            )
            session.add(claim)
            session.add(
                ClaimDispositionEvent(
                    id=uuid7(),
                    claim_id=claim.id,
                    disposition="provisional",
                    reason_code="claim_recorded",
                    actor_id=actor_id,
                )
            )
            self._cancel_unmapped_card_review(session, artifact_id)
            return AppleWalletCaptureOutcome(AppleWalletCaptureStatus.ACCEPTED, duplicate=False)

    def _persist_failure(
        self,
        artifact_id: UUID,
        account_id: UUID | None,
        code: str,
    ) -> AppleWalletCaptureOutcome:
        with self._database.transaction() as session:
            existing = self._existing(session, artifact_id, account_id)
            if existing is not None:
                return self._outcome_from_existing(session, existing)
            extraction = Extraction(
                id=uuid7(),
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key=self._ADAPTER_KEY,
                parser_version=self._PARSER_VERSION,
                status="failed",
                claim_count=0,
                failure_code=code,
                validation_report={"failure": {"code": code}},
            )
            session.add(extraction)
            if code == "unmapped_card":
                ReviewInbox.synchronize_in_session(
                    session,
                    ReviewCondition(
                        subject_type="source_artifact",
                        subject_id=artifact_id,
                        condition_code=self._UNMAPPED_CARD_CONDITION,
                        severity=ReviewSeverity.BLOCKING,
                        allowed_decisions=("configure_card_alias",),
                        context={"integration": "apple_wallet"},
                    ),
                    active=True,
                )
            return AppleWalletCaptureOutcome(
                AppleWalletCaptureStatus.REVIEW_REQUIRED, duplicate=False
            )

    def _existing(
        self,
        session: Session,
        artifact_id: UUID,
        account_id: UUID | None,
    ) -> Extraction | None:
        conditions = [
            Extraction.artifact_id == artifact_id,
            Extraction.adapter_key == self._ADAPTER_KEY,
            Extraction.parser_version == self._PARSER_VERSION,
        ]
        if account_id is None:
            conditions.append(Extraction.financial_account_id.is_(None))
        else:
            conditions.append(Extraction.financial_account_id == account_id)
        return session.scalar(select(Extraction).where(*conditions))

    @staticmethod
    def _outcome_from_existing(
        session: Session,
        extraction: Extraction,
    ) -> AppleWalletCaptureOutcome:
        if extraction.status == "accepted":
            claim = session.scalar(select(Claim.id).where(Claim.extraction_id == extraction.id))
            if claim is not None:
                return AppleWalletCaptureOutcome(AppleWalletCaptureStatus.ACCEPTED, duplicate=True)
        return AppleWalletCaptureOutcome(AppleWalletCaptureStatus.REVIEW_REQUIRED, duplicate=True)

    def _cancel_unmapped_card_review(self, session: Session, artifact_id: UUID) -> None:
        review = session.scalar(
            select(PendingReview)
            .where(
                PendingReview.subject_type == "source_artifact",
                PendingReview.subject_id == artifact_id,
                PendingReview.condition_code == self._UNMAPPED_CARD_CONDITION,
                PendingReview.status == "pending",
            )
            .with_for_update()
        )
        if review is None:
            return
        review.status = "cancelled"
        review.version += 1
        review.updated_at = datetime.now(UTC)
        session.add(
            ReviewEvent(
                id=uuid7(),
                review_id=review.id,
                version=review.version,
                event_type="cancelled",
            )
        )
