"""Enforce a two-level Category hierarchy.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-14

Existing rows are left in place. Names stay unique per parent via
uq_category_parent_name, with uq_category_top_level_name covering NULL
parents. This revision adds an If-Match version, an index on parent_id,
a self-parent check, and a trigger that rejects grandchildren.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TWO_LEVEL_FUNCTION = """
CREATE FUNCTION category_enforce_two_levels() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  parent_parent uuid;
BEGIN
  IF NEW.parent_id IS NULL THEN
    RETURN NEW;
  END IF;
  IF NEW.parent_id = NEW.id THEN
    RAISE EXCEPTION 'Categories support only two levels'
      USING ERRCODE = '23514';
  END IF;
  SELECT parent_id INTO parent_parent
    FROM category
    WHERE id = NEW.parent_id
    FOR UPDATE;
  IF NOT FOUND OR parent_parent IS NOT NULL THEN
    RAISE EXCEPTION 'Categories support only two levels'
      USING ERRCODE = '23514';
  END IF;
  PERFORM 1 FROM category WHERE parent_id = NEW.id FOR UPDATE;
  IF FOUND THEN
    RAISE EXCEPTION 'Categories support only two levels'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.add_column(
        "category",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_category_category_version_positive"),
        "category",
        "version > 0",
    )
    op.create_check_constraint(
        op.f("ck_category_category_parent_not_self"),
        "category",
        "parent_id IS DISTINCT FROM id",
    )
    op.create_index("ix_category_parent_id", "category", ["parent_id"])
    op.execute(_TWO_LEVEL_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER category_two_level_guard
        BEFORE INSERT OR UPDATE OF parent_id ON category
        FOR EACH ROW
        EXECUTE FUNCTION category_enforce_two_levels()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS category_two_level_guard ON category")
    op.execute("DROP FUNCTION IF EXISTS category_enforce_two_levels()")
    op.drop_index("ix_category_parent_id", table_name="category")
    op.drop_constraint(
        op.f("ck_category_category_parent_not_self"),
        "category",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_category_category_version_positive"),
        "category",
        type_="check",
    )
    op.drop_column("category", "version")
