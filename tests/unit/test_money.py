from decimal import Decimal

import pytest

from billzebub.money import Money


def test_money_preserves_decimal_text_and_currency() -> None:
    money = Money.parse("12.340", "sgd")

    assert money.amount == Decimal("12.340")
    assert money.currency == "SGD"
    assert money.to_wire() == {"amount": "12.340", "currency": "SGD"}


def test_money_rejects_floats_at_the_seam() -> None:
    with pytest.raises(TypeError, match="floating-point"):
        Money.parse(12.34, "SGD")  # type: ignore[arg-type]


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_money_rejects_non_finite_decimals(amount: str) -> None:
    with pytest.raises(ValueError, match="finite"):
        Money.parse(amount, "SGD")


@pytest.mark.parametrize("currency", ["SG", "SGDD", "12A", ""])
def test_money_requires_an_iso_style_currency(currency: str) -> None:
    with pytest.raises(ValueError, match="currency"):
        Money.parse("1.00", currency)
