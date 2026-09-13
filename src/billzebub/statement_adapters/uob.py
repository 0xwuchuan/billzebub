"""UOB Singapore credit-card statement adapter."""

from __future__ import annotations

import calendar
import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from monopoly.banks.uob.uob import Uob  # type: ignore[import-untyped]

from billzebub.statement_adapters.monopoly import (
    MonopolyAdapterDefinition,
    MonopolyStatementAdapter,
    MonopolyStatementMetadata,
    MonopolyStatementSelection,
)
from billzebub.statement_extraction import StatementAdapterError

_AMOUNT = r"(?P<amount>\(?\s*\d+(?:,\d{3})*\.\d+\s*\)?)(?:\s*(?P<polarity>CR|DR|DB|\+|-))?"
_CARD_PATTERN = re.compile(r"(?<!\d)(?P<card>(?:\d{4}-){3}\d{4})(?!\d)")
_CLOSING_BALANCE_PATTERN = re.compile(
    rf"\bTOTAL\s+BALANCE\b.*?{_AMOUNT}\s*$",
    re.IGNORECASE,
)
_CANDIDATE_LINE_PATTERN = re.compile(
    r"^\s*\d{2}\s+[A-Za-z]{3}\s+\d{2}\s+[A-Za-z]{3}\s+.+?\s+"
    r"\(?\s*\d+(?:,\d{3})*\.\d+\s*\)?"
    r"(?:\s+(?:CR|DR|DB|\+|-))?\s*$",
    re.IGNORECASE,
)
_PAYMENT_PATTERN = re.compile(
    r"\b(?:PAYMENT|GIRO\s+PAYMENT|CARD\s+PAYMENT|BILL\s+PAYMENT)\b",
    re.IGNORECASE,
)
_CASH_PATTERN = re.compile(r"\b(?:CASH\s+ADVANCE|CASH\s+WITHDRAWAL|ATM\s+CASH)\b", re.IGNORECASE)
_ZERO_AMOUNT_PATTERN = re.compile(
    r"\s+\(?\s*0(?:\.0+)?\s*\)?(?:\s+(?:CR|DR|DB|\+|-))?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _Section:
    card_number: str
    start_page: int
    start_line: int
    end_page: int | None
    end_line: int | None

    def includes(self, page_number: int, line_number: int) -> bool:
        position = (page_number, line_number)
        if position < (self.start_page, self.start_line):
            return False
        if self.end_page is None or self.end_line is None:
            return True
        return position < (self.end_page, self.end_line)


def uob_credit_card_adapter(*, bank: type[Any] = Uob) -> MonopolyStatementAdapter:
    """Build the versioned UOB adapter used by the worker registry."""
    return MonopolyStatementAdapter(
        key="uob-credit-card",
        adapter_version="uob-credit-1",
        institution="uob",
        definition=MonopolyAdapterDefinition(
            bank=bank,
            candidate_line_pattern=_CANDIDATE_LINE_PATTERN,
            selection=_selection,
            kind_hint=_kind_hint,
            ignores_line=lambda line: _ZERO_AMOUNT_PATTERN.search(line) is not None,
            account_identifiers=_account_identifiers,
        ),
    )


def _selection(
    statement: Any,
    expected_account_identifier: str | None,
) -> MonopolyStatementSelection:
    sections = _sections(statement)
    if expected_account_identifier is None:
        if len(sections) != 1:
            raise StatementAdapterError(
                "account_identifier_ambiguous",
                {"identifier_count": len(sections)},
            )
        section = sections[0]
    else:
        matching_sections = [
            section
            for section in sections
            if section.card_number[-4:] == expected_account_identifier
        ]
        if len(matching_sections) != 1:
            code = "account_mismatch" if not matching_sections else "account_identifier_ambiguous"
            raise StatementAdapterError(code, {"identifier_count": len(matching_sections)})
        section = matching_sections[0]

    statement_date = statement.statement_date.date()
    lines = _section_lines(statement, section)
    opening_balance = _single_balance(
        lines,
        statement.config.prev_balance_pattern,
        "opening_balance",
    )
    closing_balance = _single_balance(lines, _CLOSING_BALANCE_PATTERN, "closing_balance")
    account_digest = hashlib.sha256(section.card_number.encode()).hexdigest()[:16]
    metadata = MonopolyStatementMetadata(
        statement_identity=f"uob:{statement_date.isoformat()}:{account_digest}",
        account_identifier=section.card_number[-4:],
        statement_date=statement_date,
        period_start=_cycle_start(statement_date),
        period_end=statement_date,
        currency="SGD",
        opening_balance_text=opening_balance,
        closing_balance_text=closing_balance,
    )
    return MonopolyStatementSelection(
        metadata=metadata,
        includes_line=section.includes,
    )


def _account_identifiers(statement: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(section.card_number[-4:] for section in _sections(statement)))


def _sections(statement: Any) -> tuple[_Section, ...]:
    header_markers: list[tuple[int, int, str]] = []
    for page_number, page in enumerate(statement.pages, start=1):
        marker_lines = [
            (line_number, match.group("card"))
            for line_number, line in enumerate(page.lines, start=1)
            for match in _CARD_PATTERN.finditer(line)
        ]
        for line_number, line in enumerate(page.lines, start=1):
            if statement.config.header_pattern.search(line) is None:
                continue
            prior_markers = [marker for marker in marker_lines if marker[0] < line_number]
            if not prior_markers:
                raise StatementAdapterError("account_section_marker_missing")
            marker_line, card_number = prior_markers[-1]
            if line_number - marker_line > 10:
                raise StatementAdapterError("account_section_marker_missing")
            header_markers.append((page_number, line_number, card_number))

    starts: list[tuple[int, int, str]] = []
    for marker in header_markers:
        if not starts or starts[-1][2] != marker[2]:
            starts.append(marker)
    if not starts:
        raise StatementAdapterError("account_section_missing")

    sections: list[_Section] = []
    for index, (start_page, start_line, card_number) in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else None
        sections.append(
            _Section(
                card_number=card_number,
                start_page=start_page,
                start_line=start_line,
                end_page=end[0] if end is not None else None,
                end_line=end[1] if end is not None else None,
            )
        )
    return tuple(sections)


def _section_lines(statement: Any, section: _Section) -> list[str]:
    return [
        line
        for page_number, page in enumerate(statement.pages, start=1)
        for line_number, line in enumerate(page.lines, start=1)
        if section.includes(page_number, line_number)
    ]


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
