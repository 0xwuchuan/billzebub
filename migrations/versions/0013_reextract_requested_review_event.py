"""Record an owner request to re-extract an excluded statement.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENT_TYPES_WITH_REEXTRACT = (
    "event_type IN ('created', 'synchronized', 'resolved', 'cancelled', 'reextract_requested')"
)
_EVENT_TYPES_ORIGINAL = "event_type IN ('created', 'synchronized', 'resolved', 'cancelled')"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_review_event_event_type_known"),
        "review_event",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_review_event_event_type_known"),
        "review_event",
        _EVENT_TYPES_WITH_REEXTRACT,
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS review_event_append_only ON review_event")
    op.execute("DELETE FROM review_event WHERE event_type = 'reextract_requested'")
    op.execute(
        """
        CREATE TRIGGER review_event_append_only
        BEFORE UPDATE OR DELETE ON review_event
        FOR EACH ROW EXECUTE FUNCTION reject_append_only_change()
        """
    )
    op.drop_constraint(
        op.f("ck_review_event_event_type_known"),
        "review_event",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_review_event_event_type_known"),
        "review_event",
        _EVENT_TYPES_ORIGINAL,
    )
