"""Fail-closed ingestion of Shortcut Real-time Claims (Apple Wallet and PayLah)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.artifact_capture import ArtifactArrivalInput, ArtifactCapture
from billzebub.financial_account_aliases import AppleWalletAccountRecord, FinancialAccountAliases
from billzebub.persistence.models import (
    Claim,
    ClaimDispositionEvent,
    Extraction,
    FinancialAccount,
    FinancialAccountKind,
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
    source: str
    name: str
    merchant: str | None
    instrument: str | None
    amount: str
    date: str


@dataclass(frozen=True, slots=True)
class _ArrivalTyping:
    source_type: str
    adapter_key: str
    metadata: dict[str, Any]


class AppleWalletIngestion:
    """Preserve every authenticated Shortcut delivery before deriving a Claim."""

    _WALLET_ADAPTER_KEY = "apple_wallet_shortcut"
    _PAYLAH_ADAPTER_KEY = "paylah_shortcut"
    _PARSER_VERSION = "1"
    _PROBE2_SCHEMA = "probe-2"
    _REALTIME_SCHEMA = "realtime-1"
    _SOURCE_APPLE_WALLET = "apple_wallet"
    _SOURCE_PAYLAH = "paylah"
    _PROBE2_FIELDS = frozenset({"schema_version", "name", "merchant", "card", "amount", "date"})
    _APPLE_WALLET_REALTIME_FIELDS = frozenset(
        {"schema_version", "source", "name", "merchant", "instrument", "amount", "date"}
    )
    _PAYLAH_REALTIME_FIELDS = frozenset({"schema_version", "source", "name", "amount", "date"})
    _AMOUNT = re.compile(r"^\$(?P<amount>(?:0|[1-9]\d{0,2}(?:,\d{3})*|[1-9]\d*)(?:\.\d{2})?)$")
    _DATE_FORMAT = "%d %b %Y at %I:%M %p"
    _UNMAPPED_CARD_CONDITION = "apple_wallet_unmapped_card"
    _MISSING_PAYLAH_CONDITION = "paylah_account_missing"
    _AMBIGUOUS_PAYLAH_CONDITION = "paylah_account_ambiguous"
    _CONFIGURATION_REVIEW_CONDITIONS = frozenset(
        {_UNMAPPED_CARD_CONDITION, _MISSING_PAYLAH_CONDITION, _AMBIGUOUS_PAYLAH_CONDITION}
    )

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
        arrival = self._arrival_typing(body)
        artifact = self._artifacts.capture_bytes(
            body,
            ArtifactArrivalInput(
                source_type=arrival.source_type,
                media_type="application/json",
                received_at=received_at,
                metadata=arrival.metadata,
            ),
        )
        payload, failure_code = self._payload(body)
        if payload is None:
            return self._persist_failure(artifact.id, None, failure_code, arrival.adapter_key)

        account, account_failure = self._resolve_account(payload)
        if account is None:
            return self._persist_failure(artifact.id, None, account_failure, arrival.adapter_key)

        amount = self._amount(payload.amount)
        if amount is None:
            return self._persist_failure(
                artifact.id, account.id, "invalid_amount", arrival.adapter_key
            )
        occurrence_at = self._occurrence_at(payload.date)
        if occurrence_at is None:
            return self._persist_failure(
                artifact.id, account.id, "invalid_occurrence_time", arrival.adapter_key
            )

        return self._persist_claim(
            artifact.id,
            account.id,
            account.default_currency,
            payload,
            amount,
            occurrence_at,
            artifact.sha256,
            actor_id,
            arrival.adapter_key,
        )

    def _arrival_typing(self, body: bytes) -> _ArrivalTyping:
        schema_version, source = self._peek_declared_identity(body)
        if source is None and schema_version == self._PROBE2_SCHEMA:
            source = self._SOURCE_APPLE_WALLET
        if source == self._SOURCE_PAYLAH:
            adapter_key = self._PAYLAH_ADAPTER_KEY
            source_type = "paylah_shortcut"
        else:
            adapter_key = self._WALLET_ADAPTER_KEY
            source_type = "apple_wallet_shortcut"
        metadata: dict[str, Any] = {"adapter_key": adapter_key}
        if source is not None:
            metadata["source"] = source
        if schema_version is not None:
            metadata["schema_version"] = schema_version
        return _ArrivalTyping(source_type=source_type, adapter_key=adapter_key, metadata=metadata)

    @staticmethod
    def _peek_declared_identity(body: bytes) -> tuple[str | None, str | None]:
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, None
        if not isinstance(decoded, dict):
            return None, None
        schema = decoded.get("schema_version")
        source = decoded.get("source")
        schema_version = schema.strip() if isinstance(schema, str) else None
        declared_source = source.strip() if isinstance(source, str) else None
        return schema_version or None, declared_source or None

    def _payload(self, body: bytes) -> tuple[_Payload | None, str]:
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "invalid_json"
        if not isinstance(decoded, dict):
            return None, "invalid_payload_shape"
        if set(decoded) == self._PROBE2_FIELDS:
            return self._probe2_payload(decoded)
        schema = decoded.get("schema_version")
        if isinstance(schema, str) and schema.strip() == self._REALTIME_SCHEMA:
            return self._realtime1_payload(decoded)
        if isinstance(schema, str) and schema.strip() and schema.strip() != self._PROBE2_SCHEMA:
            return None, "unsupported_schema_version"
        return None, "invalid_payload_shape"

    def _probe2_payload(self, decoded: dict[str, Any]) -> tuple[_Payload | None, str]:
        values, failure = self._exact_string_fields(decoded, self._PROBE2_FIELDS)
        if values is None:
            return None, failure
        if values["schema_version"] != self._PROBE2_SCHEMA:
            return None, "unsupported_schema_version"
        return (
            _Payload(
                schema_version=values["schema_version"],
                source=self._SOURCE_APPLE_WALLET,
                name=values["name"],
                merchant=values["merchant"],
                instrument=values["card"],
                amount=values["amount"],
                date=values["date"],
            ),
            "",
        )

    def _realtime1_payload(self, decoded: dict[str, Any]) -> tuple[_Payload | None, str]:
        source = decoded.get("source")
        if not isinstance(source, str):
            return None, "invalid_payload_shape"
        normalized_source = source.strip()
        if normalized_source == self._SOURCE_APPLE_WALLET:
            return self._apple_wallet_realtime_payload(decoded)
        if normalized_source == self._SOURCE_PAYLAH:
            return self._paylah_realtime_payload(decoded)
        if not normalized_source or len(normalized_source) > 500:
            return None, "invalid_payload_values"
        return None, "unsupported_source"

    def _apple_wallet_realtime_payload(
        self, decoded: dict[str, Any]
    ) -> tuple[_Payload | None, str]:
        rewritten = dict(decoded)
        if "card" in rewritten and "instrument" not in rewritten:
            rewritten["instrument"] = rewritten.pop("card")
        values, failure = self._exact_string_fields(rewritten, self._APPLE_WALLET_REALTIME_FIELDS)
        if values is None:
            return None, failure
        return (
            _Payload(
                schema_version=values["schema_version"],
                source=self._SOURCE_APPLE_WALLET,
                name=values["name"],
                merchant=values["merchant"],
                instrument=values["instrument"],
                amount=values["amount"],
                date=values["date"],
            ),
            "",
        )

    def _paylah_realtime_payload(self, decoded: dict[str, Any]) -> tuple[_Payload | None, str]:
        values, failure = self._exact_string_fields(decoded, self._PAYLAH_REALTIME_FIELDS)
        if values is None:
            return None, failure
        return (
            _Payload(
                schema_version=values["schema_version"],
                source=self._SOURCE_PAYLAH,
                name=values["name"],
                merchant=None,
                instrument=None,
                amount=values["amount"],
                date=values["date"],
            ),
            "",
        )

    @staticmethod
    def _exact_string_fields(
        decoded: dict[str, Any], expected: frozenset[str]
    ) -> tuple[dict[str, str] | None, str]:
        if set(decoded) != expected:
            return None, "invalid_payload_shape"
        if any(not isinstance(decoded[field], str) for field in expected):
            return None, "invalid_payload_shape"
        values = {field: decoded[field].strip() for field in expected}
        if any(not value or len(value) > 500 for value in values.values()):
            return None, "invalid_payload_values"
        return values, ""

    def _resolve_account(self, payload: _Payload) -> tuple[AppleWalletAccountRecord | None, str]:
        if payload.source == self._SOURCE_PAYLAH:
            return self._resolve_unique_paylah()
        try:
            account = self._aliases.resolve_apple_wallet_card(payload.instrument or "")
        except ValueError:
            return None, "invalid_card_label"
        if account is None:
            return None, "unmapped_card"
        return account, ""

    def _resolve_unique_paylah(self) -> tuple[AppleWalletAccountRecord | None, str]:
        with self._database.transaction() as session:
            rows = session.execute(
                select(FinancialAccount.id, FinancialAccount.default_currency).where(
                    FinancialAccount.active.is_(True),
                    FinancialAccount.kind == FinancialAccountKind.PAYLAH,
                )
            ).all()
        if not rows:
            return None, "missing_paylah_account"
        if len(rows) > 1:
            return None, "ambiguous_paylah_account"
        return AppleWalletAccountRecord(
            id=rows[0].id, default_currency=rows[0].default_currency
        ), ""

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
        adapter_key: str,
    ) -> AppleWalletCaptureOutcome:
        raw_description = (
            payload.name if payload.merchant is None else f"{payload.merchant} — {payload.name}"
        )
        with self._database.transaction() as session:
            existing = self._existing(session, artifact_id, account_id, adapter_key)
            if existing is not None:
                return self._outcome_from_existing(session, existing)

            extraction = Extraction(
                id=uuid7(),
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key=adapter_key,
                parser_version=self._PARSER_VERSION,
                status="accepted",
                statement_currency=currency,
                candidate_row_count=1,
                claim_count=1,
                candidate_hash=candidate_hash,
                validation_report={
                    "payload_schema_version": payload.schema_version,
                    "source": payload.source,
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
                raw_description=raw_description,
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
            self._cancel_configuration_reviews(session, artifact_id)
            return AppleWalletCaptureOutcome(AppleWalletCaptureStatus.ACCEPTED, duplicate=False)

    def _persist_failure(
        self,
        artifact_id: UUID,
        account_id: UUID | None,
        code: str,
        adapter_key: str,
    ) -> AppleWalletCaptureOutcome:
        with self._database.transaction() as session:
            existing = self._existing(session, artifact_id, account_id, adapter_key)
            if existing is not None:
                return self._outcome_from_existing(session, existing)
            extraction = Extraction(
                id=uuid7(),
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key=adapter_key,
                parser_version=self._PARSER_VERSION,
                status="failed",
                claim_count=0,
                failure_code=code,
                validation_report={"failure": {"code": code}},
            )
            session.add(extraction)
            review = self._review_for_failure(code)
            if review is not None:
                ReviewInbox.synchronize_in_session(
                    session,
                    ReviewCondition(
                        subject_type="source_artifact",
                        subject_id=artifact_id,
                        condition_code=review[0],
                        severity=ReviewSeverity.BLOCKING,
                        allowed_decisions=review[1],
                        context=review[2],
                    ),
                    active=True,
                )
            return AppleWalletCaptureOutcome(
                AppleWalletCaptureStatus.REVIEW_REQUIRED, duplicate=False
            )

    def _review_for_failure(self, code: str) -> tuple[str, tuple[str, ...], dict[str, str]] | None:
        if code == "unmapped_card":
            return (
                self._UNMAPPED_CARD_CONDITION,
                ("configure_card_alias",),
                {"integration": "apple_wallet"},
            )
        if code == "missing_paylah_account":
            return (
                self._MISSING_PAYLAH_CONDITION,
                ("configure_paylah_account",),
                {"integration": "paylah"},
            )
        if code == "ambiguous_paylah_account":
            return (
                self._AMBIGUOUS_PAYLAH_CONDITION,
                ("configure_paylah_account",),
                {"integration": "paylah"},
            )
        return None

    def _existing(
        self,
        session: Session,
        artifact_id: UUID,
        account_id: UUID | None,
        adapter_key: str,
    ) -> Extraction | None:
        conditions = [
            Extraction.artifact_id == artifact_id,
            Extraction.adapter_key == adapter_key,
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

    def _cancel_configuration_reviews(self, session: Session, artifact_id: UUID) -> None:
        reviews = session.scalars(
            select(PendingReview)
            .where(
                PendingReview.subject_type == "source_artifact",
                PendingReview.subject_id == artifact_id,
                PendingReview.condition_code.in_(self._CONFIGURATION_REVIEW_CONDITIONS),
                PendingReview.status == "pending",
            )
            .with_for_update()
        ).all()
        now = datetime.now(UTC)
        for review in reviews:
            review.status = "cancelled"
            review.version += 1
            review.updated_at = now
            session.add(
                ReviewEvent(
                    id=uuid7(),
                    review_id=review.id,
                    version=review.version,
                    event_type="cancelled",
                )
            )
