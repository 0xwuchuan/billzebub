"""Record why a Jev categorization attempt skipped, and keep the raw Choice.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SKIP_REASONS = (
    "skip_reason IS NULL OR skip_reason IN ("
    "'low_confidence', 'missing_choice', 'missing_confidence', "
    "'unknown_category', 'ambiguous_category', 'jev_unavailable', 'empty_catalog')"
)
_SKIP_MATCHES_ACTION = (
    "(action = 'apply' AND skip_reason IS NULL) OR (action = 'skip' AND skip_reason IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column(
        "jev_categorization_attempt",
        sa.Column("skip_reason", sa.String(length=40), nullable=True),
    )
    op.alter_column(
        "jev_categorization_attempt",
        "choice",
        existing_type=sa.String(length=120),
        type_=sa.String(length=500),
        existing_nullable=True,
    )
    op.execute(
        """
        UPDATE jev_categorization_attempt
        SET skip_reason = CASE
            WHEN error_class IS NOT NULL OR error_message IS NOT NULL THEN 'jev_unavailable'
            WHEN choice_confidence IS NULL AND choice IS NULL THEN 'missing_confidence'
            WHEN choice IS NULL THEN 'missing_choice'
            WHEN choice_confidence IS NULL THEN 'missing_confidence'
            WHEN choice_confidence < 0.5 THEN 'low_confidence'
            ELSE 'unknown_category'
        END
        WHERE action = 'skip' AND skip_reason IS NULL
        """
    )
    op.create_check_constraint(
        op.f("ck_jev_categorization_attempt_skip_reason_known"),
        "jev_categorization_attempt",
        _SKIP_REASONS,
    )
    op.create_check_constraint(
        op.f("ck_jev_categorization_attempt_skip_reason_matches_action"),
        "jev_categorization_attempt",
        _SKIP_MATCHES_ACTION,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_jev_categorization_attempt_skip_reason_matches_action"),
        "jev_categorization_attempt",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_jev_categorization_attempt_skip_reason_known"),
        "jev_categorization_attempt",
        type_="check",
    )
    op.execute(
        """
        UPDATE jev_categorization_attempt
        SET choice = left(choice, 120)
        WHERE choice IS NOT NULL AND length(choice) > 120
        """
    )
    op.alter_column(
        "jev_categorization_attempt",
        "choice",
        existing_type=sa.String(length=500),
        type_=sa.String(length=120),
        existing_nullable=True,
    )
    op.drop_column("jev_categorization_attempt", "skip_reason")
