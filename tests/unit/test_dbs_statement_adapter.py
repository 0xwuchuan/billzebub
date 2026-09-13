import re
from datetime import date
from pathlib import Path
from typing import ClassVar

import pymupdf
import pytest
from monopoly.banks.base import BankBase  # type: ignore[import-untyped]
from monopoly.banks.dbs.dbs import Dbs  # type: ignore[import-untyped]
from monopoly.config import StatementConfig  # type: ignore[import-untyped]

from billzebub.statement_adapters import configured_statement_adapters
from billzebub.statement_adapters.dbs import dbs_credit_card_adapter
from billzebub.statement_extraction import StatementAdapterError


def create_dbs_statement(path: Path, *, bank: type[BankBase] = Dbs) -> None:
    config: StatementConfig = bank.credit
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "DBS",
                "31 Jan 2026",
                "CARD NUMBER 1111 2222 3333 4444",
                "PREVIOUS BALANCE 100.00",
                "DATE DESCRIPTION AMOUNT (S$)",
                "10 Jan FICTIONAL BOOKSHOP 10.00",
                "20 Jan DBS BILL PAYMENT 5.00 CR",
                "25 Jan FICTIONAL MERCHANT REFUND (2.00)",
                "TOTAL: 103.00",
            ]
        ),
        fontname="cour",
        fontsize=10,
    )
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    assert config.statement_type is not None


def test_dbs_adapter_satisfies_credit_card_statement_contract(tmp_path: Path) -> None:
    pdf = tmp_path / "dbs-synthetic.pdf"
    create_dbs_statement(pdf)

    assert dbs_credit_card_adapter().discover_account_identifiers(pdf, ()) == ("4444",)

    candidate = dbs_credit_card_adapter().extract(pdf, ())

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
    assert re.fullmatch(r"dbs:2026-01-31:[0-9a-f]{16}", candidate.statement_identity)


def test_dbs_adapter_version_includes_monopoly_and_billzebub_versions() -> None:
    assert dbs_credit_card_adapter().version == "monopoly-0.21.6+dbs-credit-1"


def test_deployment_registry_contains_only_accepted_adapters() -> None:
    adapters = configured_statement_adapters()

    assert [(adapter.key, adapter.institution) for adapter in adapters] == [
        ("dbs-credit-card", "dbs"),
        ("citi-credit-card", "citi"),
        ("uob-credit-card", "uob"),
    ]


class ChangedDbs(BankBase):  # type: ignore[misc]
    name = "dbs"
    credit = StatementConfig(**Dbs.credit.__dict__)
    credit.header_pattern = re.compile(r"A HEADER THAT DOES NOT EXIST")
    statement_configs: ClassVar[list[StatementConfig]] = [credit]
    identifiers: ClassVar[list[object]] = []


def test_dbs_adapter_fails_closed_when_the_statement_template_changes(tmp_path: Path) -> None:
    pdf = tmp_path / "dbs-changed-template.pdf"
    create_dbs_statement(pdf, bank=ChangedDbs)

    adapter = dbs_credit_card_adapter(bank=ChangedDbs)

    with pytest.raises(StatementAdapterError, match="monopoly_adapter_failed"):
        adapter.extract(pdf, ())
