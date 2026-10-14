from decimal import Decimal
from uuid import UUID

from billzebub.jev_context import similarity_rank
from billzebub.jev_eval import (
    ThresholdObservation,
    choice_matches_category,
    evaluate_thresholds,
    format_threshold_stats,
)
from billzebub.merchant_memory import SOURCE_JEV, SOURCE_OWNER, resolve_memory

FOOD = UUID("11111111-1111-1111-1111-111111111111")
DINING = UUID("22222222-2222-2222-2222-222222222222")
FEES = UUID("33333333-3333-3333-3333-333333333333")


def test_owner_memory_wins_over_a_disagreeing_jev_seed() -> None:
    resolved = resolve_memory({FOOD}, {DINING})
    assert resolved == (FOOD, SOURCE_OWNER)


def test_several_owner_categories_are_ambiguous() -> None:
    assert resolve_memory({FOOD, DINING}, {FOOD}) is None


def test_a_single_jev_seed_applies_when_the_owner_has_not_decided() -> None:
    assert resolve_memory(set(), {DINING}) == (DINING, SOURCE_JEV)


def test_several_jev_seeds_fall_through() -> None:
    assert resolve_memory(set(), {DINING, FEES}) is None


def test_similarity_prefers_the_same_merchant_then_kind_and_amount() -> None:
    same = similarity_rank(
        subject_key="spotify",
        subject_kind="expense",
        subject_amount="-11.98",
        candidate_key="spotify",
        candidate_kind="expense",
        candidate_amount="-11.98",
    )
    other = similarity_rank(
        subject_key="spotify",
        subject_kind="expense",
        subject_amount="-11.98",
        candidate_key="netflix",
        candidate_kind="expense",
        candidate_amount="-11.98",
    )
    farther = similarity_rank(
        subject_key="spotify",
        subject_kind="expense",
        subject_amount="-11.98",
        candidate_key="spotify",
        candidate_kind="cash_withdrawal",
        candidate_amount="-80.00",
    )
    assert same > farther > other


def test_eval_threshold_reports_precision_and_coverage() -> None:
    rows = (
        ThresholdObservation(Decimal("0.95"), "Groceries", "Groceries"),
        ThresholdObservation(Decimal("0.40"), "Dining", "Dining"),
        ThresholdObservation(Decimal("0.80"), "Parent > Fees", "Fees"),
        ThresholdObservation(Decimal("0.70"), "Transport", "Groceries"),
    )
    stats = evaluate_thresholds(rows, (Decimal("0.5"), Decimal("0.9")))
    low, high = stats
    assert low.total == 4
    assert low.covered == 3
    assert low.matches == 2
    assert low.coverage == Decimal("0.75")
    assert high.covered == 1
    assert high.matches == 1
    text = format_threshold_stats(stats)
    assert "threshold=0.50 coverage=0.750 precision=0.667 covered=3 total=4" in text
    assert "threshold=0.90 coverage=0.250 precision=1.000 covered=1 total=4" in text
    assert choice_matches_category("  Parent / Fees ", "Fees")
