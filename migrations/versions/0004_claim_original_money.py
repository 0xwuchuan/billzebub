"""Store optional original-currency evidence on immutable Claims.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("claim", sa.Column("original_amount", sa.Numeric(), nullable=True))
    op.add_column("claim", sa.Column("original_currency", sa.String(length=3), nullable=True))
    op.create_check_constraint(
        op.f("ck_claim_original_money_complete"),
        "claim",
        "(original_amount IS NULL) = (original_currency IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_claim_original_currency_iso_style"),
        "claim",
        "original_currency IS NULL OR original_currency ~ '^[A-Z]{3}$'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_claim_original_currency_iso_style"), "claim", type_="check")
    op.drop_constraint(op.f("ck_claim_original_money_complete"), "claim", type_="check")
    op.drop_column("claim", "original_currency")
    op.drop_column("claim", "original_amount")
