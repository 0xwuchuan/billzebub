"""Drop the in-app learned Counterparty to Category map.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-18

Destructive: historical owner-taught map keys are discarded. Owner
categorization still works; it no longer upserts a reusable mapping.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("counterparty_category_map")


def downgrade() -> None:
    op.create_table(
        "counterparty_category_map",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_key", sa.String(length=300), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(btrim(normalized_key)) > 0",
            name=op.f("ck_counterparty_category_map_normalized_key_present"),
        ),
        sa.CheckConstraint(
            "source IN ('owner_categorization')",
            name=op.f("ck_counterparty_category_map_source_known"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["audit_actor.id"],
            name=op.f("fk_counterparty_category_map_actor_id_audit_actor"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["category.id"],
            name=op.f("fk_counterparty_category_map_category_id_category"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_counterparty_category_map")),
        sa.UniqueConstraint(
            "normalized_key",
            name=op.f("uq_counterparty_category_map_normalized_key"),
        ),
    )
