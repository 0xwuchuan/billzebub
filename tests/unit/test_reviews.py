from uuid import UUID

from billzebub.reviews import categorization_needed_context, merge_categorization_context


def test_categorization_needed_context_carries_counterparty_amount_and_transaction_id() -> None:
    transaction_id = UUID("00000000-0000-0000-0000-000000000010")
    account_id = UUID("00000000-0000-0000-0000-000000000011")

    context = categorization_needed_context(
        transaction_id=transaction_id,
        counterparty="Synthetic Coffee",
        amount="-12.34",
        currency="SGD",
        account="Synthetic Card",
        financial_account_id=account_id,
        effective_date="2026-01-10",
        version=1,
        kind="expense",
    )

    assert context["transaction_id"] == str(transaction_id)
    assert context["counterparty"] == "Synthetic Coffee"
    assert context["amount"] == "-12.34"
    assert context["currency"] == "SGD"
    assert context["account"] == "Synthetic Card"
    assert context["version"] == 1


def test_merge_categorization_context_overlays_live_display_without_dropping_jev() -> None:
    merged = merge_categorization_context(
        {"jev_attempt": {"action": "skip"}, "counterparty": "Stale"},
        {"counterparty": "Synthetic Coffee", "amount": "-12.34", "transaction_id": "txn"},
    )

    assert merged["jev_attempt"] == {"action": "skip"}
    assert merged["counterparty"] == "Synthetic Coffee"
    assert merged["amount"] == "-12.34"
    assert merged["transaction_id"] == "txn"
