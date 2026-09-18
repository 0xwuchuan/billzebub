"""Append-only Jev categorization attempt log for owner review.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jev_categorization_attempt",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("counterparty", sa.String(length=300), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("choice", sa.String(length=120), nullable=True),
        sa.Column("choice_confidence", sa.Numeric(), nullable=True),
        sa.Column("noul", sa.Numeric(), nullable=True),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category_name", sa.String(length=120), nullable=True),
        sa.Column("error_class", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.CheckConstraint(
            "length(btrim(model)) > 0",
            name=op.f("ck_jev_categorization_attempt_model_present"),
        ),
        sa.CheckConstraint(
            "length(btrim(counterparty)) > 0",
            name=op.f("ck_jev_categorization_attempt_counterparty_present"),
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_jev_categorization_attempt_currency_iso_style"),
        ),
        sa.CheckConstraint(
            "kind IN ('expense', 'income', 'transfer', 'refund', 'reimbursement', "
            "'cash_withdrawal')",
            name=op.f("ck_jev_categorization_attempt_kind_known"),
        ),
        sa.CheckConstraint(
            "choice_confidence IS NULL OR (choice_confidence >= 0 AND choice_confidence <= 1)",
            name=op.f("ck_jev_categorization_attempt_choice_confidence_range"),
        ),
        sa.CheckConstraint(
            "noul IS NULL OR (noul >= 0 AND noul <= 1)",
            name=op.f("ck_jev_categorization_attempt_noul_range"),
        ),
        sa.CheckConstraint(
            "action IN ('apply', 'skip')",
            name=op.f("ck_jev_categorization_attempt_action_known"),
        ),
        sa.CheckConstraint(
            "(action = 'apply' AND category_id IS NOT NULL AND category_name IS NOT NULL "
            "AND length(btrim(category_name)) > 0) OR "
            "(action = 'skip' AND category_id IS NULL AND category_name IS NULL)",
            name=op.f("ck_jev_categorization_attempt_category_matches_action"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transaction.id"],
            name=op.f("fk_jev_categorization_attempt_transaction_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_jev_categorization_attempt_category_id_category"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jev_categorization_attempt")),
    )
    op.create_index(
        "ix_jev_categorization_attempt_transaction_attempted",
        "jev_categorization_attempt",
        ["transaction_id", "attempted_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_jev_categorization_attempt_transaction_attempted",
        table_name="jev_categorization_attempt",
    )
    op.drop_table("jev_categorization_attempt")
