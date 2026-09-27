"""Citi Singapore credit-card statement adapter."""

from __future__ import annotations

import calendar
import hashlib
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, ClassVar

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
_STATEMENT_DATE_MISSING = "Statement date not found"
_DATE_TEXT = r"(?:[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
_PAYMENT_DUE_DATE_PATTERN = re.compile(
    rf"Payment\s+Due\s+Date\s*:?\s*(?P<due>{_DATE_TEXT})",
    re.IGNORECASE,
)
_PAYMENT_DUE_LABEL_PATTERN = re.compile(r"Payment\s+Due\s+Date\s*:?\s*$", re.IGNORECASE)
_DATE_ONLY_PATTERN = re.compile(rf"^\s*(?P<due>{_DATE_TEXT})\s*$", re.IGNORECASE)
_MONTH_WORDS: tuple[tuple[str, int], ...] = (
    ("january", 1),
    ("february", 2),
    ("march", 3),
    ("april", 4),
    ("may", 5),
    ("june", 6),
    ("july", 7),
    ("august", 8),
    ("september", 9),
    ("sept", 9),
    ("october", 10),
    ("november", 11),
    ("december", 12),
    ("jan", 1),
    ("feb", 2),
    ("mar", 3),
    ("apr", 4),
    ("jun", 6),
    ("jul", 7),
    ("aug", 8),
    ("sep", 9),
    ("oct", 10),
    ("nov", 11),
    ("dec", 12),
)
_MONTH_NUMBERS = dict(_MONTH_WORDS)
_FILENAME_STATEMENT_MONTH = re.compile(
    r"(?:^|_)(?P<month>"
    + "|".join(sorted((word for word, _month in _MONTH_WORDS), key=len, reverse=True))
    + r")(?:[_\-\s]?(?P<year>\d{4}))?(?=[._\-]|$)",
    re.IGNORECASE,
)
# Monopoly names a missing Statement Date from ``_<Mon><YYYY>`` and sets the day to 1.
# PremierMiles files are ``eStatement_July.pdf`` / ``eStatement_July2026.pdf``, so this
# adapter owns that fallback and keeps Monopoly's Citibank statement-date pattern.
_CITI_CREDIT = replace(Citibank.credit, filename_fallback_pattern=None)


class _CitiCreditBank(Citibank):  # type: ignore[misc]
    """Citibank credit config with statement-date fallback resolved here."""

    credit = _CITI_CREDIT
    statement_configs: ClassVar[list[Any]] = [_CITI_CREDIT, Citibank.credit_us]


def citi_credit_card_adapter(*, bank: type[Any] = _CitiCreditBank) -> MonopolyStatementAdapter:
    """Build the versioned Citi adapter used by the worker registry."""
    return MonopolyStatementAdapter(
        key="citi-credit-card",
        adapter_version="citi-credit-2",
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
    statement_date = _statement_date(statement, lines)
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


def _statement_date(statement: Any, lines: list[str]) -> date:
    try:
        raw_statement_date = statement.statement_date
    except ValueError as error:
        if str(error) != _STATEMENT_DATE_MISSING:
            raise
        resolved = _fallback_statement_date(statement, lines)
        if resolved is None:
            raise StatementAdapterError(
                "statement_metadata_missing",
                {"field": "statement_date"},
            ) from error
        # Prime Monopoly's cached date so later reads use the same cycle end.
        statement.__dict__["statement_date"] = datetime(
            resolved.year,
            resolved.month,
            resolved.day,
            tzinfo=UTC,
        )
        return resolved
    if not isinstance(raw_statement_date, datetime):
        raise StatementAdapterError("statement_metadata_missing", {"field": "statement_date"})
    return raw_statement_date.date()


def _fallback_statement_date(statement: Any, lines: list[str]) -> date | None:
    """Cycle end when PremierMiles omits the Statement Date line.

    Payment Due Date is the preferred anchor: it is after the billing cycle, so
    transaction dates on the statement are not after it. ``_cycle_start`` then
    derives the period. A filename month and year is the next source, using the
    last day of that month. ``eStatement_July.pdf`` has no year, so it cannot
    stand alone.
    """
    due_dates = _payment_due_dates(lines)
    if len(due_dates) > 1:
        raise StatementAdapterError(
            "statement_metadata_ambiguous",
            {"field": "statement_date", "match_count": len(due_dates)},
        )
    if len(due_dates) == 1:
        return due_dates[0]
    return _filename_statement_date(getattr(statement, "file_path", None))


def _payment_due_dates(lines: list[str]) -> tuple[date, ...]:
    found: list[date] = []
    for index, line in enumerate(lines):
        match = _PAYMENT_DUE_DATE_PATTERN.search(line)
        parsed = _parse_date_text(match.group("due")) if match is not None else None
        if parsed is None and _PAYMENT_DUE_LABEL_PATTERN.search(line) and index + 1 < len(lines):
            next_line = _DATE_ONLY_PATTERN.search(lines[index + 1])
            parsed = _parse_date_text(next_line.group("due")) if next_line is not None else None
        if parsed is not None and parsed not in found:
            found.append(parsed)
    return tuple(found)


def _parse_date_text(text: str) -> date | None:
    parts = text.replace(",", " ").split()
    if len(parts) != 3:
        return None
    if parts[0].isdigit() and parts[2].isdigit():
        day_text, month_text, year_text = parts
    elif parts[1].isdigit() and parts[2].isdigit():
        month_text, day_text, year_text = parts
    else:
        return None
    month = _MONTH_NUMBERS.get(month_text.casefold())
    if month is None:
        return None
    try:
        return date(int(year_text), month, int(day_text))
    except ValueError:
        return None


def _filename_statement_date(file_path: object) -> date | None:
    if not isinstance(file_path, Path):
        return None
    dated = {
        (int(match.group("year")), _MONTH_NUMBERS[match.group("month").casefold()])
        for match in _FILENAME_STATEMENT_MONTH.finditer(file_path.name)
        if match.group("year") is not None
    }
    if len(dated) != 1:
        return None
    year, month = dated.pop()
    return date(year, month, calendar.monthrange(year, month)[1])


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
