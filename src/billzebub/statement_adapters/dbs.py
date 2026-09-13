"""DBS Singapore credit-card statement adapter."""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from monopoly.banks.dbs.dbs import Dbs  # type: ignore[import-untyped]

from billzebub.statement_adapters.monopoly import (
    MonopolyAdapterDefinition,
    MonopolyStatementAdapter,
    MonopolyStatementMetadata,
    MonopolyStatementSelection,
)
from billzebub.statement_extraction import StatementAdapterError

_AMOUNT = r"(?P<amount>\(?\s*\d{1,3}(?:,\d{3})*\.\d+\s*\)?)(?:\s*(?P<polarity>CR|DR|DB|\+|-))?"
_CLOSING_BALANCE_PATTERN = re.compile(
    rf"^\s*TOTAL:\s*(?:\(\s*S\$\s*\)|S\$|\$)?\s*{_AMOUNT}\s*$",
    re.IGNORECASE,
)
_CARD_LABEL_PATTERN = re.compile(
    r"\bCARD\s+(?:NUMBER|NO\.?)\b\s*[:#]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_CARD_TOKEN_PATTERN = re.compile(r"(?<![Xx*\d])(?P<number>(?:[Xx*\d][\s-]*){16})(?![Xx*\d])")
_CANDIDATE_LINE_PATTERN = re.compile(
    r"^\s*\d{2}\s+[A-Za-z]{3}\s+.+?\s+"
    r"\(?\s*\d{1,3}(?:,\d{3})*\.\d+\s*\)?"
    r"(?:\s+(?:CR|DR|DB|\+|-))?\s*$",
    re.IGNORECASE,
)
_PAYMENT_PATTERN = re.compile(
    r"\b(?:PAYMENT\s+(?:RECEIVED|THANK\s+YOU|BY)|GIRO\s+PAYMENT|CARD\s+PAYMENT|BILL\s+PAYMENT)\b",
    re.IGNORECASE,
)
_CASH_PATTERN = re.compile(r"\b(?:CASH\s+ADVANCE|CASH\s+WITHDRAWAL|ATM\s+CASH)\b", re.IGNORECASE)


def dbs_credit_card_adapter(*, bank: type[Any] = Dbs) -> MonopolyStatementAdapter:
    """Build the versioned DBS adapter used by the worker registry."""
    return MonopolyStatementAdapter(
        key="dbs-credit-card",
        adapter_version="dbs-credit-1",
        institution="dbs",
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
    account_identifier = _account_identifier(lines)
    opening_balance = _single_balance(
        lines,
        statement.config.prev_balance_pattern,
        "opening_balance",
    )
    closing_balance = _single_balance(lines, _CLOSING_BALANCE_PATTERN, "closing_balance")
    period_start = _cycle_start(statement_date)
    account_digest = hashlib.sha256(account_identifier.encode()).hexdigest()[:16]
    return MonopolyStatementMetadata(
        statement_identity=f"dbs:{statement_date.isoformat()}:{account_digest}",
        account_identifier=account_identifier,
        statement_date=statement_date,
        period_start=period_start,
        period_end=statement_date,
        currency="SGD",
        opening_balance_text=opening_balance,
        closing_balance_text=closing_balance,
    )


def _account_identifier(lines: list[str]) -> str:
    identifiers: set[str] = set()
    for line in lines:
        label = _CARD_LABEL_PATTERN.search(line)
        if label is None:
            continue
        token = _CARD_TOKEN_PATTERN.search(label.group("rest"))
        if token is None:
            continue
        normalized = re.sub(r"[\s-]", "", token.group("number"))
        if len(normalized) == 16 and normalized[-4:].isdigit():
            identifiers.add(normalized[-4:])
    if len(identifiers) != 1:
        code = "account_identifier_missing" if not identifiers else "account_identifier_ambiguous"
        raise StatementAdapterError(code, {"identifier_count": len(identifiers)})
    return identifiers.pop()


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
