"""Editable two-level Category hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.category_spend import CategorySpend, CategorySpendReport
from billzebub.persistence.models import (
    Category,
    CategorySplit,
    ClaimCategory,
    LedgerAccount,
    RecurringSeries,
)

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
    version: int = 1
    description: str | None = None


@dataclass(frozen=True, slots=True)
class CategoryUpdate:
    expected_version: int
    name: str | None = None
    parent_id: UUID | None = None
    parent_id_set: bool = False
    active: bool | None = None


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
        normalized_name = _normalize_name(name)
        try:
            with self._database.transaction() as session:
                if parent_id is not None:
                    parent = session.get(Category, parent_id)
                    _require_parent(parent)
                category = Category(
                    id=uuid7(),
                    parent_id=parent_id,
                    name=normalized_name,
                    description=_clean_description(description),
                    active=True,
                    sort_order=0,
                    version=1,
                )
                session.add(category)
                session.flush()
                return self._record(category)
        except IntegrityError as error:
            raise CategoryError("a Category with this name already exists at this level") from error

    def update(self, category_id: UUID, command: CategoryUpdate) -> CategoryRecord:
        if command.name is None and not command.parent_id_set and command.active is None:
            raise CategoryError("a Category change is required")
        normalized_name = _normalize_name(command.name) if command.name is not None else None
        try:
            with self._database.transaction() as session:
                category = session.scalar(
                    select(Category).where(Category.id == category_id).with_for_update()
                )
                if category is None:
                    raise CategoryError("Category was not found")
                if category.version != command.expected_version:
                    raise CategoryError("Category version is stale")
                if _is_reserved(category):
                    raise CategoryError("Uncategorized is a reserved system Category")
                if command.parent_id_set:
                    _move(session, category, command.parent_id)
                if normalized_name is not None:
                    category.name = normalized_name
                if command.active is not None:
                    _set_active(session, category, active=command.active)
                category.version += 1
                session.flush()
                return self._record(category)
        except IntegrityError as error:
            raise CategoryError("a Category with this name already exists at this level") from error

    def delete(self, category_id: UUID, *, expected_version: int) -> None:
        try:
            with self._database.transaction() as session:
                category = session.scalar(
                    select(Category).where(Category.id == category_id).with_for_update()
                )
                if category is None:
                    raise CategoryError("Category was not found")
                if category.version != expected_version:
                    raise CategoryError("Category version is stale")
                if _is_reserved(category):
                    raise CategoryError("Uncategorized is a reserved system Category")
                child = session.scalar(
                    select(Category.id).where(Category.parent_id == category.id).limit(1)
                )
                if child is not None:
                    raise CategoryError("Category has subcategories; archive it instead")
                if _referenced(session, category.id):
                    raise CategoryError("Category is in use; archive it instead")
                session.delete(category)
                session.flush()
        except IntegrityError as error:
            raise CategoryError("Category is in use; archive it instead") from error

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

    def spending(self, month: str) -> CategorySpendReport:
        return CategorySpend(self._database).for_month(month)

    @staticmethod
    def _record(category: Category) -> CategoryRecord:
        return CategoryRecord(
            id=category.id,
            name=category.name,
            parent_id=category.parent_id,
            active=category.active,
            version=category.version,
            description=category.description,
        )


def _clean_description(description: str | None) -> str | None:
    if description is None:
        return None
    cleaned = " ".join(description.split())
    return cleaned or None


def _normalize_name(name: str) -> str:
    normalized_name = " ".join(name.split())
    if not normalized_name:
        raise CategoryError("a Category name is required")
    if normalized_name.casefold() == "uncategorized":
        raise CategoryError("Uncategorized is a reserved system Category")
    return normalized_name


def _is_reserved(category: Category) -> bool:
    return category.parent_id is None and category.name == "Uncategorized"


def _require_parent(parent: Category | None) -> None:
    if parent is None or not parent.active:
        raise CategoryError("parent Category was not found or is inactive")
    if _is_reserved(parent):
        raise CategoryError("Uncategorized cannot have subcategories")
    if parent.parent_id is not None:
        raise CategoryError("Categories support only two levels")


def _move(session: Session, category: Category, parent_id: UUID | None) -> None:
    if parent_id == category.id:
        raise CategoryError("Categories support only two levels")
    if parent_id is None:
        category.parent_id = None
        return
    parent = session.scalar(select(Category).where(Category.id == parent_id).with_for_update())
    _require_parent(parent)
    child = session.scalar(select(Category.id).where(Category.parent_id == category.id).limit(1))
    if child is not None:
        raise CategoryError("Categories support only two levels")
    category.parent_id = parent_id


def _set_active(session: Session, category: Category, *, active: bool) -> None:
    if active and category.parent_id is not None:
        parent = session.get(Category, category.parent_id)
        if parent is None or not parent.active:
            raise CategoryError("parent Category was not found or is inactive")
    category.active = active
    if active:
        return
    children = session.scalars(
        select(Category).where(Category.parent_id == category.id).with_for_update()
    ).all()
    for child in children:
        if child.active:
            child.active = False
            child.version += 1


def _referenced(session: Session, category_id: UUID) -> bool:
    checks = (
        select(CategorySplit.id).where(CategorySplit.category_id == category_id),
        select(ClaimCategory.id).where(ClaimCategory.category_id == category_id),
        select(LedgerAccount.id).where(LedgerAccount.category_id == category_id),
        select(RecurringSeries.id).where(RecurringSeries.category_id == category_id),
    )
    return any(session.scalar(query.limit(1)) is not None for query in checks)
