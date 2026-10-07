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


def test_spotify_per_charge_refs_cluster_as_one_monthly_series() -> None:
    labels = [
        "Spotify P45AE6BD59 Stockholm SE",
        "Spotify P449A6A149 Stockholm SE",
        "Spotify P7C3E91A4B Stockholm SE",
        "Spotify P8D12F6A03 Stockholm SE",
        "Spotify P2B90C4E17 Stockholm SE",
        "Spotify P6A18D3F52 Stockholm SE",
        "Spotify P9E4B70C21 Stockholm SE",
        "Spotify P3F81A2D64 Stockholm SE",
        "Spotify P5C27B9E08 Stockholm SE",
    ]
    dates = [
        date(2025, 12, 15),
        date(2026, 1, 15),
        date(2026, 2, 15),
        date(2026, 3, 15),
        date(2026, 4, 15),
        date(2026, 5, 15),
        date(2026, 6, 15),
        date(2026, 7, 15),
        date(2026, 8, 15),
    ]
    charges = [
        _observation(label, "20.98", when) for label, when in zip(labels, dates, strict=True)
    ]

    assert {charge.normalized_counterparty for charge in charges} == {"spotify stockholm se"}
    assert normalize_counterparty("Spotify Stockholm SE") == "spotify stockholm se"

    clusters = build_clusters(charges)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.normalized_counterparty == "spotify stockholm se"
    assert cluster.cadence == "monthly"
    assert cluster.currency == "SGD"
    assert cluster.amount == Decimal("20.98")
    assert cluster.amount_min is None
    assert cluster.amount_max is None
    assert cluster.next_expected_date == date(2026, 9, 15)
    assert len(cluster.observations) == 9


def test_normalize_counterparty_keeps_merchant_words_that_contain_digits() -> None:
    assert normalize_counterparty("7ELEVEN") == "7eleven"
    assert normalize_counterparty("G4S SECURITY") == "g4s security"
    assert normalize_counterparty("MP3PLAYER") == "mp3player"
    assert normalize_counterparty("24HOURFITNESS") == "24hourfitness"
