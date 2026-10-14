"""Phase 1 persistence records and database invariants."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column
from uuid6 import uuid7

from billzebub.persistence.base import Base


class FinancialAccountKind(StrEnum):
    CREDIT_CARD = "credit_card"
    PAYLAH = "paylah"
    DEPOSIT = "deposit"


class AuditActorKind(StrEnum):
    OWNER = "owner"
    AGENT = "agent"
    INTEGRATION = "integration"
    SYSTEM = "system"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _enum(enum_class: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class FinancialAccount(Base):
    __tablename__ = "financial_account"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    institution: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[FinancialAccountKind] = mapped_column(
        _enum(FinancialAccountKind, "financial_account_kind"), nullable=False
    )
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    statement_adapter_key: Mapped[str | None] = mapped_column(String(120))
    statement_account_identifier: Mapped[str | None] = mapped_column(String(255))
    statement_password_secret: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("default_currency ~ '^[A-Z]{3}$'", name="default_currency_iso_style"),
    )


class FinancialAccountAlias(Base):
    __tablename__ = "financial_account_alias"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    financial_account_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    alias_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    value: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("alias_kind IN ('apple_wallet_card')", name="alias_kind_known"),
        CheckConstraint("length(btrim(value)) > 0", name="value_present"),
        CheckConstraint("length(btrim(normalized_value)) > 0", name="normalized_value_present"),
        UniqueConstraint(
            "alias_kind", "normalized_value", name="uq_financial_account_alias_kind_value"
        ),
    )


class Category(Base):
    __tablename__ = "category"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    parent_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("category.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_category_parent_name"),
        Index(
            "uq_category_top_level_name",
            "name",
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )


class AuditActor(Base):
    __tablename__ = "audit_actor"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    kind: Mapped[AuditActorKind] = mapped_column(
        _enum(AuditActorKind, "audit_actor_kind"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    external_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("kind", "external_key", name="uq_audit_actor_kind_external_key"),
    )


class IntegrationToken(Base):
    __tablename__ = "integration_token"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    actor_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("audit_actor.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_record"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    principal: Mapped[str] = mapped_column(String(160), nullable=False)
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_digest: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "principal", "operation", "key", name="uq_idempotency_principal_operation_key"
        ),
    )


class DurableJob(Base):
    __tablename__ = "durable_job"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    kind: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "durable_job_status"),
        nullable=False,
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        Index(
            "uq_durable_job_active_dedupe",
            "kind",
            "dedupe_key",
            unique=True,
            postgresql_where=text(
                "dedupe_key IS NOT NULL AND status IN ('queued'::durable_job_status, "
                "'running'::durable_job_status)"
            ),
        ),
        Index("ix_durable_job_due", "status", "available_at"),
    )


class SourceArtifact(Base):
    __tablename__ = "source_artifact"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        CheckConstraint("size >= 0", name="size_nonnegative"),
    )


class Extraction(Base):
    __tablename__ = "extraction"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    artifact_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("source_artifact.id", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_account_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_account.id", ondelete="RESTRICT"),
    )
    adapter_key: Mapped[str | None] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    statement_identity: Mapped[str | None] = mapped_column(String(255))
    statement_date: Mapped[date | None] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    statement_currency: Mapped[str | None] = mapped_column(String(3))
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric())
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric())
    candidate_row_count: Mapped[int | None] = mapped_column(Integer)
    claim_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    candidate_hash: Mapped[str | None] = mapped_column(String(64))
    failure_code: Mapped[str | None] = mapped_column(String(120))
    validation_report: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    supersedes_extraction_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("extraction.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('accepted', 'failed')", name="status_known"),
        CheckConstraint("claim_count >= 0", name="claim_count_nonnegative"),
        CheckConstraint(
            "statement_currency IS NULL OR statement_currency ~ '^[A-Z]{3}$'",
            name="statement_currency_iso_style",
        ),
        CheckConstraint(
            "candidate_hash IS NULL OR candidate_hash ~ '^[0-9a-f]{64}$'",
            name="candidate_hash_hex",
        ),
        CheckConstraint(
            "(status = 'accepted' AND failure_code IS NULL AND accepted_at IS NOT NULL) OR "
            "(status = 'failed' AND failure_code IS NOT NULL AND accepted_at IS NULL)",
            name="status_fields_consistent",
        ),
        CheckConstraint(
            "dismissed_at IS NULL OR status = 'failed'",
            name="dismissed_at_failed_only",
        ),
        Index("ix_extraction_artifact_created", "artifact_id", "created_at"),
        Index(
            "uq_extraction_artifact_account_adapter_version",
            "artifact_id",
            "financial_account_id",
            "adapter_key",
            "parser_version",
            unique=True,
            postgresql_where=text("financial_account_id IS NOT NULL AND adapter_key IS NOT NULL"),
        ),
        Index(
            "uq_extraction_artifact_adapter_version_unmapped",
            "artifact_id",
            "adapter_key",
            "parser_version",
            unique=True,
            postgresql_where=text("financial_account_id IS NULL AND adapter_key IS NOT NULL"),
        ),
    )


class Claim(Base):
    __tablename__ = "claim"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    claim_type: Mapped[str] = mapped_column(String(20), nullable=False)
    financial_account_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_artifact_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("source_artifact.id", ondelete="RESTRICT"),
        nullable=False,
    )
    extraction_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("extraction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_amount: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    authorized_currency: Mapped[str | None] = mapped_column(String(3))
    posted_amount: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    posted_currency: Mapped[str | None] = mapped_column(String(3))
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(), nullable=True)
    original_currency: Mapped[str | None] = mapped_column(String(3))
    occurrence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_transaction_date: Mapped[date | None] = mapped_column(Date)
    posting_date: Mapped[date | None] = mapped_column(Date)
    transaction_kind_hint: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("claim_type IN ('real_time', 'statement')", name="type_known"),
        CheckConstraint(
            "(authorized_amount IS NULL) = (authorized_currency IS NULL)",
            name="authorized_money_complete",
        ),
        CheckConstraint(
            "(posted_amount IS NULL) = (posted_currency IS NULL)",
            name="posted_money_complete",
        ),
        CheckConstraint(
            "authorized_currency IS NULL OR authorized_currency ~ '^[A-Z]{3}$'",
            name="authorized_currency_iso_style",
        ),
        CheckConstraint(
            "posted_currency IS NULL OR posted_currency ~ '^[A-Z]{3}$'",
            name="posted_currency_iso_style",
        ),
        CheckConstraint(
            "(original_amount IS NULL) = (original_currency IS NULL)",
            name="original_money_complete",
        ),
        CheckConstraint(
            "original_currency IS NULL OR original_currency ~ '^[A-Z]{3}$'",
            name="original_currency_iso_style",
        ),
        CheckConstraint(
            "(claim_type = 'real_time' AND authorized_amount IS NOT NULL AND "
            "occurrence_at IS NOT NULL) OR "
            "(claim_type = 'statement' AND posted_amount IS NOT NULL AND "
            "posting_date IS NOT NULL)",
            name="required_evidence_present",
        ),
        Index("ix_claim_account_type_created", "financial_account_id", "claim_type", "created_at"),
    )


class ClaimDispositionEvent(Base):
    __tablename__ = "claim_disposition_event"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    claim_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("claim.id", ondelete="RESTRICT"),
        nullable=False,
    )
    disposition: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("audit_actor.id", ondelete="RESTRICT")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "disposition IN ('provisional', 'confirmed', 'unconfirmed', 'excluded')",
            name="disposition_known",
        ),
        Index("ix_claim_disposition_event_claim_time", "claim_id", "occurred_at", "id"),
    )


class ClaimCategory(Base):
    """One catalog Category applied to a claim-only provisional Real-time Claim."""

    __tablename__ = "claim_category"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    claim_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("claim.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("claim_id", name="uq_claim_category_claim_id"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_style"),
    )


class ClaimSourceLocator(Base):
    __tablename__ = "claim_source_locator"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    claim_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("claim.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text_start: Mapped[int] = mapped_column(Integer, nullable=False)
    text_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("page_number > 0", name="page_number_positive"),
        CheckConstraint("line_number > 0", name="line_number_positive"),
        CheckConstraint("text_start >= 0 AND text_end > text_start", name="text_span_valid"),
        CheckConstraint(
            "text_sha256 IS NULL OR text_sha256 ~ '^[0-9a-f]{64}$'",
            name="text_sha256_hex",
        ),
    )


class FinancialTransaction(Base):
    __tablename__ = "financial_transaction"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    financial_account_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (CheckConstraint("current_version > 0", name="current_version_positive"),)


class TransactionVersion(Base):
    __tablename__ = "transaction_version"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    transaction_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    posted_amount: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    posted_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    authorized_amount: Mapped[Decimal | None] = mapped_column(Numeric())
    authorized_currency: Mapped[str | None] = mapped_column(String(3))
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    occurrence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_transaction_date: Mapped[date | None] = mapped_column(Date)
    posting_date: Mapped[date] = mapped_column(Date, nullable=False)
    counterparty: Mapped[str] = mapped_column(String(300), nullable=False)
    supersedes_version_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("transaction_version.id", ondelete="RESTRICT"),
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("audit_actor.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("transaction_id", "version", name="uq_transaction_version_number"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "kind IN ('expense', 'income', 'transfer', 'refund', 'reimbursement', "
            "'cash_withdrawal')",
            name="kind_known",
        ),
        CheckConstraint("posted_amount <> 0", name="posted_amount_nonzero"),
        CheckConstraint("posted_currency ~ '^[A-Z]{3}$'", name="posted_currency_iso_style"),
        CheckConstraint(
            "(authorized_amount IS NULL) = (authorized_currency IS NULL)",
            name="authorized_money_complete",
        ),
        CheckConstraint(
            "authorized_currency IS NULL OR authorized_currency ~ '^[A-Z]{3}$'",
            name="authorized_currency_iso_style",
        ),
    )


class TransactionClaim(Base):
    __tablename__ = "transaction_claim"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    transaction_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    claim_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("claim.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("transaction_id", "role", name="uq_transaction_claim_role"),
        CheckConstraint("role IN ('statement', 'real_time')", name="role_known"),
    )


class CorrectionEvent(Base):
    __tablename__ = "correction_event"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    transaction_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    prior_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("transaction_version.id", ondelete="RESTRICT"),
        nullable=False,
    )
    replacement_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("transaction_version.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("audit_actor.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (CheckConstraint("length(btrim(reason)) > 0", name="reason_present"),)


class CategorySplit(Base):
    __tablename__ = "category_split"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    transaction_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("transaction_version.id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("category.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "transaction_version_id", "category_id", name="uq_category_split_version_category"
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_style"),
    )


class LedgerAccount(Base):
    __tablename__ = "ledger_account"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    account_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    financial_account_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_account.id", ondelete="RESTRICT"),
        unique=True,
    )
    category_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("category.id", ondelete="RESTRICT"),
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "account_type IN ('financial', 'category', 'income', 'transfer', "
            "'offset_unallocated', 'offset_allocated')",
            name="account_type_known",
        ),
        CheckConstraint(
            "(account_type = 'financial' AND financial_account_id IS NOT NULL AND "
            "category_id IS NULL) OR "
            "(account_type = 'category' AND category_id IS NOT NULL AND "
            "financial_account_id IS NULL) OR "
            "(account_type NOT IN ('financial', 'category') AND financial_account_id IS NULL "
            "AND category_id IS NULL)",
            name="reference_matches_type",
        ),
    )


class OffsetAllocation(Base):
    __tablename__ = "offset_allocation"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    offset_transaction_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    expense_transaction_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("audit_actor.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "offset_transaction_id <> expense_transaction_id", name="transactions_differ"
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_style"),
        Index("ix_offset_allocation_offset_transaction", "offset_transaction_id", "created_at"),
        Index("ix_offset_allocation_expense_transaction", "expense_transaction_id", "created_at"),
    )


class Journal(Base):
    __tablename__ = "journal"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    transaction_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("transaction_version.id", ondelete="RESTRICT"),
        nullable=False,
    )
    journal_type: Mapped[str] = mapped_column(String(30), nullable=False)
    offset_allocation_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("offset_allocation.id", ondelete="RESTRICT"),
        unique=True,
    )
    reverses_journal_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("journal.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "journal_type IN ('confirmation', 'correction_reversal', "
            "'correction_replacement', 'offset_allocation')",
            name="journal_type_known",
        ),
    )


class LedgerPosting(Base):
    __tablename__ = "ledger_posting"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    journal_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("journal.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ledger_account_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("ledger_account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("direction IN ('debit', 'credit')", name="direction_known"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_style"),
        Index("ix_ledger_posting_journal_id", "journal_id", "id"),
    )


class PendingReview(Base):
    __tablename__ = "pending_review"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    condition_code: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    allowed_decisions: Mapped[list[str]] = mapped_column(ARRAY(String(120)), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("severity IN ('attention', 'blocking')", name="severity_known"),
        CheckConstraint("status IN ('pending', 'resolved', 'cancelled')", name="status_known"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("cardinality(allowed_decisions) > 0", name="decisions_present"),
        Index(
            "uq_pending_review_active_condition",
            "subject_type",
            "subject_id",
            "condition_code",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_pending_review_status_severity_created", "status", "severity", "created_at"),
    )


class ReviewEvent(Base):
    __tablename__ = "review_event"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    review_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("pending_review.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    decision: Mapped[str | None] = mapped_column(String(120))
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("audit_actor.id", ondelete="RESTRICT")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("review_id", "version", name="uq_review_event_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "event_type IN ('created', 'synchronized', 'resolved', 'cancelled', "
            "'reextract_requested')",
            name="event_type_known",
        ),
        CheckConstraint(
            "(event_type = 'resolved' AND decision IS NOT NULL) OR "
            "(event_type <> 'resolved' AND decision IS NULL)",
            name="decision_matches_event",
        ),
    )


class ReferenceExchangeRate(Base):
    __tablename__ = "reference_exchange_rate"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "rate_date",
            "base_currency",
            "quote_currency",
            name="uq_reference_exchange_rate_date_pair",
        ),
        CheckConstraint("base_currency ~ '^[A-Z]{3}$'", name="base_currency_iso_style"),
        CheckConstraint("quote_currency ~ '^[A-Z]{3}$'", name="quote_currency_iso_style"),
        CheckConstraint("base_currency <> quote_currency", name="currencies_differ"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("length(btrim(source_name)) > 0", name="source_present"),
    )


class ReconciledClaimPair(Base):
    __tablename__ = "reconciled_claim_pair"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    real_time_claim_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("claim.id", ondelete="RESTRICT"),
        nullable=False,
    )
    statement_claim_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("claim.id", ondelete="RESTRICT"),
        nullable=False,
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    decision_source: Mapped[str] = mapped_column(String(20), nullable=False)
    review_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("pending_review.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("audit_actor.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("real_time_claim_id", name="uq_reconciled_claim_pair_real_time_claim"),
        UniqueConstraint("statement_claim_id", name="uq_reconciled_claim_pair_statement_claim"),
        UniqueConstraint("transaction_id", name="uq_reconciled_claim_pair_transaction"),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        CheckConstraint("decision_source IN ('automatic', 'review')", name="decision_source_known"),
        CheckConstraint(
            "(decision_source = 'review') = (review_id IS NOT NULL)",
            name="review_matches_source",
        ),
        Index("ix_reconciled_claim_pair_statement_created", "statement_claim_id", "created_at"),
    )


class RejectedClaimPair(Base):
    __tablename__ = "rejected_claim_pair"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    real_time_claim_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("claim.id", ondelete="RESTRICT"), nullable=False
    )
    statement_claim_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("claim.id", ondelete="RESTRICT"), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False)
    review_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("pending_review.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("audit_actor.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "real_time_claim_id", "statement_claim_id", name="uq_rejected_claim_pair_claims"
        ),
        CheckConstraint("length(btrim(reason_code)) > 0", name="reason_present"),
        Index("ix_rejected_claim_pair_statement_created", "statement_claim_id", "created_at"),
    )


class InboxFileObservation(Base):
    __tablename__ = "inbox_file_observation"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    financial_account_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    modified_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    artifact_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("source_artifact.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "financial_account_id",
            "file_name",
            "size",
            "modified_ns",
            name="uq_inbox_file_observation_fingerprint",
        ),
        CheckConstraint("size >= 0", name="size_nonnegative"),
        CheckConstraint("modified_ns >= 0", name="modified_ns_nonnegative"),
        CheckConstraint("status IN ('observed', 'captured')", name="status_known"),
        Index("ix_inbox_file_observation_status", "status", "first_observed_at"),
    )


class JevCategorizationAttempt(Base):
    __tablename__ = "jev_categorization_attempt"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    transaction_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
    )
    claim_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("claim.id", ondelete="RESTRICT"),
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    counterparty: Mapped[str] = mapped_column(String(300), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    choice: Mapped[str | None] = mapped_column(String(500))
    skip_reason: Mapped[str | None] = mapped_column(String(40))
    choice_confidence: Mapped[Decimal | None] = mapped_column(Numeric())
    noul: Mapped[Decimal | None] = mapped_column(Numeric())
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("category.id", ondelete="RESTRICT")
    )
    category_name: Mapped[str | None] = mapped_column(String(120))
    error_class: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        CheckConstraint("length(btrim(model)) > 0", name="model_present"),
        CheckConstraint("length(btrim(counterparty)) > 0", name="counterparty_present"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_style"),
        CheckConstraint(
            "kind IN ('expense', 'income', 'transfer', 'refund', 'reimbursement', "
            "'cash_withdrawal')",
            name="kind_known",
        ),
        CheckConstraint(
            "choice_confidence IS NULL OR (choice_confidence >= 0 AND choice_confidence <= 1)",
            name="choice_confidence_range",
        ),
        CheckConstraint(
            "noul IS NULL OR (noul >= 0 AND noul <= 1)",
            name="noul_range",
        ),
        CheckConstraint("action IN ('apply', 'skip')", name="action_known"),
        CheckConstraint(
            "skip_reason IS NULL OR skip_reason IN ("
            "'low_confidence', 'missing_choice', 'missing_confidence', "
            "'unknown_category', 'ambiguous_category', 'jev_unavailable', 'empty_catalog')",
            name="skip_reason_known",
        ),
        CheckConstraint(
            "(action = 'apply' AND skip_reason IS NULL) OR "
            "(action = 'skip' AND skip_reason IS NOT NULL)",
            name="skip_reason_matches_action",
        ),
        CheckConstraint(
            "(action = 'apply' AND category_id IS NOT NULL AND category_name IS NOT NULL "
            "AND length(btrim(category_name)) > 0) OR "
            "(action = 'skip' AND category_id IS NULL AND category_name IS NULL)",
            name="category_matches_action",
        ),
        CheckConstraint(
            "(transaction_id IS NOT NULL AND claim_id IS NULL) OR "
            "(transaction_id IS NULL AND claim_id IS NOT NULL)",
            name="subject_exclusive",
        ),
        Index(
            "ix_jev_categorization_attempt_transaction_attempted",
            "transaction_id",
            "attempted_at",
            "id",
        ),
        Index(
            "ix_jev_categorization_attempt_claim_attempted",
            "claim_id",
            "attempted_at",
            "id",
        ),
    )


class ArtifactArrival(Base):
    __tablename__ = "artifact_arrival"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    artifact_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("source_artifact.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    original_name: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (Index("ix_artifact_arrival_artifact_received", "artifact_id", "received_at"),)


class RecurringSeries(Base):
    """A repeating spend pattern the owner can confirm, pause, or dismiss."""

    __tablename__ = "recurring_series"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    counterparty: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_counterparty: Mapped[str] = mapped_column(String(300), nullable=False)
    cluster_key: Mapped[str] = mapped_column(String(360), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(), nullable=False)
    amount_min: Mapped[Decimal | None] = mapped_column(Numeric())
    amount_max: Mapped[Decimal | None] = mapped_column(Numeric())
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cadence: Mapped[str] = mapped_column(String(20), nullable=False)
    interval_days: Mapped[int | None] = mapped_column(Integer)
    next_expected_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("category.id", ondelete="RESTRICT"),
    )
    primary_account_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_account.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric())
    last_matched_tx_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
    )
    notes: Mapped[str | None] = mapped_column(Text)
    missed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("cluster_key", name="uq_recurring_series_cluster_key"),
        CheckConstraint("length(btrim(counterparty)) > 0", name="counterparty_present"),
        CheckConstraint(
            "length(btrim(normalized_counterparty)) > 0",
            name="normalized_counterparty_present",
        ),
        CheckConstraint("length(btrim(cluster_key)) > 0", name="cluster_key_present"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "(amount_min IS NULL AND amount_max IS NULL) OR "
            "(amount_min IS NOT NULL AND amount_max IS NOT NULL AND amount_min > 0 "
            "AND amount_min <= amount AND amount <= amount_max)",
            name="amount_bounds",
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso_style"),
        CheckConstraint(
            "cadence IN ('weekly', 'monthly', 'yearly', 'custom_days')",
            name="cadence_known",
        ),
        CheckConstraint(
            "(cadence = 'custom_days' AND interval_days IS NOT NULL AND interval_days > 0) OR "
            "(cadence IN ('weekly', 'monthly', 'yearly') AND interval_days IS NULL)",
            name="cadence_interval",
        ),
        CheckConstraint(
            "status IN ('proposed', 'active', 'paused', 'ended', 'dismissed')",
            name="status_known",
        ),
        CheckConstraint("source IN ('detected', 'manual')", name="source_known"),
        CheckConstraint(
            "(source = 'manual' AND confidence IS NULL) OR "
            "(source = 'detected' AND confidence IS NOT NULL AND confidence >= 0 "
            "AND confidence <= 1)",
            name="confidence_matches_source",
        ),
        CheckConstraint("notes IS NULL OR length(btrim(notes)) > 0", name="notes_present"),
        Index("ix_recurring_series_status_next_expected", "status", "next_expected_date"),
    )


class RecurringOccurrence(Base):
    """Link from a Recurring Series to one settled Transaction."""

    __tablename__ = "recurring_occurrence"

    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, default=uuid7)
    series_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("recurring_series.id", ondelete="RESTRICT"),
        nullable=False,
    )
    transaction_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("financial_transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    match_kind: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "series_id",
            "transaction_id",
            name="uq_recurring_occurrence_series_transaction",
        ),
        UniqueConstraint("transaction_id", name="uq_recurring_occurrence_transaction_id"),
        CheckConstraint("match_kind IN ('auto', 'manual')", name="match_kind_known"),
        Index("ix_recurring_occurrence_series_matched", "series_id", "matched_at"),
    )
