"""Allow owner dismissal of failed Extractions without changing status.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "extraction",
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_extraction_dismissed_at_failed_only"),
        "extraction",
        "dismissed_at IS NULL OR status = 'failed'",
    )
    op.execute("DROP TRIGGER IF EXISTS extraction_append_only ON extraction")
    op.execute(
        """
        CREATE FUNCTION extraction_guard_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'extraction is append-only'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF to_jsonb(NEW) - 'dismissed_at' = to_jsonb(OLD) - 'dismissed_at'
               AND OLD.dismissed_at IS NULL
               AND NEW.dismissed_at IS NOT NULL
               AND NEW.status = 'failed'
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'extraction is append-only'
                USING ERRCODE = 'integrity_constraint_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER extraction_append_only
        BEFORE UPDATE OR DELETE ON extraction
        FOR EACH ROW EXECUTE FUNCTION extraction_guard_change()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS extraction_append_only ON extraction")
    op.execute("DROP FUNCTION IF EXISTS extraction_guard_change()")
    op.execute(
        """
        CREATE TRIGGER extraction_append_only
        BEFORE UPDATE OR DELETE ON extraction
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_change()
        """
    )
    op.drop_constraint(
        op.f("ck_extraction_dismissed_at_failed_only"), "extraction", type_="check"
    )
    op.drop_column("extraction", "dismissed_at")
