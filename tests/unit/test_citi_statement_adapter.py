import re
from datetime import date
from pathlib import Path

import pymupdf
import pytest

from billzebub.statement_adapters.citi import citi_credit_card_adapter
from billzebub.statement_extraction import StatementAdapterError


def _write_citi_credit_card_statement(path: Path) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "CITIBANK",
                "Statement Date 31 Jan 2026",
                "BALANCE PREVIOUS STATEMENT 100.00",
                "1111222233334444",
                "DATE DESCRIPTION AMOUNT",
                "10 Jan FICTIONAL BOOKSHOP 10.00",
                "20 Jan CITIBANK BILL PAYMENT 5.00 CR",
                "25 Jan FICTIONAL MERCHANT REFUND (2.00)",
                "1111222233334444 103.00 10.00",
            ]
        ),
        fontname="cour",
        fontsize=10,
    )
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]


def test_citi_adapter_satisfies_credit_card_statement_contract(tmp_path: Path) -> None:
    pdf = tmp_path / "citi-synthetic.pdf"
    _write_citi_credit_card_statement(pdf)

    assert citi_credit_card_adapter().discover_account_identifiers(pdf, ()) == ("4444",)

    candidate = citi_credit_card_adapter().extract(pdf, ())

    assert candidate.account_identifier == "4444"
    assert candidate.statement_date == date(2026, 1, 31)
    assert candidate.period_start == date(2026, 1, 1)
    assert candidate.period_end == date(2026, 1, 31)
    assert candidate.currency == "SGD"
    assert candidate.opening_balance_text == "100.00"
    assert candidate.closing_balance_text == "103.00"
    assert candidate.candidate_row_count == 3
    assert [row.posted_amount_text for row in candidate.rows] == ["-10.00", "5.00", "2.00"]
    assert [row.transaction_kind_hint for row in candidate.rows] == [
        "expense",
        "transfer",
        "refund",
    ]
    assert all(row.locator.page_number == 1 for row in candidate.rows)
    assert re.fullmatch(r"citi:2026-01-31:[0-9a-f]{16}", candidate.statement_identity)


def test_citi_adapter_version_includes_monopoly_and_billzebub_versions() -> None:
    assert citi_credit_card_adapter().version == "monopoly-0.21.6+citi-credit-1"


def test_citi_adapter_fails_closed_without_one_summary_account_balance(tmp_path: Path) -> None:
    pdf = tmp_path / "citi-changed-template.pdf"
    _write_citi_credit_card_statement(pdf)
    document = pymupdf.open(pdf)  # type: ignore[no-untyped-call]
    page = document[0]
    page.add_redact_annot(page.rect)
    page.apply_redactions()
    document.save(tmp_path / "citi-unparseable.pdf")  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]

    with pytest.raises(StatementAdapterError, match="ocr_required"):
        citi_credit_card_adapter().extract(tmp_path / "citi-unparseable.pdf", ())
