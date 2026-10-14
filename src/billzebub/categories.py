"""Editable two-level Category hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from billzebub.persistence.models import Category

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class CategoryError(ValueError):
    """Category hierarchy policy rejected a requested change."""


@dataclass(frozen=True, slots=True)
class CategoryRecord:
    id: UUID
    name: str
    parent_id: UUID | None
    active: bool
    description: str | None = None


class CategoryCatalog:
    """Own Category naming and the top-level/optional-subcategory invariant."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(
        self,
        name: str,
        *,
        parent_id: UUID | None = None,
        description: str | None = None,
    ) -> CategoryRecord:
        normalized_name = " ".join(name.split())
        if not normalized_name:
            raise CategoryError("a Category name is required")
        if normalized_name.casefold() == "uncategorized":
            raise CategoryError("Uncategorized is a reserved system Category")

        try:
            with self._database.transaction() as session:
                if parent_id is not None:
                    parent = session.get(Category, parent_id)
                    if parent is None or not parent.active:
                        raise CategoryError("parent Category was not found or is inactive")
                    if parent.parent_id is not None:
                        raise CategoryError("Categories support only two levels")
                category = Category(
                    id=uuid7(),
                    parent_id=parent_id,
                    name=normalized_name,
                    description=_clean_description(description),
                    active=True,
                    sort_order=0,
                )
                session.add(category)
                session.flush()
                return self._record(category)
        except IntegrityError as error:
            raise CategoryError("a Category with this name already exists at this level") from error

    def list(self) -> tuple[CategoryRecord, ...]:
        with self._database.transaction() as session:
            categories = session.scalars(
                select(Category).order_by(
                    Category.parent_id, Category.sort_order, Category.name, Category.id
                )
            ).all()
            return tuple(self._record(category) for category in categories)

    def get(self, category_id: UUID) -> CategoryRecord:
        with self._database.transaction() as session:
            category = session.scalar(select(Category).where(Category.id == category_id))
            if category is None:
                raise CategoryError("Category was not found")
            return self._record(category)

    @staticmethod
    def _record(category: Category) -> CategoryRecord:
        return CategoryRecord(
            id=category.id,
            name=category.name,
            parent_id=category.parent_id,
            active=category.active,
            description=category.description,
        )


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None
    cleaned = " ".join(description.split())
    return cleaned or None
