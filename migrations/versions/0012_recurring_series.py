"""Add Recurring Series and Occurrence tables.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recurring_series",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("counterparty", sa.String(length=300), nullable=False),
        sa.Column("normalized_counterparty", sa.String(length=300), nullable=False),
        sa.Column("cluster_key", sa.String(length=360), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("amount_min", sa.Numeric(), nullable=True),
        sa.Column("amount_max", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cadence", sa.String(length=20), nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.Column("next_expected_date", sa.Date(), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("primary_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Numeric(), nullable=True),
        sa.Column("last_matched_tx_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("missed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.CheckConstraint(
            "length(btrim(counterparty)) > 0",
            name=op.f("ck_recurring_series_counterparty_present"),
        ),
        sa.CheckConstraint(
            "length(btrim(normalized_counterparty)) > 0",
            name=op.f("ck_recurring_series_normalized_counterparty_present"),
        ),
        sa.CheckConstraint(
            "length(btrim(cluster_key)) > 0",
            name=op.f("ck_recurring_series_cluster_key_present"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_recurring_series_amount_positive")),
        sa.CheckConstraint(
            "(amount_min IS NULL AND amount_max IS NULL) OR "
            "(amount_min IS NOT NULL AND amount_max IS NOT NULL AND amount_min > 0 "
            "AND amount_min <= amount AND amount <= amount_max)",
            name=op.f("ck_recurring_series_amount_bounds"),
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_recurring_series_currency_iso_style"),
        ),
        sa.CheckConstraint(
            "cadence IN ('weekly', 'monthly', 'yearly', 'custom_days')",
            name=op.f("ck_recurring_series_cadence_known"),
        ),
        sa.CheckConstraint(
            "(cadence = 'custom_days' AND interval_days IS NOT NULL AND interval_days > 0) OR "
            "(cadence IN ('weekly', 'monthly', 'yearly') AND interval_days IS NULL)",
            name=op.f("ck_recurring_series_cadence_interval"),
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'active', 'paused', 'ended', 'dismissed')",
            name=op.f("ck_recurring_series_status_known"),
        ),
        sa.CheckConstraint(
            "source IN ('detected', 'manual')",
            name=op.f("ck_recurring_series_source_known"),
        ),
        sa.CheckConstraint(
            "(source = 'manual' AND confidence IS NULL) OR "
            "(source = 'detected' AND confidence IS NOT NULL AND confidence >= 0 "
            "AND confidence <= 1)",
            name=op.f("ck_recurring_series_confidence_matches_source"),
        ),
        sa.CheckConstraint(
            "notes IS NULL OR length(btrim(notes)) > 0",
            name=op.f("ck_recurring_series_notes_present"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_recurring_series_category_id_category"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["primary_account_id"],
            ["financial_account.id"],
            name=op.f("fk_recurring_series_primary_account_id_financial_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_matched_tx_id"],
            ["financial_transaction.id"],
            name=op.f("fk_recurring_series_last_matched_tx_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurring_series")),
        sa.UniqueConstraint("cluster_key", name="uq_recurring_series_cluster_key"),
    )
    op.create_index(
        "ix_recurring_series_status_next_expected",
        "recurring_series",
        ["status", "next_expected_date"],
    )
    op.create_table(
        "recurring_occurrence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("series_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("match_kind", sa.String(length=20), nullable=False),
        sa.CheckConstraint(
            "match_kind IN ('auto', 'manual')",
            name=op.f("ck_recurring_occurrence_match_kind_known"),
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["recurring_series.id"],
            name=op.f("fk_recurring_occurrence_series_id_recurring_series"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transaction.id"],
            name=op.f("fk_recurring_occurrence_transaction_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recurring_occurrence")),
        sa.UniqueConstraint(
            "series_id",
            "transaction_id",
            name="uq_recurring_occurrence_series_transaction",
        ),
        sa.UniqueConstraint("transaction_id", name="uq_recurring_occurrence_transaction_id"),
    )
    op.create_index(
        "ix_recurring_occurrence_series_matched",
        "recurring_occurrence",
        ["series_id", "matched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_recurring_occurrence_series_matched", table_name="recurring_occurrence")
    op.drop_table("recurring_occurrence")
    op.drop_index("ix_recurring_series_status_next_expected", table_name="recurring_series")
    op.drop_table("recurring_series")
