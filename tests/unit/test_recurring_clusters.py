from datetime import date
from decimal import Decimal
from uuid import uuid4

from billzebub.recurrings import (
    SpendObservation,
    advance_expected,
    amounts_within_tolerance,
    build_clusters,
    guess_cadence,
    normalize_counterparty,
)


def _observation(
    counterparty: str,
    amount: str,
    when: date,
    *,
    currency: str = "SGD",
) -> SpendObservation:
    return SpendObservation(
        transaction_id=uuid4(),
        counterparty=counterparty,
        normalized_counterparty=normalize_counterparty(counterparty),
        amount=Decimal(amount),
        currency=currency,
        effective_date=when,
        financial_account_id=uuid4(),
        category_id=None,
    )


def test_amount_tolerance_uses_the_wider_of_one_unit_or_two_percent() -> None:
    assert amounts_within_tolerance(Decimal("10.00"), Decimal("11.00"))
    assert not amounts_within_tolerance(Decimal("10.00"), Decimal("11.01"))
    assert amounts_within_tolerance(Decimal("100.00"), Decimal("102.00"))
    assert not amounts_within_tolerance(Decimal("100.00"), Decimal("103.00"))


def test_cadence_guess_names_regular_gaps_and_rejects_irregular_ones() -> None:
    weekly = [date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15)]
    monthly = [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)]
    yearly = [date(2024, 3, 1), date(2025, 3, 1), date(2026, 3, 1)]
    fortnightly = [date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 29)]
    irregular = [date(2026, 1, 1), date(2026, 1, 3), date(2026, 3, 1)]

    assert guess_cadence(weekly) == ("weekly", None)
    assert guess_cadence(monthly) == ("monthly", None)
    assert guess_cadence(yearly) == ("yearly", None)
    assert guess_cadence(fortnightly) == ("custom_days", 14)
    assert guess_cadence(irregular) is None
    assert guess_cadence(monthly[:2]) is None


def test_detector_clusters_a_repeating_merchant_inside_tolerance() -> None:
    netflix = [
        _observation("NETFLIX.COM", "15.98", date(2026, 1, 5)),
        _observation("netflix.com", "16.40", date(2026, 2, 5)),
        _observation("Netflix", "15.98", date(2026, 3, 5)),
    ]
    other = [_observation("SYNTHETIC COFFEE", "4.50", date(2026, 2, 2))]
    wide = [
        _observation("CITY ENERGY", "100.00", date(2026, 1, 1)),
        _observation("CITY ENERGY", "100.00", date(2026, 2, 1)),
        _observation("CITY ENERGY", "130.00", date(2026, 3, 1)),
    ]

    clusters = build_clusters([*netflix, *other, *wide])

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.normalized_counterparty == "netflix"
    assert cluster.cadence == "monthly"
    assert cluster.currency == "SGD"
    assert cluster.next_expected_date == date(2026, 4, 5)
    assert cluster.amount_min == Decimal("15.98")
    assert cluster.amount_max == Decimal("16.40")
    assert len(cluster.observations) == 3
    assert Decimal("0") <= cluster.confidence <= Decimal("1")


def test_monthly_advance_clamps_short_months() -> None:
    assert advance_expected(date(2026, 1, 31), "monthly", None) == date(2026, 2, 28)
    assert advance_expected(date(2026, 3, 5), "weekly", None) == date(2026, 3, 12)
