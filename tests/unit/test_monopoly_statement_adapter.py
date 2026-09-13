import re
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

import pymupdf
from monopoly.banks.base import BankBase  # type: ignore[import-untyped]
from monopoly.config import StatementConfig  # type: ignore[import-untyped]
from monopoly.constants import EntryType  # type: ignore[import-untyped]

from billzebub.statement_adapters import (
    MonopolyAdapterDefinition,
    MonopolyStatementAdapter,
    MonopolyStatementMetadata,
    MonopolyStatementSelection,
)


class SyntheticBank(BankBase):  # type: ignore[misc]
    name = "synthetic"
    credit = StatementConfig(
        statement_type=EntryType.CREDIT,
        statement_date_pattern=re.compile(r"STATEMENT DATE (\d{2} [A-Z]{3} \d{4})"),
        header_pattern=re.compile(r"DATE\s+DESCRIPTION\s+AMOUNT"),
        transaction_date_format="%d %b",
        transaction_pattern=re.compile(
            r"(?P<transaction_date>\d{2} [A-Z]{3})\s+"
            r"(?P<description>.*?)\s+"
            r"(?P<amount>\(?\d+\.\d{2}\)?)(?:\s+(?P<polarity>CR))?$"
        ),
    )
    statement_configs: ClassVar[list[StatementConfig]] = [credit]
    identifiers: ClassVar[list[Any]] = []


def selection(
    statement: Any,
    _expected_account_identifier: str | None,
) -> MonopolyStatementSelection:
    text = "\n".join(page.raw_text for page in statement.pages)

    def value(pattern: str) -> str:
        match = re.search(pattern, text)
        assert match is not None
        return match.group(1)

    return MonopolyStatementSelection(
        metadata=MonopolyStatementMetadata(
            statement_identity="synthetic-2026-01",
            account_identifier=value(r"ACCOUNT\s+(\S+)"),
            statement_date=date(2026, 1, 31),
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            currency="SGD",
            opening_balance_text=value(r"PREVIOUS BALANCE\s+(\d+\.\d{2})"),
            closing_balance_text=value(r"CLOSING BALANCE\s+(\d+\.\d{2})"),
        ),
        includes_line=lambda _page_number, _line_number: True,
    )


def create_statement(path: Path) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "SYNTHETIC BANK",
                "STATEMENT DATE 31 JAN 2026",
                "PERIOD 01 JAN 2026 TO 31 JAN 2026",
                "ACCOUNT SYNTHETIC-001",
                "PREVIOUS BALANCE 100.00",
                "DATE DESCRIPTION AMOUNT",
                "10 JAN SYNTHETIC PURCHASE 10.00",
                "20 JAN SYNTHETIC CARD PAYMENT 5.00 CR",
                "25 JAN SYNTHETIC REFUND (2.00)",
                "CLOSING BALANCE 103.00",
            ]
        ),
        fontname="cour",
        fontsize=10,
    )
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]


def test_monopoly_bridge_recovers_exact_strings_and_provenance_before_float(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "synthetic.pdf"
    create_statement(pdf)
    adapter = MonopolyStatementAdapter(
        key="synthetic-monopoly",
        adapter_version="synthetic-1",
        institution="synthetic-bank",
        definition=MonopolyAdapterDefinition(
            bank=SyntheticBank,
            candidate_line_pattern=re.compile(r"^\s*\d{2} [A-Z]{3}.*\d+\.\d{2}"),
            selection=selection,
            kind_hint=lambda description, _polarity: (
                "transfer"
                if "PAYMENT" in description
                else "refund"
                if "REFUND" in description
                else "expense"
            ),
        ),
    )

    candidate = adapter.extract(pdf, ())

    assert adapter.version == "monopoly-0.21.6+synthetic-1"
    assert candidate.candidate_row_count == 3
    assert [row.posted_amount_text for row in candidate.rows] == ["-10.00", "5.00", "2.00"]
    assert [row.transaction_kind_hint for row in candidate.rows] == [
        "expense",
        "transfer",
        "refund",
    ]
    assert all(row.locator.page_number == 1 for row in candidate.rows)
    assert all(row.locator.text_sha256 is not None for row in candidate.rows)
