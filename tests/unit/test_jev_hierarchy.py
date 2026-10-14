from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from billzebub.jev import JevCategory, parse_jev_proposal, parse_jev_response
from billzebub.jev_hierarchy import (
    catalog_choice_criteria,
    resolve_catalog_choice,
)

FOOD = UUID("11111111-1111-4111-8111-111111111111")
DINING = UUID("22222222-2222-4222-8222-222222222222")
GROCERIES = UUID("33333333-3333-4333-8333-333333333333")
TRANSPORT = UUID("44444444-4444-4444-8444-444444444444")
LATE = UUID("55555555-5555-4555-8555-555555555555")


@dataclass(frozen=True, slots=True)
class _Category:
    id: UUID
    name: str
    parent_id: UUID | None = None


def _catalog() -> tuple[_Category, ...]:
    return (
        _Category(FOOD, "Food"),
        _Category(DINING, "Dining", FOOD),
        _Category(GROCERIES, "Groceries", FOOD),
        _Category(TRANSPORT, "Transport"),
        _Category(uuid4(), "Uncategorized"),
    )


def test_catalog_uses_unique_parent_child_paths() -> None:
    criteria = catalog_choice_criteria(_catalog())

    assert criteria == {
        "Food": "Food",
        "Food > Dining": "Food > Dining",
        "Food > Groceries": "Food > Groceries",
        "Transport": "Transport",
    }
    assert "Uncategorized" not in criteria


def test_duplicate_labels_are_omitted_and_distinct_paths_stay() -> None:
    other = uuid4()
    shared = (
        _Category(FOOD, "Food"),
        _Category(uuid4(), "food"),
        _Category(DINING, "Dining", FOOD),
        _Category(other, "Travel"),
        _Category(GROCERIES, "Dining", other),
    )

    criteria = catalog_choice_criteria(shared)

    assert "Food" not in criteria
    assert criteria["Food > Dining"] == "Food > Dining"
    assert criteria["Travel > Dining"] == "Travel > Dining"


def test_grandchild_paths_are_not_offered() -> None:
    categories = (
        _Category(FOOD, "Food"),
        _Category(DINING, "Dining", FOOD),
        _Category(LATE, "Late night", DINING),
    )

    assert catalog_choice_criteria(categories) == {
        "Food": "Food",
        "Food > Dining": "Food > Dining",
    }


def test_child_above_threshold_applies_the_child() -> None:
    resolved = resolve_catalog_choice(
        "food  >  dining",
        Decimal("0.80"),
        _catalog(),
        Decimal("0.5"),
    )

    assert resolved is not None
    assert resolved.category_id == DINING
    assert resolved.category_name == "Dining"
    assert resolved.fell_back_to_parent is False
    assert resolved.confidence == Decimal("0.80")


def test_low_confidence_child_falls_back_to_aggregated_parent_mass() -> None:
    resolved = resolve_catalog_choice(
        "Food > Dining",
        Decimal("0.20"),
        _catalog(),
        Decimal("0.5"),
        probabilities={
            "Food > Dining": "0.40",
            "Food > Groceries": "0.30",
            "Food": "0.05",
            "Transport": "0.25",
        },
    )

    assert resolved is not None
    assert resolved.fell_back_to_parent is True
    assert resolved.category_id == FOOD
    assert resolved.category_name == "Food"
    assert resolved.confidence == Decimal("0.70")


def test_low_confidence_child_without_probabilities_skips() -> None:
    resolved = resolve_catalog_choice(
        "Food > Dining",
        Decimal("0.49"),
        _catalog(),
        Decimal("0.5"),
    )

    assert resolved is None


def test_parent_level_choice_uses_its_own_confidence() -> None:
    applied = resolve_catalog_choice("Food", Decimal("0.50"), _catalog(), Decimal("0.5"))
    skipped = resolve_catalog_choice("Transport", Decimal("0.49"), _catalog(), Decimal("0.5"))

    assert applied is not None
    assert applied.category_id == FOOD
    assert applied.fell_back_to_parent is False
    assert skipped is None


def test_child_mass_below_threshold_does_not_apply_the_parent() -> None:
    resolved = resolve_catalog_choice(
        "Food > Dining",
        Decimal("0.10"),
        _catalog(),
        Decimal("0.5"),
        probabilities={"Food > Dining": "0.20", "Transport": "0.80"},
    )

    assert resolved is None


def _jev_catalog() -> tuple[JevCategory, ...]:
    return tuple(JevCategory(item.id, item.name, item.parent_id) for item in _catalog())


def test_parse_jev_proposal_applies_parent_fallback_from_probabilities() -> None:
    proposal = parse_jev_proposal(
        "Food > Dining",
        "0.20",
        _jev_catalog(),
        Decimal("0.5"),
        model="jev-1.13.0",
        probabilities={"Food > Dining": "0.40", "Food > Groceries": "0.30"},
    )

    assert proposal.action == "apply"
    assert proposal.category_id == FOOD
    assert proposal.category_name == "Food"
    assert proposal.confidence == Decimal("0.70")
    assert proposal.choice == "Food > Dining"
    assert proposal.fell_back_to_parent is True


class _Answer:
    def __init__(self) -> None:
        self.choice = "Food > Dining"
        self.confidence = 0.91
        self.probabilities = {"Food > Dining": "0.91", "Transport": "0.09"}


class _Response:
    def __init__(self) -> None:
        self.model = "jev-1.13.0"
        self.choices = {"category": _Answer()}


def test_parse_jev_response_reads_probabilities_and_keeps_a_confident_child() -> None:
    proposal = parse_jev_response(
        _Response(),
        _jev_catalog(),
        Decimal("0.5"),
        model="jev-1.13.0",
    )

    assert proposal.action == "apply"
    assert proposal.category_id == DINING
    assert proposal.category_name == "Dining"
