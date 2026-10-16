"""Two-level Category paths for Jev, isolated from the name matcher.

Jev v1 (a separate branch) owns casefold/NFKC/whitespace matching, slash
paths, duplicate resolution, and skip_reason logging inside ``jev.py``.
This module only builds ``Parent > Child`` labels and applies the parent
when a child choice is below the confidence floor. Rebase by calling
``catalog_choice_criteria`` and ``resolve_catalog_choice`` from the matcher
that lands second.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import UUID

PATH_SEPARATOR = " > "
_UNCATEGORIZED = "uncategorized"


class PathCategory(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def name(self) -> str: ...

    @property
    def parent_id(self) -> UUID | None: ...


@dataclass(frozen=True, slots=True)
class CatalogChoice:
    category_id: UUID
    category_name: str
    label: str
    parent_id: UUID | None


@dataclass(frozen=True, slots=True)
class ResolvedCategory:
    category_id: UUID
    category_name: str
    confidence: Decimal
    fell_back_to_parent: bool


def normalize_label(value: str) -> str:
    """Collapse whitespace. NFKC and ``Parent/Child`` stay in the Jev v1 matcher."""
    return " ".join(value.split())


def catalog_choices(categories: Sequence[PathCategory]) -> tuple[CatalogChoice, ...]:
    """Unique ``Parent > Child`` labels. Flat categories keep their plain name.

    Duplicate labels (casefold) are omitted so an ambiguous Choice cannot apply.
    Grandchildren and Uncategorized are not offered.
    """
    names = {category.id: normalize_label(category.name) for category in categories}
    parents = {category.id: category.parent_id for category in categories}
    preliminary: list[CatalogChoice] = []
    for category in categories:
        label = _label(category, names, parents)
        if label is None:
            continue
        preliminary.append(
            CatalogChoice(
                category_id=category.id,
                category_name=normalize_label(category.name),
                label=label,
                parent_id=category.parent_id,
            )
        )
    seen: dict[str, CatalogChoice] = {}
    duplicates: set[str] = set()
    for choice in preliminary:
        key = choice.label.casefold()
        if key in seen:
            duplicates.add(key)
            continue
        seen[key] = choice
    return tuple(choice for key, choice in seen.items() if key not in duplicates)


def catalog_choice_criteria(categories: Sequence[PathCategory]) -> dict[str, str]:
    """Choice options keyed by the label Jev must return."""
    return {choice.label: choice.label for choice in catalog_choices(categories)}


def resolve_catalog_choice(
    choice: str,
    confidence: Decimal,
    categories: Sequence[PathCategory],
    min_confidence: Decimal,
    *,
    probabilities: Mapping[str, object] | None = None,
) -> ResolvedCategory | None:
    """Map a returned path to a Category id, with parent fallback.

    A child at or above ``min_confidence`` applies as itself. Below that floor,
    sum the child probabilities under its parent when the response exposes them.
    If that mass clears the floor, apply the parent and leave the child for a
    later refinement. Without a distribution, a parent applies only when the
    selected option is that parent and its own confidence clears the floor.
    """
    label = normalize_label(choice)
    if not label:
        return None
    choices = catalog_choices(categories)
    matched = next((item for item in choices if item.label.casefold() == label.casefold()), None)
    if matched is None:
        return None
    if confidence >= min_confidence:
        return ResolvedCategory(
            category_id=matched.category_id,
            category_name=matched.category_name,
            confidence=confidence,
            fell_back_to_parent=False,
        )
    if matched.parent_id is None:
        return None
    parent = next((item for item in choices if item.category_id == matched.parent_id), None)
    if parent is None:
        return None
    mass = _child_probability_mass(parent.category_id, choices, probabilities)
    if mass is None or mass < min_confidence or mass > Decimal("1"):
        return None
    return ResolvedCategory(
        category_id=parent.category_id,
        category_name=parent.category_name,
        confidence=mass,
        fell_back_to_parent=True,
    )


def _label(
    category: PathCategory,
    names: Mapping[UUID, str],
    parents: Mapping[UUID, UUID | None],
) -> str | None:
    name = names.get(category.id, "")
    if not name or name.casefold() == _UNCATEGORIZED:
        return None
    parent_id = category.parent_id
    if parent_id is None:
        return name
    parent_name = names.get(parent_id, "")
    if not parent_name or parent_name.casefold() == _UNCATEGORIZED:
        return None
    if parents.get(parent_id) is not None:
        return None
    return f"{parent_name}{PATH_SEPARATOR}{name}"


def _child_probability_mass(
    parent_id: UUID,
    choices: Sequence[CatalogChoice],
    probabilities: Mapping[str, object] | None,
) -> Decimal | None:
    distribution = _distribution(probabilities)
    if distribution is None:
        return None
    labels = [choice.label.casefold() for choice in choices if choice.parent_id == parent_id]
    if not labels:
        return None
    total = Decimal(0)
    for label in labels:
        total += distribution.get(label, Decimal(0))
    return total


def _distribution(probabilities: Mapping[str, object] | None) -> dict[str, Decimal] | None:
    if not isinstance(probabilities, Mapping) or not probabilities:
        return None
    parsed: dict[str, Decimal] = {}
    for key, raw in probabilities.items():
        if not isinstance(key, str):
            return None
        value = _probability(raw)
        if value is None:
            return None
        parsed[normalize_label(key).casefold()] = value
    return parsed


def _probability(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, int):
            parsed = Decimal(value)
        elif isinstance(value, float):
            parsed = Decimal(str(value))
        elif isinstance(value, str):
            parsed = Decimal(value.strip())
        elif isinstance(value, Decimal):
            parsed = value
        else:
            return None
    except InvalidOperation:
        return None
    if parsed < Decimal(0) or parsed > Decimal(1):
        return None
    return parsed
