"""Merchant memory and Category descriptions for Jev Choice criteria.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("category", sa.Column("description", sa.Text(), nullable=True))
    op.create_table(
        "merchant_category_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_key", sa.String(length=300), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(normalized_key)) > 0",
            name=op.f("ck_merchant_category_memory_normalized_key_present"),
        ),
        sa.CheckConstraint(
            "source IN ('owner', 'jev')",
            name=op.f("ck_merchant_category_memory_source_known"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_merchant_category_memory_category_id_category"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merchant_category_memory")),
        sa.UniqueConstraint(
            "normalized_key",
            name=op.f("uq_merchant_category_memory_normalized_key"),
        ),
    )
    op.create_table(
        "merchant_memory_exclusion",
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_key", sa.String(length=300), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(normalized_key)) > 0",
            name=op.f("ck_merchant_memory_exclusion_normalized_key_present"),
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["financial_transaction.id"],
            name=op.f("fk_merchant_memory_exclusion_transaction_id_financial_transaction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "transaction_id",
            name=op.f("pk_merchant_memory_exclusion"),
        ),
    )


def downgrade() -> None:
    op.drop_table("merchant_memory_exclusion")
    op.drop_table("merchant_category_memory")
    op.drop_column("category", "description")
