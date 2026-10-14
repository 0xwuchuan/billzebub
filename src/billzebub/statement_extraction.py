"""Strict, atomic statement Extraction behind institution adapter seams."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.artifacts import ContentAddressedStore
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    Claim,
    ClaimDispositionEvent,
    ClaimSourceLocator,
    Extraction,
    FinancialAccount,
    FinancialAccountKind,
    PendingReview,
    ReviewEvent,
    SourceArtifact,
)

_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9]\d*)\.\d+$")
_SECRET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
_UNMASKED_PAN = re.compile(r"\d{13,}")
_METADATA_FIELDS = frozenset({"statement_date", "closing_balance", "opening_balance"})
_METADATA_PROBLEMS = frozenset({"missing", "ambiguous"})
_MAX_METADATA_FIELDS = 8
_MAX_METADATA_CANDIDATES = 8
_MAX_METADATA_CANDIDATE_LENGTH = 80
_KNOWN_KINDS = {
    "expense",
    "income",
    "transfer",
    "refund",
    "reimbursement",
    "cash_withdrawal",
}


class ExtractionStatus(StrEnum):
    ACCEPTED = "accepted"
    FAILED = "failed"
    REPROCESS_REQUIRED = "reprocess_required"


@dataclass(frozen=True, slots=True)
class SourceLocator:
    page_number: int
    line_number: int
    text_start: int
    text_end: int
    text_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.page_number <= 0 or self.line_number <= 0:
            raise ValueError("Source Locator page and line numbers are one-based")
        if self.text_start < 0 or self.text_end <= self.text_start:
            raise ValueError("Source Locator text span is invalid")
        if self.text_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", self.text_sha256) is None:
            raise ValueError("Source Locator text hash must be SHA-256")


@dataclass(frozen=True, slots=True)
class StatementRowCandidate:
    raw_description: str
    posted_amount_text: str
    provider_transaction_date: date
    posting_date: date
    transaction_kind_hint: str | None
    locator: SourceLocator
    original_amount_text: str | None = None
    original_currency: str | None = None


@dataclass(frozen=True, slots=True)
class StatementCandidate:
    statement_identity: str
    account_identifier: str
    statement_date: date
    period_start: date
    period_end: date
    currency: str
    opening_balance_text: str
    closing_balance_text: str
    candidate_row_count: int
    rows: tuple[StatementRowCandidate, ...]


class StatementAdapter(Protocol):
    key: str
    version: str
    institution: str

    def extract(
        self,
        path: Path,
        passwords: tuple[SecretStr, ...],
        expected_account_identifier: str | None = None,
    ) -> StatementCandidate: ...


class StatementAdapterError(Exception):
    """An adapter failed with a bounded code safe for persistence."""

    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


class StatementAdapterRegistry:
    """Resolve only explicitly configured statement adapters."""

    def __init__(self, adapters: Sequence[StatementAdapter]) -> None:
        self._adapters: dict[str, StatementAdapter] = {}
        for adapter in adapters:
            if not adapter.key.strip() or not adapter.version.strip():
                raise ValueError("statement adapter key and version are required")
            if adapter.key in self._adapters:
                raise ValueError(f"duplicate statement adapter key: {adapter.key}")
            self._adapters[adapter.key] = adapter

    def get(self, key: str) -> StatementAdapter:
        try:
            return self._adapters[key]
        except KeyError as error:
            raise StatementAdapterError("adapter_not_configured") from error


@dataclass(frozen=True, slots=True)
class ExtractionFailure:
    code: str
    details: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    extraction_id: UUID
    status: ExtractionStatus
    claim_count: int
    duplicate: bool
    failure: ExtractionFailure | None
    review_id: UUID | None


@dataclass(frozen=True, slots=True)
class _ValidatedCandidate:
    candidate: StatementCandidate
    opening_balance: Decimal
    closing_balance: Decimal
    posted_amounts: tuple[Decimal, ...]
    original_amounts: tuple[Decimal | None, ...]
    candidate_hash: str
    validation_report: dict[str, Any]


class _ValidationFailure(Exception):  # noqa: N818
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _safe_metadata_fields(value: object) -> list[dict[str, Any]]:
    """Keep a short, masked list of metadata failure fields.

    A candidate that still contains a long digit run is dropped. The field
    entry stays so a review can see which value was missing or ambiguous.
    """
    if not isinstance(value, list) or len(value) > _MAX_METADATA_FIELDS:
        return []
    cleaned: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            return []
        field = item.get("field")
        problem = item.get("problem")
        candidates = item.get("candidates")
        if (
            not isinstance(field, str)
            or field not in _METADATA_FIELDS
            or not isinstance(problem, str)
            or problem not in _METADATA_PROBLEMS
            or not isinstance(candidates, list)
            or len(candidates) > _MAX_METADATA_CANDIDATES
        ):
            return []
        safe_candidates: list[str] = []
        for candidate in candidates:
            if type(candidate) is not str or len(candidate) > _MAX_METADATA_CANDIDATE_LENGTH:
                return []
            if _UNMASKED_PAN.search(candidate) is not None:
                continue
            safe_candidates.append(candidate)
        cleaned.append({"field": field, "problem": problem, "candidates": safe_candidates})
    return cleaned


class StatementExtraction:
    """Validate a complete statement result and persist all Claims atomically."""

    def __init__(
        self,
        database: Database,
        artifact_store: ContentAddressedStore,
        adapters: StatementAdapterRegistry,
        *,
        password_root: Path,
    ) -> None:
        self._database = database
        self._artifact_store = artifact_store
        self._adapters = adapters
        self._password_root = password_root.expanduser().resolve()

    def extract(
        self,
        *,
        artifact_id: UUID,
        financial_account_id: UUID,
        approved_reprocess_hash: str | None = None,
    ) -> ExtractionOutcome:
        account, artifact = self._load_inputs(financial_account_id, artifact_id)
        if account.statement_adapter_key is None:
            return self._persist_failure(
                account,
                artifact,
                adapter_key="unconfigured",
                parser_version="unconfigured",
                failure=ExtractionFailure("adapter_not_configured", {}),
            )
        try:
            adapter = self._adapters.get(account.statement_adapter_key)
        except StatementAdapterError as error:
            return self._persist_failure(
                account,
                artifact,
                adapter_key=account.statement_adapter_key,
                parser_version="unconfigured",
                failure=ExtractionFailure(error.code, self._safe_details(error.details)),
            )

        existing = self._existing(artifact.id, account.id, adapter.key, adapter.version)
        if existing is not None:
            return self._outcome_from_existing(existing, duplicate=True)
        prior_accepted = self._latest_accepted(artifact.id, account.id)
        if adapter.institution != account.institution:
            return self._persist_failure(
                account,
                artifact,
                adapter_key=adapter.key,
                parser_version=adapter.version,
                failure=ExtractionFailure("institution_mismatch", {}),
            )

        path = self._artifact_store.verified_path(artifact.sha256, artifact.size)
        try:
            passwords = self._load_passwords(account.statement_password_secret)
            candidate = adapter.extract(
                path,
                passwords,
                expected_account_identifier=account.statement_account_identifier,
            )
            validated = self._validate(account, candidate)
        except StatementAdapterError as error:
            return self._persist_failure(
                account,
                artifact,
                adapter_key=adapter.key,
                parser_version=adapter.version,
                failure=ExtractionFailure(error.code, self._safe_details(error.details)),
            )
        except _ValidationFailure as error:
            return self._persist_failure(
                account,
                artifact,
                adapter_key=adapter.key,
                parser_version=adapter.version,
                failure=ExtractionFailure(error.code, error.details),
            )
        except (OSError, ValueError):
            return self._persist_failure(
                account,
                artifact,
                adapter_key=adapter.key,
                parser_version=adapter.version,
                failure=ExtractionFailure("adapter_failed", {}),
            )

        identity_prior = self._latest_accepted_identity(
            account.id,
            validated.candidate.statement_identity,
        )
        if prior_accepted is None:
            prior_accepted = identity_prior
        if (
            identity_prior is not None
            and identity_prior.artifact_id != artifact.id
            and identity_prior.parser_version == adapter.version
            and identity_prior.candidate_hash == validated.candidate_hash
        ):
            return self._outcome_from_existing(identity_prior, duplicate=True)

        reprocess_diff: dict[str, Any] | None = None
        if prior_accepted is not None:
            reprocess_diff = self._reprocess_diff(prior_accepted, validated.candidate)
            if approved_reprocess_hash != validated.candidate_hash:
                failure_code = (
                    "successful_reprocess_requires_approval"
                    if approved_reprocess_hash is None
                    else "reprocess_candidate_changed"
                )
                review_id = self._sync_reprocess_review(
                    artifact.id,
                    account.id,
                    adapter.key,
                    validated.candidate_hash,
                    reprocess_diff,
                )
                return ExtractionOutcome(
                    extraction_id=prior_accepted.id,
                    status=ExtractionStatus.REPROCESS_REQUIRED,
                    claim_count=prior_accepted.claim_count,
                    duplicate=False,
                    failure=ExtractionFailure(
                        failure_code,
                        {
                            "candidate_hash": validated.candidate_hash,
                            "diff": reprocess_diff,
                        },
                    ),
                    review_id=review_id,
                )
        elif approved_reprocess_hash is not None:
            raise ValueError("no successful Extraction exists to reprocess")

        return self._persist_accepted(
            account,
            artifact,
            adapter,
            validated,
            supersedes=prior_accepted,
            reprocess_diff=reprocess_diff,
        )

    def _load_inputs(
        self,
        financial_account_id: UUID,
        artifact_id: UUID,
    ) -> tuple[FinancialAccount, SourceArtifact]:
        with self._database.transaction() as session:
            account = session.get(FinancialAccount, financial_account_id)
            artifact = session.get(SourceArtifact, artifact_id)
            if account is None:
                raise ValueError("Financial Account was not found")
            if artifact is None:
                raise ValueError("Source Artifact was not found")
            if artifact.media_type != "application/pdf":
                raise ValueError("statement Source Artifact must be a PDF")
            return account, artifact

    def _existing(
        self,
        artifact_id: UUID,
        account_id: UUID,
        adapter_key: str,
        parser_version: str,
    ) -> Extraction | None:
        with self._database.transaction() as session:
            return session.scalar(
                select(Extraction).where(
                    Extraction.artifact_id == artifact_id,
                    Extraction.financial_account_id == account_id,
                    Extraction.adapter_key == adapter_key,
                    Extraction.parser_version == parser_version,
                )
            )

    def _latest_accepted(
        self,
        artifact_id: UUID,
        account_id: UUID,
    ) -> Extraction | None:
        with self._database.transaction() as session:
            return session.scalar(
                select(Extraction)
                .where(
                    Extraction.artifact_id == artifact_id,
                    Extraction.financial_account_id == account_id,
                    Extraction.status == ExtractionStatus.ACCEPTED.value,
                )
                .order_by(Extraction.accepted_at.desc(), Extraction.id.desc())
                .limit(1)
            )

    def _latest_accepted_identity(
        self,
        account_id: UUID,
        statement_identity: str,
    ) -> Extraction | None:
        with self._database.transaction() as session:
            return session.scalar(
                select(Extraction)
                .where(
                    Extraction.financial_account_id == account_id,
                    Extraction.statement_identity == statement_identity,
                    Extraction.status == ExtractionStatus.ACCEPTED.value,
                )
                .order_by(Extraction.accepted_at.desc(), Extraction.id.desc())
                .limit(1)
            )

    def _reprocess_diff(
        self,
        prior: Extraction,
        candidate: StatementCandidate,
    ) -> dict[str, Any]:
        with self._database.transaction() as session:
            old_claims = session.scalars(
                select(Claim)
                .where(Claim.extraction_id == prior.id)
                .order_by(Claim.created_at, Claim.id)
            ).all()
        old_fingerprints = [
            self._row_fingerprint(
                claim.raw_description,
                format(claim.posted_amount, "f") if claim.posted_amount is not None else "",
                claim.provider_transaction_date,
                claim.posting_date,
                claim.transaction_kind_hint,
                format(claim.original_amount, "f") if claim.original_amount is not None else None,
                claim.original_currency,
            )
            for claim in old_claims
        ]
        new_fingerprints = [
            self._row_fingerprint(
                row.raw_description,
                row.posted_amount_text,
                row.provider_transaction_date,
                row.posting_date,
                row.transaction_kind_hint,
                row.original_amount_text,
                row.original_currency,
            )
            for row in candidate.rows
        ]
        shared_count = min(len(old_fingerprints), len(new_fingerprints))
        return {
            "previous_extraction_id": str(prior.id),
            "added_rows": max(0, len(new_fingerprints) - len(old_fingerprints)),
            "removed_rows": max(0, len(old_fingerprints) - len(new_fingerprints)),
            "changed_rows": sum(
                old_fingerprints[index] != new_fingerprints[index] for index in range(shared_count)
            ),
            "statement_identity_changed": prior.statement_identity != candidate.statement_identity,
            "period_changed": (
                prior.period_start != candidate.period_start
                or prior.period_end != candidate.period_end
            ),
            "balances_changed": (
                prior.opening_balance
                != self._decimal(candidate.opening_balance_text, "opening_balance")
                or prior.closing_balance
                != self._decimal(candidate.closing_balance_text, "closing_balance")
            ),
        }

    @staticmethod
    def _row_fingerprint(
        description: str,
        posted_amount: str,
        provider_transaction_date: date | None,
        posting_date: date | None,
        kind_hint: str | None,
        original_amount: str | None,
        original_currency: str | None,
    ) -> str:
        encoded = json.dumps(
            {
                "description": description,
                "posted_amount": posted_amount,
                "provider_transaction_date": (
                    provider_transaction_date.isoformat()
                    if provider_transaction_date is not None
                    else None
                ),
                "posting_date": posting_date.isoformat() if posting_date is not None else None,
                "kind_hint": kind_hint,
                "original_amount": original_amount,
                "original_currency": original_currency,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _persist_accepted(
        self,
        account: FinancialAccount,
        artifact: SourceArtifact,
        adapter: StatementAdapter,
        validated: _ValidatedCandidate,
        *,
        supersedes: Extraction | None,
        reprocess_diff: dict[str, Any] | None,
    ) -> ExtractionOutcome:
        now = datetime.now(UTC)
        extraction_id = uuid7()
        with self._database.transaction() as session:
            existing = session.scalar(
                select(Extraction).where(
                    Extraction.artifact_id == artifact.id,
                    Extraction.financial_account_id == account.id,
                    Extraction.adapter_key == adapter.key,
                    Extraction.parser_version == adapter.version,
                )
            )
            if existing is not None:
                return self._outcome_from_existing(existing, duplicate=True)

            candidate = validated.candidate
            extraction = Extraction(
                id=extraction_id,
                artifact_id=artifact.id,
                financial_account_id=account.id,
                adapter_key=adapter.key,
                parser_version=adapter.version,
                status=ExtractionStatus.ACCEPTED.value,
                statement_identity=candidate.statement_identity,
                statement_date=candidate.statement_date,
                period_start=candidate.period_start,
                period_end=candidate.period_end,
                statement_currency=candidate.currency,
                opening_balance=validated.opening_balance,
                closing_balance=validated.closing_balance,
                candidate_row_count=candidate.candidate_row_count,
                claim_count=len(candidate.rows),
                candidate_hash=validated.candidate_hash,
                validation_report={
                    **validated.validation_report,
                    **({"reprocess_diff": reprocess_diff} if reprocess_diff is not None else {}),
                },
                supersedes_extraction_id=supersedes.id if supersedes is not None else None,
                accepted_at=now,
            )
            session.add(extraction)
            session.flush()
            for row, amount, original_amount in zip(
                candidate.rows,
                validated.posted_amounts,
                validated.original_amounts,
                strict=True,
            ):
                self._add_claim(
                    session,
                    extraction,
                    account,
                    artifact,
                    row,
                    amount,
                    candidate.currency,
                    original_amount,
                )
            if supersedes is not None:
                self._cancel_reprocess_review(session, artifact.id, account.id)
            session.flush()
            return ExtractionOutcome(
                extraction_id=extraction.id,
                status=ExtractionStatus.ACCEPTED,
                claim_count=extraction.claim_count,
                duplicate=False,
                failure=None,
                review_id=None,
            )

    def _persist_failure(
        self,
        account: FinancialAccount,
        artifact: SourceArtifact,
        *,
        adapter_key: str,
        parser_version: str,
        failure: ExtractionFailure,
    ) -> ExtractionOutcome:
        with self._database.transaction() as session:
            existing = session.scalar(
                select(Extraction).where(
                    Extraction.artifact_id == artifact.id,
                    Extraction.financial_account_id == account.id,
                    Extraction.adapter_key == adapter_key,
                    Extraction.parser_version == parser_version,
                )
            )
            if existing is not None:
                return self._outcome_from_existing(existing, duplicate=True)

            extraction = Extraction(
                id=uuid7(),
                artifact_id=artifact.id,
                financial_account_id=account.id,
                adapter_key=adapter_key,
                parser_version=parser_version,
                status=ExtractionStatus.FAILED.value,
                claim_count=0,
                failure_code=failure.code,
                validation_report={"failure": failure.details},
                accepted_at=None,
            )
            session.add(extraction)
            session.flush()
            review_id = self._add_failure_review(session, extraction.id, failure.code)
            session.flush()
            return ExtractionOutcome(
                extraction_id=extraction.id,
                status=ExtractionStatus.FAILED,
                claim_count=0,
                duplicate=False,
                failure=failure,
                review_id=review_id,
            )

    @staticmethod
    def _add_claim(
        session: Session,
        extraction: Extraction,
        account: FinancialAccount,
        artifact: SourceArtifact,
        row: StatementRowCandidate,
        amount: Decimal,
        currency: str,
        original_amount: Decimal | None,
    ) -> None:
        claim_id = uuid7()
        session.add(
            Claim(
                id=claim_id,
                claim_type="statement",
                financial_account_id=account.id,
                source_artifact_id=artifact.id,
                extraction_id=extraction.id,
                raw_description=row.raw_description,
                posted_amount=amount,
                posted_currency=currency,
                original_amount=original_amount,
                original_currency=row.original_currency,
                provider_transaction_date=row.provider_transaction_date,
                posting_date=row.posting_date,
                transaction_kind_hint=row.transaction_kind_hint,
            )
        )
        session.add(
            ClaimDispositionEvent(
                id=uuid7(),
                claim_id=claim_id,
                disposition="provisional",
                reason_code="claim_recorded",
            )
        )
        locator = row.locator
        session.add(
            ClaimSourceLocator(
                id=uuid7(),
                claim_id=claim_id,
                page_number=locator.page_number,
                line_number=locator.line_number,
                text_start=locator.text_start,
                text_end=locator.text_end,
                text_sha256=locator.text_sha256,
            )
        )

    def _sync_reprocess_review(
        self,
        artifact_id: UUID,
        account_id: UUID,
        adapter_key: str,
        candidate_hash: str,
        reprocess_diff: dict[str, Any],
    ) -> UUID:
        condition_code = f"statement_reprocess:{account_id}"
        with self._database.transaction() as session:
            review = session.scalar(
                select(PendingReview)
                .where(
                    PendingReview.subject_type == "source_artifact",
                    PendingReview.subject_id == artifact_id,
                    PendingReview.condition_code == condition_code,
                    PendingReview.status == "pending",
                )
                .with_for_update()
            )
            context = {
                "adapter_key": adapter_key,
                "candidate_hash": candidate_hash,
                "diff": reprocess_diff,
            }
            if review is None:
                review = PendingReview(
                    id=uuid7(),
                    subject_type="source_artifact",
                    subject_id=artifact_id,
                    condition_code=condition_code,
                    severity="blocking",
                    status="pending",
                    version=1,
                    allowed_decisions=["approve_exact_diff", "keep_previous_extraction"],
                    context=context,
                )
                event_type = "created"
            else:
                review.version += 1
                review.context = context
                review.updated_at = datetime.now(UTC)
                event_type = "synchronized"
            session.add(review)
            session.flush()
            session.add(
                ReviewEvent(
                    id=uuid7(),
                    review_id=review.id,
                    version=review.version,
                    event_type=event_type,
                )
            )
            session.flush()
            return review.id

    @staticmethod
    def _cancel_reprocess_review(
        session: Session,
        artifact_id: UUID,
        account_id: UUID,
    ) -> None:
        condition_code = f"statement_reprocess:{account_id}"
        review = session.scalar(
            select(PendingReview)
            .where(
                PendingReview.subject_type == "source_artifact",
                PendingReview.subject_id == artifact_id,
                PendingReview.condition_code == condition_code,
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

    @staticmethod
    def _add_failure_review(session: Session, extraction_id: UUID, failure_code: str) -> UUID:
        review_id = uuid7()
        review = PendingReview(
            id=review_id,
            subject_type="extraction",
            subject_id=extraction_id,
            condition_code=f"statement_extraction:{failure_code}",
            severity="blocking",
            status="pending",
            version=1,
            allowed_decisions=["retry_after_adapter_update", "exclude_source_artifact"],
            context={"failure_code": failure_code},
        )
        session.add(review)
        session.flush()
        session.add(
            ReviewEvent(
                id=uuid7(),
                review_id=review_id,
                version=1,
                event_type="created",
            )
        )
        return review_id

    @staticmethod
    def _validate(
        account: FinancialAccount,
        candidate: StatementCandidate,
    ) -> _ValidatedCandidate:
        if not candidate.statement_identity.strip():
            raise _ValidationFailure("statement_identity_missing")
        if account.statement_account_identifier is None:
            raise _ValidationFailure("account_identifier_not_configured")
        if candidate.account_identifier != account.statement_account_identifier:
            raise _ValidationFailure(
                "account_mismatch",
                {
                    "expected_configured": True,
                    "observed_present": bool(candidate.account_identifier),
                },
            )
        if candidate.currency != account.default_currency:
            raise _ValidationFailure(
                "statement_currency_mismatch",
                {"expected_currency": account.default_currency},
            )
        if candidate.period_start > candidate.period_end:
            raise _ValidationFailure("statement_period_invalid")
        if not candidate.period_start <= candidate.statement_date <= candidate.period_end:
            raise _ValidationFailure("statement_date_outside_period")
        if candidate.candidate_row_count != len(candidate.rows):
            raise _ValidationFailure(
                "row_coverage_mismatch",
                {
                    "candidate_row_count": candidate.candidate_row_count,
                    "parsed_row_count": len(candidate.rows),
                },
            )

        opening = StatementExtraction._decimal(candidate.opening_balance_text, "opening_balance")
        closing = StatementExtraction._decimal(candidate.closing_balance_text, "closing_balance")
        amounts: list[Decimal] = []
        original_amounts: list[Decimal | None] = []
        locator_keys: set[tuple[int, int, int, int]] = set()
        for row in candidate.rows:
            if not row.raw_description.strip():
                raise _ValidationFailure("row_description_missing")
            amount = StatementExtraction._decimal(row.posted_amount_text, "posted_amount")
            if (row.original_amount_text is None) != (row.original_currency is None):
                raise _ValidationFailure("original_money_incomplete")
            original_amount: Decimal | None = None
            if row.original_amount_text is not None and row.original_currency is not None:
                if re.fullmatch(r"[A-Z]{3}", row.original_currency) is None:
                    raise _ValidationFailure("original_currency_invalid")
                original_amount = StatementExtraction._decimal(
                    row.original_amount_text,
                    "original_amount",
                )
                if original_amount == 0:
                    raise _ValidationFailure("zero_original_amount_row")
            if amount == 0:
                raise _ValidationFailure("zero_amount_row")
            if (
                row.transaction_kind_hint is not None
                and row.transaction_kind_hint not in _KNOWN_KINDS
            ):
                raise _ValidationFailure("transaction_kind_unknown")
            # Provider dates describe when the activity occurred, not necessarily the
            # billing-cycle membership. A late-presented purchase can predate the
            # period while still appearing on this statement; it must never be after it.
            if row.provider_transaction_date > candidate.statement_date:
                raise _ValidationFailure("transaction_date_outside_statement")
            if row.posting_date > candidate.statement_date:
                raise _ValidationFailure("posting_date_outside_statement")
            locator_key = (
                row.locator.page_number,
                row.locator.line_number,
                row.locator.text_start,
                row.locator.text_end,
            )
            if locator_key in locator_keys:
                raise _ValidationFailure("duplicate_source_locator")
            locator_keys.add(locator_key)
            amounts.append(amount)
            original_amounts.append(original_amount)

        activity_total = sum(amounts, Decimal(0))
        if account.kind is FinancialAccountKind.CREDIT_CARD:
            calculated_closing = opening - activity_total
        else:
            calculated_closing = opening + activity_total
        if calculated_closing != closing:
            raise _ValidationFailure(
                "balance_validation_failed",
                {
                    "row_count": len(amounts),
                    "calculated_matches_reported": False,
                },
            )

        candidate_hash = StatementExtraction._candidate_hash(candidate)
        return _ValidatedCandidate(
            candidate=candidate,
            opening_balance=opening,
            closing_balance=closing,
            posted_amounts=tuple(amounts),
            original_amounts=tuple(original_amounts),
            candidate_hash=candidate_hash,
            validation_report={
                "account_match": True,
                "currency_match": True,
                "row_coverage": {
                    "candidate": candidate.candidate_row_count,
                    "parsed": len(candidate.rows),
                },
                "balance_validation": True,
                "provenance_complete": True,
                "original_currency_evidence_count": sum(
                    original_amount is not None for original_amount in original_amounts
                ),
            },
        )

    @staticmethod
    def _decimal(value: str, field_name: str) -> Decimal:
        if type(value) is not str or _DECIMAL_PATTERN.fullmatch(value) is None:
            raise _ValidationFailure("invalid_decimal_string", {"field": field_name})
        try:
            amount = Decimal(value)
        except InvalidOperation as error:
            raise _ValidationFailure("invalid_decimal_string", {"field": field_name}) from error
        if not amount.is_finite():
            raise _ValidationFailure("invalid_decimal_string", {"field": field_name})
        return amount

    @staticmethod
    def _candidate_hash(candidate: StatementCandidate) -> str:
        encoded = json.dumps(
            asdict(candidate),
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: value.isoformat() if isinstance(value, date) else value,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _load_passwords(self, reference: str | None) -> tuple[SecretStr, ...]:
        if reference is None:
            return ()
        if _SECRET_NAME_PATTERN.fullmatch(reference) is None:
            raise ValueError("invalid statement password secret reference")
        path = self._password_root / reference
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise ValueError("statement password secret must be a regular file")
        if metadata.st_mode & 0o077:
            raise ValueError("statement password secret permissions are too broad")
        password = path.read_text(encoding="utf-8").rstrip("\r\n")
        if not password:
            raise ValueError("statement password secret is empty")
        return (SecretStr(password),)

    @staticmethod
    def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in details.items():
            if key in {
                "row_count",
                "page_count",
                "candidate_row_count",
                "parsed_row_count",
                "password_required",
                "ocr_required",
            } and isinstance(value, bool | int):
                safe[key] = value
        fields = _safe_metadata_fields(details.get("fields"))
        if fields:
            safe["fields"] = fields
        return safe

    @staticmethod
    def _outcome_from_existing(extraction: Extraction, *, duplicate: bool) -> ExtractionOutcome:
        failure = (
            ExtractionFailure(
                extraction.failure_code,
                dict(extraction.validation_report.get("failure", {})),
            )
            if extraction.failure_code is not None
            else None
        )
        return ExtractionOutcome(
            extraction_id=extraction.id,
            status=ExtractionStatus(extraction.status),
            claim_count=extraction.claim_count,
            duplicate=duplicate,
            failure=failure,
            review_id=None,
        )
