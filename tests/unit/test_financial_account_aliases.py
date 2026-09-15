import pytest

from billzebub.financial_account_aliases import (
    FinancialAccountAliasError,
    normalize_apple_wallet_card_label,
)

_ASCII_LABEL = "UOB Lady's World Mastercard"
_CURLY_LABEL_WITH_NEWLINE = "UOB Lady\u2019s World Mastercard\n"


def test_normalize_folds_curly_apostrophe_and_trailing_newline() -> None:
    assert normalize_apple_wallet_card_label(_ASCII_LABEL) == (
        normalize_apple_wallet_card_label(_CURLY_LABEL_WITH_NEWLINE)
    )
    assert normalize_apple_wallet_card_label(_CURLY_LABEL_WITH_NEWLINE) == (
        "uob lady's world mastercard"
    )


@pytest.mark.parametrize(
    "variant",
    [
        "UOB Lady\u2018s World Mastercard",
        "UOB Lady\u02bcs World Mastercard\r\n",
        "  UOB Lady\u2019s World Mastercard  \n",
        "UOB Lady\uff07s World Mastercard",
    ],
)
def test_normalize_folds_other_typographic_apostrophes_and_whitespace(variant: str) -> None:
    assert normalize_apple_wallet_card_label(variant) == normalize_apple_wallet_card_label(
        _ASCII_LABEL
    )


def test_normalize_keeps_distinct_card_labels_unmapped() -> None:
    assert normalize_apple_wallet_card_label(_ASCII_LABEL) != normalize_apple_wallet_card_label(
        "UOB Lady's Solitaire Mastercard"
    )
    assert normalize_apple_wallet_card_label(_ASCII_LABEL) != normalize_apple_wallet_card_label(
        "DBS Woman's World Mastercard"
    )


def test_normalize_rejects_blank_labels() -> None:
    with pytest.raises(FinancialAccountAliasError, match="invalid"):
        normalize_apple_wallet_card_label("  \n")
