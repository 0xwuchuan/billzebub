"""Citi Singapore credit-card statement adapter."""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from monopoly.banks.citibank.citibank import Citibank  # type: ignore[import-untyped]

from billzebub.statement_adapters.monopoly import (
    MonopolyAdapterDefinition,
    MonopolyStatementAdapter,
    MonopolyStatementMetadata,
    MonopolyStatementSelection,
)
from billzebub.statement_extraction import StatementAdapterError

_AMOUNT = r"(?P<amount>\(?\s*\d+(?:,\d{3})*\.\d+\s*\)?)(?:\s*(?P<polarity>CR|DR|DB|\+|-))?"
_ACCOUNT_BALANCE_PATTERN = re.compile(
    rf"^\s*(?P<account>\d{{16}})\s+(?:S\$|\$)?\s*{_AMOUNT}",
    re.IGNORECASE,
)
_CANDIDATE_LINE_PATTERN = re.compile(
    r"^\s*\d{2}\s+[A-Za-z]{3}\s+.+?\s+"
    r"\(?\s*\d{1,3}(?:,\d{3})*\.\d+\s*\)?"
    r"(?:\s+(?:CR|DR|DB|\+|-))?\s*$",
    re.IGNORECASE,
)
_PAYMENT_PATTERN = re.compile(
    r"\b(?:PAYMENT|GIRO\s+PAYMENT|CARD\s+PAYMENT|BILL\s+PAYMENT)\b",
    re.IGNORECASE,
)
_CASH_PATTERN = re.compile(r"\b(?:CASH\s+ADVANCE|CASH\s+WITHDRAWAL|ATM\s+CASH)\b", re.IGNORECASE)
_DETAIL_ACCOUNT_PATTERN = re.compile(r"(?<!\d)(?P<account>(?:\d{4}[\s-]*){4})(?!\d)")


def citi_credit_card_adapter(*, bank: type[Any] = Citibank) -> MonopolyStatementAdapter:
    """Build the versioned Citi adapter used by the worker registry."""
    return MonopolyStatementAdapter(
        key="citi-credit-card",
        adapter_version="citi-credit-1",
        institution="citi",
        definition=MonopolyAdapterDefinition(
            bank=bank,
            candidate_line_pattern=_CANDIDATE_LINE_PATTERN,
            selection=_selection,
            kind_hint=_kind_hint,
        ),
    )


def _selection(
    statement: Any,
    expected_account_identifier: str | None,
) -> MonopolyStatementSelection:
    metadata = _metadata(statement)
    if (
        expected_account_identifier is not None
        and metadata.account_identifier != expected_account_identifier
    ):
        raise StatementAdapterError("account_mismatch")
    return MonopolyStatementSelection(
        metadata=metadata,
        includes_line=lambda _page_number, _line_number: True,
    )


def _metadata(statement: Any) -> MonopolyStatementMetadata:
    lines = [line for page in statement.pages for line in page.lines]
    statement_date = statement.statement_date.date()
    account_number = _detail_account_number(statement)
    closing_balance = _account_balance(lines, account_number)
    opening_balance = _single_balance(
        lines,
        statement.config.prev_balance_pattern,
        "opening_balance",
    )
    period_start = _cycle_start(statement_date)
    account_digest = hashlib.sha256(account_number.encode()).hexdigest()[:16]
    return MonopolyStatementMetadata(
        statement_identity=f"citi:{statement_date.isoformat()}:{account_digest}",
        account_identifier=account_number[-4:],
        statement_date=statement_date,
        period_start=period_start,
        period_end=statement_date,
        currency="SGD",
        opening_balance_text=opening_balance,
        closing_balance_text=closing_balance,
    )


def _detail_account_number(statement: Any) -> str:
    accounts: set[str] = set()
    for page in statement.pages:
        for index, line in enumerate(page.lines):
            if statement.config.header_pattern.search(line) is None:
                continue
            for prior_line in page.lines[max(0, index - 10) : index]:
                for match in _DETAIL_ACCOUNT_PATTERN.finditer(prior_line):
                    accounts.add(re.sub(r"[\s-]", "", match.group("account")))
    if len(accounts) != 1:
        code = "account_identifier_missing" if not accounts else "account_identifier_ambiguous"
        raise StatementAdapterError(code, {"identifier_count": len(accounts)})
    return accounts.pop()


def _account_balance(lines: list[str], account_number: str) -> str:
    balances = [
        _balance_effect(match.group("amount"), match.groupdict().get("polarity"))
        for line in lines
        for match in [_ACCOUNT_BALANCE_PATTERN.search(line)]
        if match is not None and match.group("account") == account_number
    ]
    if len(balances) != 1:
        raise StatementAdapterError(
            "statement_metadata_ambiguous",
            {"field": "closing_balance", "match_count": len(balances)},
        )
    return balances[0]


def _single_balance(lines: list[str], pattern: re.Pattern[str] | None, field: str) -> str:
    if pattern is None:
        raise StatementAdapterError("statement_metadata_missing", {"field": field})
    matches = [match for line in lines if (match := pattern.search(line))]
    if len(matches) != 1:
        raise StatementAdapterError(
            "statement_metadata_ambiguous",
            {"field": field, "match_count": len(matches)},
        )
    fields = matches[0].groupdict()
    return _balance_effect(fields["amount"], fields.get("polarity"))


def _balance_effect(amount_text: str, polarity: str | None) -> str:
    cleaned = re.sub(r"[^\d.]", "", amount_text)
    try:
        amount = Decimal(cleaned)
    except InvalidOperation as error:
        raise StatementAdapterError("invalid_decimal_string") from error
    if not amount.is_finite():
        raise StatementAdapterError("invalid_decimal_string")
    is_credit = polarity in {"CR", "+"} or (
        amount_text.strip().startswith("(") and amount_text.strip().endswith(")")
    )
    return format(-abs(amount) if is_credit else abs(amount), "f")


def _cycle_start(statement_date: date) -> date:
    if statement_date.month == 1:
        previous_year, previous_month = statement_date.year - 1, 12
    else:
        previous_year, previous_month = statement_date.year, statement_date.month - 1
    previous_day = min(statement_date.day, calendar.monthrange(previous_year, previous_month)[1])
    return date(previous_year, previous_month, previous_day) + timedelta(days=1)


def _kind_hint(description: str, polarity: str | None) -> str:
    if polarity in {"CR", "+"}:
        return "transfer" if _PAYMENT_PATTERN.search(description) else "refund"
    if _CASH_PATTERN.search(description):
        return "cash_withdrawal"
    return "expense"
