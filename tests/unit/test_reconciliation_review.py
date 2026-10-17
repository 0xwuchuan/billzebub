from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from billzebub.reconciliation_review import (
    account_last4,
    card_last4,
    match_criterion_results,
    occurred_at_payload,
    provisional_source,
    signed_amount_delta,
    signed_day_delta,
    statement_issuer,
)

_SINGAPORE = ZoneInfo("Asia/Singapore")


def test_card_last4_keeps_only_a_short_suffix() -> None:
    assert card_last4(None) is None
    assert card_last4("   ") is None
    assert card_last4("4242") == "4242"
    assert card_last4("XXXX-XXXX-XXXX-4242") == "4242"
    assert card_last4("Visa 4242") == "4242"
    assert card_last4("Synthetic Wallet Card") is None
    assert card_last4("statement-2026-01") is None


def test_account_last4_prefers_the_statement_identifier() -> None:
    assert account_last4("XXXX-XXXX-XXXX-4242", ("Visa 1111",)) == "4242"
    assert account_last4(None, ("Visa 1111",)) == "1111"
    assert account_last4("Synthetic Wallet Card", ("not a number",)) is None


def test_provisional_source_names_wallet_and_paylah() -> None:
    assert provisional_source("apple_wallet_shortcut", {}) == "wallet"
    assert provisional_source("synthetic", {"source": "apple_wallet"}) == "wallet"
    assert provisional_source("synthetic", {"source": "Apple Pay"}) == "wallet"
    assert provisional_source("paylah_shortcut", {}) == "paylah"
    assert provisional_source("synthetic-reconciliation", {}) is None


def test_statement_issuer_uses_the_adapter_before_the_account() -> None:
    assert statement_issuer("dbs-credit-card", "synthetic-bank") == "dbs"
    assert statement_issuer("synthetic-statement", "synthetic-bank") == "synthetic-bank"
    assert statement_issuer(None, "  ") is None


def test_amount_delta_is_signed_and_same_currency_only() -> None:
    assert signed_amount_delta(Decimal("-8.00"), "SGD", Decimal("-8.50"), "SGD") == "-0.50"
    assert signed_amount_delta(Decimal("-8.00"), "SGD", Decimal("-10.80"), "USD") is None


def test_day_delta_is_signed_from_the_provisional_date() -> None:
    assert signed_day_delta(date(2026, 1, 10), date(2026, 1, 9)) == -1
    assert signed_day_delta(date(2026, 1, 10), date(2026, 1, 12)) == 2


def test_match_reasons_mark_failed_criteria() -> None:
    assert match_criterion_results(
        ["same_financial_account", "amount_exact_posted", "counterparty_no_overlap"]
    ) == [
        {"criterion": "financial_account", "passed": True, "code": "same_financial_account"},
        {"criterion": "amount", "passed": True, "code": "amount_exact_posted"},
        {"criterion": "counterparty", "passed": False, "code": "counterparty_no_overlap"},
    ]


def test_occurred_at_splits_date_and_time_in_the_reporting_timezone() -> None:
    payload = occurred_at_payload(datetime(2026, 1, 10, 16, 30, tzinfo=UTC), _SINGAPORE)

    assert payload == {
        "date": "2026-01-11",
        "time": "00:30:00",
        "timezone": "Asia/Singapore",
    }
    assert occurred_at_payload(None, _SINGAPORE) == {
        "date": None,
        "time": None,
        "timezone": "Asia/Singapore",
    }
