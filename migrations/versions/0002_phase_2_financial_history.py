"""Create immutable Claims and Phase 2 financial history records.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_append_only_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )

    op.create_table(
        "extraction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parser_version", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('accepted', 'failed')",
            name=op.f("ck_extraction_status_known"),
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["source_artifact.id"],
            name=op.f("fk_extraction_artifact_id_source_artifact"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extraction")),
    )
    op.create_index(
        "ix_extraction_artifact_created",
        "extraction",
        ["artifact_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "claim",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_type", sa.String(length=20), nullable=False),
        sa.Column("financial_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_description", sa.Text(), nullable=False),
        sa.Column("authorized_amount", sa.Numeric(), nullable=True),
        sa.Column("authorized_currency", sa.String(length=3), nullable=True),
        sa.Column("posted_amount", sa.Numeric(), nullable=True),
        sa.Column("posted_currency", sa.String(length=3), nullable=True),
        sa.Column("occurrence_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_transaction_date", sa.Date(), nullable=True),
        sa.Column("posting_date", sa.Date(), nullable=True),
        sa.Column("transaction_kind_hint", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "claim_type IN ('real_time', 'statement')",
            name=op.f("ck_claim_type_known"),
        ),
        sa.CheckConstraint(
            "(authorized_amount IS NULL) = (authorized_currency IS NULL)",
            name=op.f("ck_claim_authorized_money_complete"),
        ),
        sa.CheckConstraint(
            "(posted_amount IS NULL) = (posted_currency IS NULL)",
            name=op.f("ck_claim_posted_money_complete"),
        ),
        sa.CheckConstraint(
            "authorized_currency IS NULL OR authorized_currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_claim_authorized_currency_iso_style"),
        ),
        sa.CheckConstraint(
            "posted_currency IS NULL OR posted_currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_claim_posted_currency_iso_style"),
        ),
        sa.CheckConstraint(
            "(claim_type = 'real_time' AND authorized_amount IS NOT NULL AND "
            "occurrence_at IS NOT NULL) OR "
            "(claim_type = 'statement' AND posted_amount IS NOT NULL AND "
            "posting_date IS NOT NULL)",
            name=op.f("ck_claim_required_evidence_present"),
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            ["extraction.id"],
            name=op.f("fk_claim_extraction_id_extraction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["financial_account_id"],
            ["financial_account.id"],
            name=op.f("fk_claim_financial_account_id_financial_account"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"],
            ["source_artifact.id"],
            name=op.f("fk_claim_source_artifact_id_source_artifact"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim")),
    )
    op.create_index(
        "ix_claim_account_type_created",
        "claim",
        ["financial_account_id", "claim_type", "created_at"],
        unique=False,
    )

    op.create_table(
        "claim_disposition_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("disposition", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "disposition IN ('provisional', 'confirmed', 'unconfirmed', 'excluded')",
            name=op.f("ck_claim_disposition_event_disposition_known"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["audit_actor.id"],
            name=op.f("fk_claim_disposition_event_actor_id_audit_actor"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claim.id"],
            name=op.f("fk_claim_disposition_event_claim_id_claim"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_disposition_event")),
    )
    op.create_index(
        "ix_claim_disposition_event_claim_time",
        "claim_disposition_event",
        ["claim_id", "occurred_at", "id"],
        unique=False,
    )

    op.create_table(
        "financial_transaction",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("financial_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "current_version > 0",
            name=op.f("ck_financial_transaction_current_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["financial_account_id"],
            ["financial_account.id"],
            name=op.f("fk_financial_transaction_financial_account_id_financial_account"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_transaction")),
    )

    op.create_table(
        "transaction_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("posted_amount", sa.Numeric(), nullable=False),
        sa.Column("posted_currency", sa.String(length=3), nullable=False),
        sa.Column("authorized_amount", sa.Numeric(), nullable=True),
        sa.Column("authorized_currency", sa.String(length=3), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("occurrence_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_transaction_date", sa.Date(), nullable=True),
        sa.Column("posting_date", sa.Date(), nullable=False),
        sa.Column("counterparty", sa.String(length=300), nullable=False),
        sa.Column("supersedes_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_transaction_version_version_positive")),
        sa.CheckConstraint(
            "kind IN ('expense', 'income', 'transfer', 'refund', 'reimbursement', "
            "'cash_withdrawal')",
            name=op.f("ck_transaction_version_kind_known"),
        ),
        sa.CheckConstraint(
            "posted_amount <> 0",
            name=op.f("ck_transaction_version_posted_amount_nonzero"),
        ),
        sa.CheckConstraint(
            "posted_currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_transaction_version_posted_currency_iso_style"),
        ),
        sa.CheckConstraint(
            "(authorized_amount IS NULL) = (authorized_currency IS NULL)",
            name=op.f("ck_transaction_version_authorized_money_complete"),
        ),
        sa.CheckConstraint(
            "authorized_currency IS NULL OR authorized_currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_transaction_version_authorized_currency_iso_style"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["audit_actor.id"],
            name=op.f("fk_transaction_version_actor_id_audit_actor"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_version_id"],
            ["transaction_version.id"],
            name=op.f("fk_transaction_version_supersedes_version_id_transaction_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transaction.id"],
            name=op.f("fk_transaction_version_transaction_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_version")),
        sa.UniqueConstraint("transaction_id", "version", name="uq_transaction_version_number"),
    )

    op.create_table(
        "transaction_claim",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('statement', 'real_time')",
            name=op.f("ck_transaction_claim_role_known"),
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claim.id"],
            name=op.f("fk_transaction_claim_claim_id_claim"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transaction.id"],
            name=op.f("fk_transaction_claim_transaction_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_claim")),
        sa.UniqueConstraint("claim_id", name=op.f("uq_transaction_claim_claim_id")),
        sa.UniqueConstraint("transaction_id", "role", name="uq_transaction_claim_role"),
    )

    op.create_table(
        "correction_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prior_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replacement_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0",
            name=op.f("ck_correction_event_reason_present"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["audit_actor.id"],
            name=op.f("fk_correction_event_actor_id_audit_actor"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prior_version_id"],
            ["transaction_version.id"],
            name=op.f("fk_correction_event_prior_version_id_transaction_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_version_id"],
            ["transaction_version.id"],
            name=op.f("fk_correction_event_replacement_version_id_transaction_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transaction.id"],
            name=op.f("fk_correction_event_transaction_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correction_event")),
        sa.UniqueConstraint(
            "replacement_version_id",
            name=op.f("uq_correction_event_replacement_version_id"),
        ),
    )

    op.create_table(
        "category_split",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_category_split_amount_positive")),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_category_split_currency_iso_style"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_category_split_category_id_category"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_version_id"],
            ["transaction_version.id"],
            name=op.f("fk_category_split_transaction_version_id_transaction_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_category_split")),
        sa.UniqueConstraint(
            "transaction_version_id", "category_id", name="uq_category_split_version_category"
        ),
    )

    op.create_table(
        "ledger_account",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=160), nullable=False),
        sa.Column("account_type", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("financial_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "account_type IN ('financial', 'category', 'income', 'transfer', "
            "'offset_unallocated', 'offset_allocated')",
            name=op.f("ck_ledger_account_account_type_known"),
        ),
        sa.CheckConstraint(
            "(account_type = 'financial' AND financial_account_id IS NOT NULL AND "
            "category_id IS NULL) OR "
            "(account_type = 'category' AND category_id IS NOT NULL AND "
            "financial_account_id IS NULL) OR "
            "(account_type NOT IN ('financial', 'category') AND financial_account_id IS NULL "
            "AND category_id IS NULL)",
            name=op.f("ck_ledger_account_reference_matches_type"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_ledger_account_category_id_category"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["financial_account_id"],
            ["financial_account.id"],
            name=op.f("fk_ledger_account_financial_account_id_financial_account"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_account")),
        sa.UniqueConstraint("category_id", name=op.f("uq_ledger_account_category_id")),
        sa.UniqueConstraint("code", name=op.f("uq_ledger_account_code")),
        sa.UniqueConstraint(
            "financial_account_id", name=op.f("uq_ledger_account_financial_account_id")
        ),
    )

    op.create_table(
        "offset_allocation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offset_transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expense_transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "offset_transaction_id <> expense_transaction_id",
            name=op.f("ck_offset_allocation_transactions_differ"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_offset_allocation_amount_positive")),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_offset_allocation_currency_iso_style"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["audit_actor.id"],
            name=op.f("fk_offset_allocation_actor_id_audit_actor"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["expense_transaction_id"],
            ["financial_transaction.id"],
            name=op.f("fk_offset_allocation_expense_transaction_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["offset_transaction_id"],
            ["financial_transaction.id"],
            name=op.f("fk_offset_allocation_offset_transaction_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offset_allocation")),
    )
    op.create_index(
        "ix_offset_allocation_offset_transaction",
        "offset_allocation",
        ["offset_transaction_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_offset_allocation_expense_transaction",
        "offset_allocation",
        ["expense_transaction_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "journal",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("transaction_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("journal_type", sa.String(length=30), nullable=False),
        sa.Column("offset_allocation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reverses_journal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "journal_type IN ('confirmation', 'correction_reversal', "
            "'correction_replacement', 'offset_allocation')",
            name=op.f("ck_journal_journal_type_known"),
        ),
        sa.ForeignKeyConstraint(
            ["offset_allocation_id"],
            ["offset_allocation.id"],
            name=op.f("fk_journal_offset_allocation_id_offset_allocation"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reverses_journal_id"],
            ["journal.id"],
            name=op.f("fk_journal_reverses_journal_id_journal"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["transaction_version_id"],
            ["transaction_version.id"],
            name=op.f("fk_journal_transaction_version_id_transaction_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_journal")),
        sa.UniqueConstraint("offset_allocation_id", name=op.f("uq_journal_offset_allocation_id")),
    )

    op.create_table(
        "ledger_posting",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("journal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ledger_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "direction IN ('debit', 'credit')",
            name=op.f("ck_ledger_posting_direction_known"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_ledger_posting_amount_positive")),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_ledger_posting_currency_iso_style"),
        ),
        sa.ForeignKeyConstraint(
            ["journal_id"],
            ["journal.id"],
            name=op.f("fk_ledger_posting_journal_id_journal"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ledger_account_id"],
            ["ledger_account.id"],
            name=op.f("fk_ledger_posting_ledger_account_id_ledger_account"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ledger_posting")),
    )
    op.create_index(
        "ix_ledger_posting_journal_id",
        "ledger_posting",
        ["journal_id", "id"],
        unique=False,
    )

    op.create_table(
        "pending_review",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("condition_code", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("allowed_decisions", postgresql.ARRAY(sa.String(length=120)), nullable=False),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "severity IN ('attention', 'blocking')",
            name=op.f("ck_pending_review_severity_known"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'cancelled')",
            name=op.f("ck_pending_review_status_known"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_pending_review_version_positive")),
        sa.CheckConstraint(
            "cardinality(allowed_decisions) > 0",
            name=op.f("ck_pending_review_decisions_present"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pending_review")),
    )
    op.create_index(
        "uq_pending_review_active_condition",
        "pending_review",
        ["subject_type", "subject_id", "condition_code"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_pending_review_status_severity_created",
        "pending_review",
        ["status", "severity", "created_at"],
        unique=False,
    )

    op.create_table(
        "review_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("decision", sa.String(length=120), nullable=True),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_review_event_version_positive")),
        sa.CheckConstraint(
            "event_type IN ('created', 'synchronized', 'resolved', 'cancelled')",
            name=op.f("ck_review_event_event_type_known"),
        ),
        sa.CheckConstraint(
            "(event_type = 'resolved' AND decision IS NOT NULL) OR "
            "(event_type <> 'resolved' AND decision IS NULL)",
            name=op.f("ck_review_event_decision_matches_event"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["audit_actor.id"],
            name=op.f("fk_review_event_actor_id_audit_actor"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["pending_review.id"],
            name=op.f("fk_review_event_review_id_pending_review"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_event")),
        sa.UniqueConstraint("review_id", "version", name="uq_review_event_version"),
    )

    append_only_tables = (
        "claim",
        "claim_disposition_event",
        "transaction_version",
        "transaction_claim",
        "correction_event",
        "category_split",
        "offset_allocation",
        "journal",
        "ledger_posting",
        "review_event",
    )
    for table in append_only_tables:
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_append_only_change()
            """
        )


def downgrade() -> None:
    append_only_tables = (
        "review_event",
        "ledger_posting",
        "journal",
        "offset_allocation",
        "category_split",
        "correction_event",
        "transaction_claim",
        "transaction_version",
        "claim_disposition_event",
        "claim",
    )
    for table in append_only_tables:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.drop_table("review_event")
    op.drop_index("ix_pending_review_status_severity_created", table_name="pending_review")
    op.drop_index("uq_pending_review_active_condition", table_name="pending_review")
    op.drop_table("pending_review")
    op.drop_index("ix_ledger_posting_journal_id", table_name="ledger_posting")
    op.drop_table("ledger_posting")
    op.drop_table("journal")
    op.drop_index("ix_offset_allocation_expense_transaction", table_name="offset_allocation")
    op.drop_index("ix_offset_allocation_offset_transaction", table_name="offset_allocation")
    op.drop_table("offset_allocation")
    op.drop_table("ledger_account")
    op.drop_table("category_split")
    op.drop_table("correction_event")
    op.drop_table("transaction_claim")
    op.drop_table("transaction_version")
    op.drop_table("financial_transaction")
    op.drop_index("ix_claim_disposition_event_claim_time", table_name="claim_disposition_event")
    op.drop_table("claim_disposition_event")
    op.drop_index("ix_claim_account_type_created", table_name="claim")
    op.drop_table("claim")
    op.drop_index("ix_extraction_artifact_created", table_name="extraction")
    op.drop_table("extraction")
    op.execute("DROP FUNCTION reject_append_only_change()")
