"""Add private Financial Account aliases for Apple Wallet card labels.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_account_alias",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("financial_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias_kind", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=160), nullable=False),
        sa.Column("normalized_value", sa.String(length=160), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "alias_kind IN ('apple_wallet_card')",
            name=op.f("ck_financial_account_alias_alias_kind_known"),
        ),
        sa.CheckConstraint(
            "length(btrim(value)) > 0",
            name=op.f("ck_financial_account_alias_value_present"),
        ),
        sa.CheckConstraint(
            "length(btrim(normalized_value)) > 0",
            name=op.f("ck_financial_account_alias_normalized_value_present"),
        ),
        sa.ForeignKeyConstraint(
            ["financial_account_id"],
            ["financial_account.id"],
            name=op.f("fk_financial_account_alias_financial_account_id_financial_account"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_financial_account_alias")),
        sa.UniqueConstraint(
            "alias_kind",
            "normalized_value",
            name="uq_financial_account_alias_kind_value",
        ),
    )
    op.create_index(
        "uq_extraction_artifact_adapter_version_unmapped",
        "extraction",
        ["artifact_id", "adapter_key", "parser_version"],
        unique=True,
        postgresql_where=sa.text("financial_account_id IS NULL AND adapter_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_extraction_artifact_adapter_version_unmapped",
        table_name="extraction",
    )
    op.drop_table("financial_account_alias")
