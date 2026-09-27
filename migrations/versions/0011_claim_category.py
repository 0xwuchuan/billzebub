"""Store Jev Categories for claim-only provisional Real-time Claims.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "claim_category",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_claim_category_amount_positive")),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_claim_category_currency_iso_style"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_claim_category_category_id_category"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claim.id"],
            name=op.f("fk_claim_category_claim_id_claim"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_category")),
        sa.UniqueConstraint("claim_id", name="uq_claim_category_claim_id"),
    )
    op.alter_column("jev_categorization_attempt", "transaction_id", nullable=True)
    op.add_column(
        "jev_categorization_attempt",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_jev_categorization_attempt_claim_id_claim"),
        "jev_categorization_attempt",
        "claim",
        ["claim_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_jev_categorization_attempt_subject_exclusive"),
        "jev_categorization_attempt",
        "(transaction_id IS NOT NULL AND claim_id IS NULL) OR "
        "(transaction_id IS NULL AND claim_id IS NOT NULL)",
    )
    op.create_index(
        "ix_jev_categorization_attempt_claim_attempted",
        "jev_categorization_attempt",
        ["claim_id", "attempted_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_jev_categorization_attempt_claim_attempted",
        table_name="jev_categorization_attempt",
    )
    op.drop_constraint(
        op.f("ck_jev_categorization_attempt_subject_exclusive"),
        "jev_categorization_attempt",
        type_="check",
    )
    op.drop_constraint(
        op.f("fk_jev_categorization_attempt_claim_id_claim"),
        "jev_categorization_attempt",
        type_="foreignkey",
    )
    op.execute("DELETE FROM jev_categorization_attempt WHERE transaction_id IS NULL")
    op.drop_column("jev_categorization_attempt", "claim_id")
    op.alter_column("jev_categorization_attempt", "transaction_id", nullable=False)
    op.drop_table("claim_category")
