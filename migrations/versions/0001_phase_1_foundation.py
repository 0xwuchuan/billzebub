"""Create the Phase 1 persistence foundation.

Revision ID: 0001
Revises:
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

financial_account_kind = postgresql.ENUM(
    "credit_card", "paylah", "deposit", name="financial_account_kind"
)
audit_actor_kind = postgresql.ENUM(
    "owner", "agent", "integration", "system", name="audit_actor_kind"
)
durable_job_status = postgresql.ENUM(
    "queued", "running", "succeeded", "failed", name="durable_job_status"
)


def upgrade() -> None:
    financial_account_kind.create(op.get_bind(), checkfirst=True)
    audit_actor_kind.create(op.get_bind(), checkfirst=True)
    durable_job_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "financial_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("institution", sa.String(length=80), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "credit_card",
                "paylah",
                "deposit",
                name="financial_account_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("default_currency", sa.String(length=3), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "default_currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_financial_account_default_currency_iso_style"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_account")),
        sa.UniqueConstraint("slug", name=op.f("uq_financial_account_slug")),
    )

    op.create_table(
        "category",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["category.id"],
            name=op.f("fk_category_parent_id_category"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category")),
        sa.UniqueConstraint("parent_id", "name", name="uq_category_parent_name"),
    )
    op.create_index(
        "uq_category_top_level_name",
        "category",
        ["name"],
        unique=True,
        postgresql_where=sa.text("parent_id IS NULL"),
    )

    op.create_table(
        "audit_actor",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "owner",
                "agent",
                "integration",
                "system",
                name="audit_actor_kind",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_actor")),
        sa.UniqueConstraint("kind", "external_key", name="uq_audit_actor_kind_external_key"),
    )

    op.create_table(
        "integration_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_prefix", sa.String(length=20), nullable=False),
        sa.Column("token_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["audit_actor.id"],
            name=op.f("fk_integration_token_actor_id_audit_actor"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integration_token")),
        sa.UniqueConstraint("token_digest", name=op.f("uq_integration_token_token_digest")),
        sa.UniqueConstraint("token_prefix", name=op.f("uq_integration_token_token_prefix")),
    )

    op.create_table(
        "idempotency_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal", sa.String(length=160), nullable=False),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_digest", sa.LargeBinary(length=32), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_record")),
        sa.UniqueConstraint(
            "principal",
            "operation",
            "key",
            name="uq_idempotency_principal_operation_key",
        ),
    )

    op.create_table(
        "durable_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=120), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="durable_job_status",
                create_type=False,
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_durable_job_attempts_nonnegative")),
        sa.CheckConstraint("max_attempts > 0", name=op.f("ck_durable_job_max_attempts_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_durable_job")),
    )
    op.create_index("ix_durable_job_due", "durable_job", ["status", "available_at"], unique=False)
    op.create_index(
        "uq_durable_job_active_dedupe",
        "durable_job",
        ["kind", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text(
            "dedupe_key IS NOT NULL AND status IN ('queued'::durable_job_status, "
            "'running'::durable_job_status)"
        ),
    )

    op.create_table(
        "source_artifact",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=160), nullable=False),
        sa.Column("content_path", sa.Text(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_source_artifact_sha256_hex")),
        sa.CheckConstraint("size >= 0", name=op.f("ck_source_artifact_size_nonnegative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_artifact")),
        sa.UniqueConstraint("content_path", name=op.f("uq_source_artifact_content_path")),
        sa.UniqueConstraint("sha256", name=op.f("uq_source_artifact_sha256")),
    )

    op.create_table(
        "artifact_arrival",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["source_artifact.id"],
            name=op.f("fk_artifact_arrival_artifact_id_source_artifact"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_arrival")),
    )
    op.create_index(
        "ix_artifact_arrival_artifact_received",
        "artifact_arrival",
        ["artifact_id", "received_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_artifact_arrival_artifact_received", table_name="artifact_arrival")
    op.drop_table("artifact_arrival")
    op.drop_table("source_artifact")
    op.drop_index("uq_durable_job_active_dedupe", table_name="durable_job")
    op.drop_index("ix_durable_job_due", table_name="durable_job")
    op.drop_table("durable_job")
    op.drop_table("idempotency_record")
    op.drop_table("integration_token")
    op.drop_table("audit_actor")
    op.drop_index("uq_category_top_level_name", table_name="category")
    op.drop_table("category")
    op.drop_table("financial_account")

    durable_job_status.drop(op.get_bind(), checkfirst=True)
    audit_actor_kind.drop(op.get_bind(), checkfirst=True)
    financial_account_kind.drop(op.get_bind(), checkfirst=True)
