from decimal import Decimal
from uuid import uuid4

from billzebub.categorizer import (
    ABSTAIN_CONFIDENCE,
    CATEGORY_NAME_CONFIDENCE,
    KEYWORD_CONFIDENCE,
    LEARNED_CONFIDENCE,
    CategoryHint,
    normalize_counterparty_key,
    propose,
)


def _categories() -> tuple[CategoryHint, ...]:
    return (
        CategoryHint(uuid4(), "Dining"),
        CategoryHint(uuid4(), "Gifts"),
        CategoryHint(uuid4(), "Groceries"),
        CategoryHint(uuid4(), "Health"),
        CategoryHint(uuid4(), "Shopping"),
        CategoryHint(uuid4(), "Transport"),
        CategoryHint(uuid4(), "Utilities"),
    )


def test_normalize_counterparty_key_collapses_case_and_spacing() -> None:
    assert normalize_counterparty_key("  Synthetic   Grocer  ") == "synthetic grocer"


def test_learned_map_beats_keyword_rules() -> None:
    categories = _categories()
    gifts = next(hint for hint in categories if hint.name == "Gifts")
    proposal = propose(
        counterparty="Synthetic Grocer",
        categories=categories,
        learned={normalize_counterparty_key("Synthetic Grocer"): gifts.id},
    )

    assert proposal.category_id == gifts.id
    assert proposal.confidence == LEARNED_CONFIDENCE
    assert proposal.source == "learned_map"


def test_category_name_token_is_high_confidence() -> None:
    categories = _categories()
    groceries = next(hint for hint in categories if hint.name == "Groceries")
    proposal = propose(
        counterparty="Synthetic Groceries Hall",
        categories=categories,
        learned={},
    )

    assert proposal.category_id == groceries.id
    assert proposal.confidence == CATEGORY_NAME_CONFIDENCE
    assert proposal.source == "category_name"


def test_unique_keyword_rule_is_below_nas_safe_threshold() -> None:
    categories = _categories()
    groceries = next(hint for hint in categories if hint.name == "Groceries")
    proposal = propose(
        counterparty="Synthetic Grocer",
        categories=categories,
        learned={},
    )

    assert proposal.category_id == groceries.id
    assert proposal.confidence == KEYWORD_CONFIDENCE
    assert proposal.source == "keyword_rule"
    assert proposal.confidence < Decimal("1.000")


def test_ambiguous_keywords_abstain() -> None:
    categories = _categories()
    proposal = propose(
        counterparty="Synthetic Cafe Taxi",
        categories=categories,
        learned={},
    )

    assert proposal.category_id is None
    assert proposal.confidence == ABSTAIN_CONFIDENCE
    assert proposal.source == "ambiguous"


def test_unknown_merchant_abstains() -> None:
    proposal = propose(
        counterparty="Synthetic Unknown Vendor",
        categories=_categories(),
        learned={},
    )

    assert proposal.category_id is None
    assert proposal.confidence == ABSTAIN_CONFIDENCE
    assert proposal.source == "unknown"


def test_missing_catalog_category_cannot_be_proposed() -> None:
    dining = CategoryHint(uuid4(), "Dining")
    proposal = propose(
        counterparty="Synthetic Grocer",
        categories=(dining,),
        learned={},
    )

    assert proposal.category_id is None
    assert proposal.source == "unknown"
