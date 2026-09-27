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
    assert citi_credit_card_adapter().version == "monopoly-0.21.6+citi-credit-2"


def _write_lines(path: Path, lines: list[str]) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text((72, 72), "\n".join(lines), fontname="cour", fontsize=10)
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]


def _premiermiles_lines(due_lines: list[str] | None = None) -> list[str]:
    return [
        "CITIBANK",
        *(due_lines or []),
        "BALANCE PREVIOUS STATEMENT 100.00",
        "1111222233334444",
        "DATE DESCRIPTION AMOUNT",
        "10 Jul FICTIONAL BOOKSHOP 10.00",
        "20 Jul CITIBANK BILL PAYMENT 5.00 CR",
        "25 Jul FICTIONAL MERCHANT REFUND (2.00)",
        "1111222233334444 103.00 10.00",
    ]


@pytest.mark.parametrize(
    "due_lines",
    [
        ["Payment Due Date: July 30, 2026"],
        ["Payment Due Date:", "July 30, 2026"],
    ],
)
def test_citi_premiermiles_uses_payment_due_date_when_statement_date_is_absent(
    tmp_path: Path,
    due_lines: list[str],
) -> None:
    pdf = tmp_path / "eStatement_July.pdf"
    _write_lines(pdf, _premiermiles_lines(due_lines))

    assert citi_credit_card_adapter().discover_account_identifiers(pdf, ()) == ("4444",)
    candidate = citi_credit_card_adapter().extract(pdf, ())

    assert candidate.statement_date == date(2026, 7, 30)
    assert candidate.period_start == date(2026, 7, 1)
    assert candidate.period_end == date(2026, 7, 30)
    assert [row.provider_transaction_date for row in candidate.rows] == [
        date(2026, 7, 10),
        date(2026, 7, 20),
        date(2026, 7, 25),
    ]
    assert [row.posted_amount_text for row in candidate.rows] == ["-10.00", "5.00", "2.00"]
    assert re.fullmatch(r"citi:2026-07-30:[0-9a-f]{16}", candidate.statement_identity)


def test_citi_rewards_statement_date_wins_over_payment_due_date_and_filename(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "eStatement_February.pdf"
    _write_lines(
        pdf,
        [
            "CITIBANK",
            "Payment Due Date: February 25, 2026",
            "Statement Date 31 Jan 2026",
            "BALANCE PREVIOUS STATEMENT 100.00",
            "1111222233334444",
            "DATE DESCRIPTION AMOUNT",
            "10 Jan FICTIONAL BOOKSHOP 10.00",
            "20 Jan CITIBANK BILL PAYMENT 5.00 CR",
            "25 Jan FICTIONAL MERCHANT REFUND (2.00)",
            "1111222233334444 103.00 10.00",
        ],
    )

    candidate = citi_credit_card_adapter().extract(pdf, ())

    assert candidate.statement_date == date(2026, 1, 31)
    assert candidate.period_start == date(2026, 1, 1)
    assert candidate.period_end == date(2026, 1, 31)
    assert [row.provider_transaction_date for row in candidate.rows] == [
        date(2026, 1, 10),
        date(2026, 1, 20),
        date(2026, 1, 25),
    ]


@pytest.mark.parametrize(
    ("filename", "statement_day"),
    [
        ("eStatement_July2026.pdf", date(2026, 7, 31)),
        ("eStatement_Jul2026.pdf", date(2026, 7, 31)),
        ("eStatement_July_2026.pdf", date(2026, 7, 31)),
        ("eStatement_Sep2026.pdf", date(2026, 9, 30)),
    ],
)
def test_citi_filename_month_year_is_cycle_end_when_no_statement_or_due_date(
    tmp_path: Path,
    filename: str,
    statement_day: date,
) -> None:
    pdf = tmp_path / filename
    _write_lines(pdf, _premiermiles_lines())

    candidate = citi_credit_card_adapter().extract(pdf, ())

    assert candidate.statement_date == statement_day
    assert candidate.period_end == statement_day
    assert candidate.period_start < statement_day
    assert all(row.provider_transaction_date <= statement_day for row in candidate.rows)


def test_citi_month_only_filename_without_a_date_fails_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "eStatement_July.pdf"
    _write_lines(pdf, _premiermiles_lines())

    with pytest.raises(StatementAdapterError, match="statement_metadata_missing"):
        citi_credit_card_adapter().extract(pdf, ())


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
