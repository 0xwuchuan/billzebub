"""Add strict statement Extraction evidence and provenance.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "financial_account",
        sa.Column("statement_adapter_key", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "financial_account",
        sa.Column("statement_account_identifier", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "financial_account",
        sa.Column("statement_password_secret", sa.String(length=120), nullable=True),
    )

    op.add_column(
        "extraction",
        sa.Column("financial_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("extraction", sa.Column("adapter_key", sa.String(length=120), nullable=True))
    op.add_column(
        "extraction", sa.Column("statement_identity", sa.String(length=255), nullable=True)
    )
    op.add_column("extraction", sa.Column("statement_date", sa.Date(), nullable=True))
    op.add_column("extraction", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("extraction", sa.Column("period_end", sa.Date(), nullable=True))
    op.add_column("extraction", sa.Column("statement_currency", sa.String(length=3), nullable=True))
    op.add_column("extraction", sa.Column("opening_balance", sa.Numeric(), nullable=True))
    op.add_column("extraction", sa.Column("closing_balance", sa.Numeric(), nullable=True))
    op.add_column("extraction", sa.Column("candidate_row_count", sa.Integer(), nullable=True))
    op.add_column(
        "extraction",
        sa.Column("claim_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("extraction", sa.Column("candidate_hash", sa.String(length=64), nullable=True))
    op.add_column("extraction", sa.Column("failure_code", sa.String(length=120), nullable=True))
    op.add_column(
        "extraction",
        sa.Column(
            "validation_report",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "extraction",
        sa.Column("supersedes_extraction_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_extraction_financial_account_id_financial_account"),
        "extraction",
        "financial_account",
        ["financial_account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_extraction_supersedes_extraction_id_extraction"),
        "extraction",
        "extraction",
        ["supersedes_extraction_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_extraction_claim_count_nonnegative"),
        "extraction",
        "claim_count >= 0",
    )
    op.create_check_constraint(
        op.f("ck_extraction_statement_currency_iso_style"),
        "extraction",
        "statement_currency IS NULL OR statement_currency ~ '^[A-Z]{3}$'",
    )
    op.create_check_constraint(
        op.f("ck_extraction_candidate_hash_hex"),
        "extraction",
        "candidate_hash IS NULL OR candidate_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        op.f("ck_extraction_status_fields_consistent"),
        "extraction",
        "(status = 'accepted' AND failure_code IS NULL AND accepted_at IS NOT NULL) OR "
        "(status = 'failed' AND failure_code IS NOT NULL AND accepted_at IS NULL)",
    )
    op.create_index(
        "uq_extraction_artifact_account_adapter_version",
        "extraction",
        ["artifact_id", "financial_account_id", "adapter_key", "parser_version"],
        unique=True,
        postgresql_where=sa.text("financial_account_id IS NOT NULL AND adapter_key IS NOT NULL"),
    )

    op.create_table(
        "claim_source_locator",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("text_start", sa.Integer(), nullable=False),
        sa.Column("text_end", sa.Integer(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "page_number > 0",
            name=op.f("ck_claim_source_locator_page_number_positive"),
        ),
        sa.CheckConstraint(
            "line_number > 0",
            name=op.f("ck_claim_source_locator_line_number_positive"),
        ),
        sa.CheckConstraint(
            "text_start >= 0 AND text_end > text_start",
            name=op.f("ck_claim_source_locator_text_span_valid"),
        ),
        sa.CheckConstraint(
            "text_sha256 IS NULL OR text_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_claim_source_locator_text_sha256_hex"),
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claim.id"],
            name=op.f("fk_claim_source_locator_claim_id_claim"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_source_locator")),
        sa.UniqueConstraint("claim_id", name=op.f("uq_claim_source_locator_claim_id")),
    )

    op.create_table(
        "inbox_file_observation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("financial_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("modified_ns", sa.BigInteger(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("size >= 0", name=op.f("ck_inbox_file_observation_size_nonnegative")),
        sa.CheckConstraint(
            "modified_ns >= 0",
            name=op.f("ck_inbox_file_observation_modified_ns_nonnegative"),
        ),
        sa.CheckConstraint(
            "status IN ('observed', 'captured')",
            name=op.f("ck_inbox_file_observation_status_known"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["source_artifact.id"],
            name=op.f("fk_inbox_file_observation_artifact_id_source_artifact"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["financial_account_id"],
            ["financial_account.id"],
            name=op.f("fk_inbox_file_observation_financial_account_id_financial_account"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbox_file_observation")),
        sa.UniqueConstraint(
            "financial_account_id",
            "file_name",
            "size",
            "modified_ns",
            name="uq_inbox_file_observation_fingerprint",
        ),
    )
    op.create_index(
        "ix_inbox_file_observation_status",
        "inbox_file_observation",
        ["status", "first_observed_at"],
        unique=False,
    )

    for table in ("extraction", "claim_source_locator"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_append_only_change()
            """
        )


def downgrade() -> None:
    for table in ("claim_source_locator", "extraction"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.drop_index("ix_inbox_file_observation_status", table_name="inbox_file_observation")
    op.drop_table("inbox_file_observation")
    op.drop_table("claim_source_locator")
    op.drop_index(
        "uq_extraction_artifact_account_adapter_version",
        table_name="extraction",
        postgresql_where=sa.text("financial_account_id IS NOT NULL AND adapter_key IS NOT NULL"),
    )
    op.drop_constraint(op.f("ck_extraction_status_fields_consistent"), "extraction", type_="check")
    op.drop_constraint(op.f("ck_extraction_candidate_hash_hex"), "extraction", type_="check")
    op.drop_constraint(
        op.f("ck_extraction_statement_currency_iso_style"), "extraction", type_="check"
    )
    op.drop_constraint(op.f("ck_extraction_claim_count_nonnegative"), "extraction", type_="check")
    op.drop_constraint(
        op.f("fk_extraction_supersedes_extraction_id_extraction"),
        "extraction",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_extraction_financial_account_id_financial_account"),
        "extraction",
        type_="foreignkey",
    )
    for column in (
        "supersedes_extraction_id",
        "validation_report",
        "failure_code",
        "candidate_hash",
        "claim_count",
        "candidate_row_count",
        "closing_balance",
        "opening_balance",
        "statement_currency",
        "period_end",
        "period_start",
        "statement_date",
        "statement_identity",
        "adapter_key",
        "financial_account_id",
    ):
        op.drop_column("extraction", column)
    op.drop_column("financial_account", "statement_password_secret")
    op.drop_column("financial_account", "statement_account_identifier")
    op.drop_column("financial_account", "statement_adapter_key")
