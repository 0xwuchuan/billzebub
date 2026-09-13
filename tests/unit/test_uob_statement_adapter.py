import re
from datetime import date
from pathlib import Path

import pymupdf
import pytest

from billzebub.statement_adapters.uob import uob_credit_card_adapter
from billzebub.statement_extraction import StatementAdapterError


def _write_uob_credit_card_statement(path: Path) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "UOB",
                "Statement Date 31 Jan 2026",
                "1111-2222-3333-4444",
                "Description of Transaction Transaction Amount",
                "PREVIOUS BALANCE 100.00",
                "11 Jan 10 Jan FICTIONAL BOOKSHOP 10.00",
                "21 Jan 20 Jan UOB BILL PAYMENT 5.00 CR",
                "26 Jan 25 Jan FICTIONAL MERCHANT REFUND (2.00)",
                "27 Jan 26 Jan FICTIONAL ZERO-VALUE NOTICE 0.00",
                "TOTAL BALANCE 103.00",
            ]
        ),
        fontname="cour",
        fontsize=10,
    )
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]


def test_uob_adapter_scopes_rows_and_preserves_posting_dates(tmp_path: Path) -> None:
    pdf = tmp_path / "uob-synthetic.pdf"
    _write_uob_credit_card_statement(pdf)

    assert uob_credit_card_adapter().discover_account_identifiers(pdf, ()) == ("4444",)

    candidate = uob_credit_card_adapter().extract(
        pdf,
        (),
        expected_account_identifier="4444",
    )

    assert candidate.account_identifier == "4444"
    assert candidate.statement_date == date(2026, 1, 31)
    assert candidate.period_start == date(2026, 1, 1)
    assert candidate.period_end == date(2026, 1, 31)
    assert candidate.currency == "SGD"
    assert candidate.opening_balance_text == "100.00"
    assert candidate.closing_balance_text == "103.00"
    assert candidate.candidate_row_count == 3
    assert [row.posted_amount_text for row in candidate.rows] == ["-10.00", "5.00", "2.00"]
    assert [row.provider_transaction_date for row in candidate.rows] == [
        date(2026, 1, 10),
        date(2026, 1, 20),
        date(2026, 1, 25),
    ]
    assert [row.posting_date for row in candidate.rows] == [
        date(2026, 1, 11),
        date(2026, 1, 21),
        date(2026, 1, 26),
    ]
    assert [row.transaction_kind_hint for row in candidate.rows] == [
        "expense",
        "transfer",
        "refund",
    ]
    assert all(row.locator.page_number == 1 for row in candidate.rows)
    assert re.fullmatch(r"uob:2026-01-31:[0-9a-f]{16}", candidate.statement_identity)


def test_uob_adapter_fails_closed_for_an_unconfigured_card(tmp_path: Path) -> None:
    pdf = tmp_path / "uob-synthetic.pdf"
    _write_uob_credit_card_statement(pdf)

    with pytest.raises(StatementAdapterError, match="account_mismatch"):
        uob_credit_card_adapter().extract(
            pdf,
            (),
            expected_account_identifier="9999",
        )


def test_uob_adapter_version_includes_monopoly_and_billzebub_versions() -> None:
    assert uob_credit_card_adapter().version == "monopoly-0.21.6+uob-credit-1"
