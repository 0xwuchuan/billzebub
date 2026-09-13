"""Persist reconciliation decisions, rejections, and reference FX rates.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reference_exchange_rate",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("quote_currency", sa.String(length=3), nullable=False),
        sa.Column("rate", sa.Numeric(), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "base_currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_reference_exchange_rate_base_currency_iso_style"),
        ),
        sa.CheckConstraint(
            "quote_currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_reference_exchange_rate_quote_currency_iso_style"),
        ),
        sa.CheckConstraint(
            "base_currency <> quote_currency",
            name=op.f("ck_reference_exchange_rate_currencies_differ"),
        ),
        sa.CheckConstraint("rate > 0", name=op.f("ck_reference_exchange_rate_rate_positive")),
        sa.CheckConstraint(
            "length(btrim(source_name)) > 0", name=op.f("ck_reference_exchange_rate_source_present")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reference_exchange_rate")),
        sa.UniqueConstraint(
            "rate_date",
            "base_currency",
            "quote_currency",
            name="uq_reference_exchange_rate_date_pair",
        ),
    )

    op.create_table(
        "reconciled_claim_pair",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("real_time_claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement_claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("decision_source", sa.String(length=20), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100", name=op.f("ck_reconciled_claim_pair_score_range")
        ),
        sa.CheckConstraint(
            "decision_source IN ('automatic', 'review')",
            name=op.f("ck_reconciled_claim_pair_decision_source_known"),
        ),
        sa.CheckConstraint(
            "(decision_source = 'review') = (review_id IS NOT NULL)",
            name=op.f("ck_reconciled_claim_pair_review_matches_source"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["audit_actor.id"],
            name=op.f("fk_reconciled_claim_pair_actor_id_audit_actor"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["real_time_claim_id"],
            ["claim.id"],
            name=op.f("fk_reconciled_claim_pair_real_time_claim_id_claim"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["pending_review.id"],
            name=op.f("fk_reconciled_claim_pair_review_id_pending_review"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["statement_claim_id"],
            ["claim.id"],
            name=op.f("fk_reconciled_claim_pair_statement_claim_id_claim"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transaction.id"],
            name=op.f("fk_reconciled_claim_pair_transaction_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reconciled_claim_pair")),
        sa.UniqueConstraint("real_time_claim_id", name="uq_reconciled_claim_pair_real_time_claim"),
        sa.UniqueConstraint("statement_claim_id", name="uq_reconciled_claim_pair_statement_claim"),
        sa.UniqueConstraint("transaction_id", name="uq_reconciled_claim_pair_transaction"),
    )
    op.create_index(
        "ix_reconciled_claim_pair_statement_created",
        "reconciled_claim_pair",
        ["statement_claim_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "rejected_claim_pair",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("real_time_claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement_claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(reason_code)) > 0", name=op.f("ck_rejected_claim_pair_reason_present")
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["audit_actor.id"],
            name=op.f("fk_rejected_claim_pair_actor_id_audit_actor"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["real_time_claim_id"],
            ["claim.id"],
            name=op.f("fk_rejected_claim_pair_real_time_claim_id_claim"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["pending_review.id"],
            name=op.f("fk_rejected_claim_pair_review_id_pending_review"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["statement_claim_id"],
            ["claim.id"],
            name=op.f("fk_rejected_claim_pair_statement_claim_id_claim"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rejected_claim_pair")),
        sa.UniqueConstraint(
            "real_time_claim_id",
            "statement_claim_id",
            name="uq_rejected_claim_pair_claims",
        ),
    )
    op.create_index(
        "ix_rejected_claim_pair_statement_created",
        "rejected_claim_pair",
        ["statement_claim_id", "created_at"],
        unique=False,
    )

    for table in ("reconciled_claim_pair", "rejected_claim_pair"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_append_only_change()
            """
        )


def downgrade() -> None:
    for table in ("rejected_claim_pair", "reconciled_claim_pair"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.drop_index("ix_rejected_claim_pair_statement_created", table_name="rejected_claim_pair")
    op.drop_table("rejected_claim_pair")
    op.drop_index("ix_reconciled_claim_pair_statement_created", table_name="reconciled_claim_pair")
    op.drop_table("reconciled_claim_pair")
    op.drop_table("reference_exchange_rate")
