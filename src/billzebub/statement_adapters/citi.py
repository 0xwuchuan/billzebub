"""Citi Singapore credit-card statement adapter."""

from __future__ import annotations

import calendar
import hashlib
import re
from collections.abc import Callable
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
_MASKED_CARD_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:[Xx*]{4}[\s-]*){3}(?P<last4>\d{4})(?!\d)")
_MASKED_ACCOUNT_BALANCE_PATTERN = re.compile(
    rf"^\s*(?:[Xx*]{{4}}[\s-]*){{3}}(?P<last4>\d{{4}})\s+(?:S\$|\$)?\s*{_AMOUNT}",
    re.IGNORECASE,
)
_STATEMENT_DATE_MISSING = "Statement date not found"
# Month-first with a comma is the Rewards/PremierMiles due-date line. The other
# arms cover day-first commas, hyphenated months, ISO dates, and numeric DMY.
_DATE_TEXT = (
    r"(?:"
    r"[A-Za-z]{3,9}\s+\d{1,2},\s+\d{4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9},\s+\d{4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2}\s+\d{4}"
    r"|\d{1,2}-[A-Za-z]{3,9}-\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}/\d{1,2}/\d{4}"
    r")"
)
_RANGE_SEP = r"\s*(?:-|\u2013|\u2014|\bto\b)\s*"
_PAYMENT_DUE_DATE_PATTERN = re.compile(
    rf"Payment\s+Due\s+Date\s*:?\s*(?P<due>{_DATE_TEXT})",
    re.IGNORECASE,
)
_BLANK_DUE_TOKEN = r"-{2,}|\u2014|\u2013|\u2015"
_BLANK_DUE_PATTERN = re.compile(
    rf"Payment\s+Due\s+Date\s*:?\s*(?P<blank>{_BLANK_DUE_TOKEN})\s*$",
    re.IGNORECASE,
)
_BLANK_ONLY_PATTERN = re.compile(rf"^\s*(?P<blank>{_BLANK_DUE_TOKEN})\s*$")
_GRAND_TOTAL_PATTERN = re.compile(
    rf"^\s*GRAND\s+TOTAL\s*(?:\|+|:)?\s*(?:S\$|\$)?\s*{_AMOUNT}\s*$",
    re.IGNORECASE,
)
_TRANSACTION_DAY_PATTERN = re.compile(r"^\s*(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3})\b")
_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
_CYCLE_SPAN_DAYS = 35
_PAYMENT_DUE_LABEL_PATTERN = re.compile(r"Payment\s+Due\s+Date\s*:?\s*$", re.IGNORECASE)
_DATE_ONLY_PATTERN = re.compile(rf"^\s*(?P<due>{_DATE_TEXT})\s*$", re.IGNORECASE)
_STATEMENT_DATE_PATTERN = re.compile(
    rf"Statement\s+Date\s*:?\s*(?P<due>{_DATE_TEXT})",
    re.IGNORECASE,
)
_STATEMENT_DATE_LABEL_PATTERN = re.compile(r"Statement\s+Date\s*:?\s*$", re.IGNORECASE)
_PERIOD_LABEL = r"(?:Statement\s+(?:Date|Period)|Billing\s+Period)"
_STATEMENT_PERIOD_PATTERN = re.compile(
    rf"{_PERIOD_LABEL}\s*:?\s*(?P<start>{_DATE_TEXT}){_RANGE_SEP}(?P<end>{_DATE_TEXT})",
    re.IGNORECASE,
)
_PERIOD_LABEL_ONLY_PATTERN = re.compile(rf"{_PERIOD_LABEL}\s*:?\s*$", re.IGNORECASE)
_DATE_RANGE_LINE_PATTERN = re.compile(
    rf"^\s*(?P<start>{_DATE_TEXT}){_RANGE_SEP}(?P<end>{_DATE_TEXT})\s*$",
    re.IGNORECASE,
)
_TWO_COLUMN_LABEL_PATTERN = re.compile(
    r"Statement\s+Date\b.*\bPayment\s+Due\s+Date\b",
    re.IGNORECASE,
)
_TWO_DATES_PATTERN = re.compile(
    rf"(?P<first>{_DATE_TEXT}).*?(?P<second>{_DATE_TEXT})",
    re.IGNORECASE,
)
_DATE_TEXT_PATTERN = re.compile(_DATE_TEXT)
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
_MONTH_YEAR_PATTERN = re.compile(
    r"(?<![\d])(?<![\d]\s)\b(?P<month>"
    + "|".join(sorted((word for word, _month in _MONTH_WORDS), key=len, reverse=True))
    + r")\s+(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
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
        adapter_version="citi-credit-4",
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
    metadata = _metadata(statement, expected_account_identifier)
    if (
        expected_account_identifier is not None
        and metadata.account_identifier != expected_account_identifier.strip()
    ):
        raise StatementAdapterError("account_mismatch")
    return MonopolyStatementSelection(
        metadata=metadata,
        includes_line=lambda _page_number, _line_number: True,
    )


def _metadata(
    statement: Any,
    expected_account_identifier: str | None,
) -> MonopolyStatementMetadata:
    lines = [line for page in statement.pages for line in page.lines]
    statement_date = _statement_date(statement, lines)
    account_number = _account_number(statement, lines, expected_account_identifier)
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
            raise _metadata_failure(
                "statement_date",
                "missing",
                _blank_due_tokens(lines),
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
        raise _metadata_failure("statement_date", "missing", [])
    return raw_statement_date.date()


def _fallback_statement_date(statement: Any, lines: list[str]) -> date | None:
    """Cycle end when Monopoly cannot parse a Statement Date line.

    A labeled statement date wins, including a colon or the next line, and a
    two-column header whose dates sit on the following line. A statement-period
    range is next: dateparser rejects ``12 Feb 2026 - 11 Mar 2026``, which is
    the March PremierMiles shape, and the range end is the cycle end.
    Payment Due Date remains the anchor when those are absent. ``---`` is a
    blank due date, not a parsed date and not an ambiguous candidate. A filename
    month and year uses the last day of that month. Transaction dates are used
    only when one printed year places every transaction inside a 35-day cycle.
    A zero-total statement with no transactions then uses one printed
    ``Month YYYY`` as that month's last day.
    """
    for found in (
        _labeled_statement_dates(lines),
        _statement_period_ends(lines),
        _payment_due_dates(lines),
    ):
        resolved = _one_date(found)
        if resolved is not None:
            return resolved
    filename_date = _filename_statement_date(getattr(statement, "file_path", None))
    if filename_date is not None:
        return filename_date
    from_transactions = _statement_date_from_transactions(lines)
    if from_transactions is not None:
        return from_transactions
    return _zero_balance_statement_date(lines)


def _one_date(found: tuple[date, ...]) -> date | None:
    if len(found) > 1:
        raise _metadata_failure(
            "statement_date",
            "ambiguous",
            [item.isoformat() for item in found],
        )
    if len(found) == 1:
        return found[0]
    return None


def _labeled_statement_dates(lines: list[str]) -> tuple[date, ...]:
    found: list[date] = []
    for index, line in enumerate(lines):
        if _STATEMENT_PERIOD_PATTERN.search(line) is not None:
            continue
        parsed = _two_column_statement_date(lines, index)
        if parsed is None:
            parsed = _single_statement_date(lines, index)
        if parsed is not None and parsed not in found:
            found.append(parsed)
    return tuple(found)


def _two_column_statement_date(lines: list[str], index: int) -> date | None:
    line = lines[index]
    if _TWO_COLUMN_LABEL_PATTERN.search(line) is None or _DATE_TEXT_PATTERN.search(line):
        return None
    if index + 1 >= len(lines):
        return None
    match = _TWO_DATES_PATTERN.search(lines[index + 1])
    if match is None:
        return None
    return _parse_date_text(match.group("first"))


def _single_statement_date(lines: list[str], index: int) -> date | None:
    line = lines[index]
    match = _STATEMENT_DATE_PATTERN.search(line)
    parsed = _parse_date_text(match.group("due")) if match is not None else None
    if (
        parsed is None
        and _STATEMENT_DATE_LABEL_PATTERN.search(line) is not None
        and index + 1 < len(lines)
        and _DATE_RANGE_LINE_PATTERN.search(lines[index + 1]) is None
    ):
        next_line = _DATE_ONLY_PATTERN.search(lines[index + 1])
        parsed = _parse_date_text(next_line.group("due")) if next_line is not None else None
    return parsed


def _statement_period_ends(lines: list[str]) -> tuple[date, ...]:
    found: list[date] = []
    for index, line in enumerate(lines):
        match = _STATEMENT_PERIOD_PATTERN.search(line)
        parsed = _parse_date_text(match.group("end")) if match is not None else None
        if (
            parsed is None
            and _PERIOD_LABEL_ONLY_PATTERN.search(line) is not None
            and index + 1 < len(lines)
        ):
            next_range = _DATE_RANGE_LINE_PATTERN.search(lines[index + 1])
            parsed = _parse_date_text(next_range.group("end")) if next_range is not None else None
        if parsed is not None and parsed not in found:
            found.append(parsed)
    return tuple(found)


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
    stripped = text.strip()
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", stripped)
    if iso is not None:
        return _calendar_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    numeric = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", stripped)
    if numeric is not None:
        return _calendar_date(int(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1)))
    hyphenated = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3,9})-(\d{4})", stripped)
    if hyphenated is not None:
        month = _MONTH_NUMBERS.get(hyphenated.group(2).casefold())
        if month is None:
            return None
        return _calendar_date(int(hyphenated.group(3)), month, int(hyphenated.group(1)))
    parts = stripped.replace(",", " ").split()
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
    return _calendar_date(int(year_text), month, int(day_text))


def _calendar_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
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


def _account_number(
    statement: Any,
    lines: list[str],
    expected_account_identifier: str | None,
) -> str:
    """Card number used for identity, digest, and the closing-balance line.

    The 16-digit number in the ten lines above the transaction header is the
    primary key. PremierMiles text often has no such number. A masked last4 in
    that window is the same identifier. Otherwise the Financial Account's
    configured last4 is the fallback, and a unique summary line ending in that
    last4 supplies the full number for the existing balance match.
    """
    full_accounts: set[str] = set()
    masked_last4: set[str] = set()
    for page in statement.pages:
        for index, line in enumerate(page.lines):
            if statement.config.header_pattern.search(line) is None:
                continue
            for prior_line in page.lines[max(0, index - 10) : index]:
                for match in _DETAIL_ACCOUNT_PATTERN.finditer(prior_line):
                    full_accounts.add(re.sub(r"[\s-]", "", match.group("account")))
                for match in _MASKED_CARD_PATTERN.finditer(prior_line):
                    masked_last4.add(match.group("last4"))
    if len(full_accounts) > 1:
        raise StatementAdapterError(
            "account_identifier_ambiguous",
            {"identifier_count": len(full_accounts)},
        )
    if len(full_accounts) == 1:
        return full_accounts.pop()
    if len(masked_last4) > 1:
        raise StatementAdapterError(
            "account_identifier_ambiguous",
            {"identifier_count": len(masked_last4)},
        )
    configured = _configured_last4(expected_account_identifier)
    if len(masked_last4) == 1:
        printed = masked_last4.pop()
        if configured is not None and configured != printed:
            raise StatementAdapterError("account_mismatch")
        return _unique_balance_pan(lines, printed) or printed
    if configured is None:
        raise StatementAdapterError("account_identifier_missing", {"identifier_count": 0})
    printed_accounts = _balance_accounts(lines)
    matching = {account for account in printed_accounts if account.endswith(configured)}
    if len(matching) > 1:
        raise StatementAdapterError(
            "account_identifier_ambiguous",
            {"identifier_count": len(matching)},
        )
    if len(matching) == 1:
        return matching.pop()
    if printed_accounts:
        raise StatementAdapterError("account_mismatch")
    return configured


def _configured_last4(expected_account_identifier: str | None) -> str | None:
    if expected_account_identifier is None:
        return None
    token = expected_account_identifier.strip()
    if re.fullmatch(r"\d{4}", token) is None:
        return None
    return token


def _unique_balance_pan(lines: list[str], last4: str) -> str | None:
    matching = {account for account in _balance_accounts(lines) if account.endswith(last4)}
    if len(matching) > 1:
        raise StatementAdapterError(
            "account_identifier_ambiguous",
            {"identifier_count": len(matching)},
        )
    if len(matching) == 1:
        return matching.pop()
    return None


def _balance_accounts(lines: list[str]) -> set[str]:
    return {
        match.group("account")
        for line in lines
        if (match := _ACCOUNT_BALANCE_PATTERN.search(line)) is not None
    }


def _account_balance(lines: list[str], account_number: str) -> str:
    exact = _balance_amounts(
        lines,
        lambda match: match.group("account") == account_number,
    )
    if len(account_number) == 16:
        balances = exact
    else:
        balances = exact or _balance_amounts(
            lines,
            lambda match: match.group("account").endswith(account_number),
        )
        if not balances:
            balances = [
                _balance_effect(match.group("amount"), match.groupdict().get("polarity"))
                for line in lines
                if (match := _MASKED_ACCOUNT_BALANCE_PATTERN.search(line)) is not None
                and match.group("last4") == account_number
            ]
    distinct = _distinct(balances)
    if len(distinct) > 1:
        raise _metadata_failure("closing_balance", "ambiguous", distinct)
    if len(distinct) == 1:
        return distinct[0]
    # PremierMiles prints GRAND TOTAL and never a card-number amount line.
    totals = _grand_total_amounts(lines)
    if len(totals) > 1:
        raise _metadata_failure("closing_balance", "ambiguous", totals)
    if len(totals) == 1:
        return totals[0]
    raise _metadata_failure("closing_balance", "missing", [])


def _balance_amounts(
    lines: list[str],
    include: Callable[[re.Match[str]], bool],
) -> list[str]:
    return [
        _balance_effect(match.group("amount"), match.groupdict().get("polarity"))
        for line in lines
        if (match := _ACCOUNT_BALANCE_PATTERN.search(line)) is not None and include(match)
    ]


def _single_balance(lines: list[str], pattern: re.Pattern[str] | None, field: str) -> str:
    if pattern is None:
        raise _metadata_failure(field, "missing", [])
    amounts = [
        _balance_effect(match.group("amount"), match.groupdict().get("polarity"))
        for line in lines
        if (match := pattern.search(line)) is not None
    ]
    distinct = _distinct(amounts)
    if len(distinct) > 1:
        raise _metadata_failure(field, "ambiguous", distinct)
    if len(distinct) == 1:
        return distinct[0]
    raise _metadata_failure(field, "missing", [])


def _grand_total_amounts(lines: list[str]) -> list[str]:
    return _distinct(
        [
            _balance_effect(match.group("amount"), match.groupdict().get("polarity"))
            for line in lines
            if (match := _GRAND_TOTAL_PATTERN.search(line)) is not None
        ]
    )


def _distinct(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _metadata_failure(field: str, problem: str, candidates: list[str]) -> StatementAdapterError:
    return StatementAdapterError(
        f"statement_metadata_{problem}",
        {
            "fields": [
                {
                    "field": field,
                    "problem": problem,
                    "candidates": [_mask_candidate(candidate) for candidate in candidates],
                }
            ]
        },
    )


def _mask_candidate(text: str) -> str:
    collapsed = " ".join(text.split())

    def last4(digits: str) -> str:
        return f"••••{digits[-4:]}"

    collapsed = _DETAIL_ACCOUNT_PATTERN.sub(
        lambda match: last4(re.sub(r"[\s-]", "", match.group("account"))),
        collapsed,
    )
    collapsed = _MASKED_CARD_PATTERN.sub(
        lambda match: last4(match.group("last4")),
        collapsed,
    )
    collapsed = re.sub(r"\d{13,}", lambda match: last4(match.group(0)), collapsed)
    return collapsed[:80]


def _blank_due_tokens(lines: list[str]) -> list[str]:
    found: list[str] = []
    for index, line in enumerate(lines):
        match = _BLANK_DUE_PATTERN.search(line)
        token = match.group("blank") if match is not None else None
        if (
            token is None
            and _PAYMENT_DUE_LABEL_PATTERN.search(line) is not None
            and index + 1 < len(lines)
        ):
            blank = _BLANK_ONLY_PATTERN.search(lines[index + 1])
            token = blank.group("blank") if blank is not None else None
        if token is not None and token not in found:
            found.append(token)
    return found


def _statement_date_from_transactions(lines: list[str]) -> date | None:
    """Latest transaction date when every posted line fits one cycle.

    Transaction lines are ``DD MMM`` without a year. The year is the single
    ``20xx`` printed anywhere in the document. A span wider than 35 days shifts
    November and December back one year for a December/January cycle. A wider
    span after that shift is not one cycle, so it is not a statement date.
    """
    day_months = _transaction_day_months(lines)
    if not day_months:
        return None
    years = {int(year) for line in lines for year in _YEAR_PATTERN.findall(line)}
    if len(years) != 1:
        return None
    year = next(iter(years))
    placed = _placed_dates(year, day_months, shift_late_months=False)
    if placed is None:
        return None
    if _span_days(placed) > _CYCLE_SPAN_DAYS:
        placed = _placed_dates(year, day_months, shift_late_months=True)
        if placed is None or _span_days(placed) > _CYCLE_SPAN_DAYS:
            return None
    return max(placed)


def _transaction_day_months(lines: list[str]) -> list[tuple[int, int]] | None:
    found: list[tuple[int, int]] = []
    for line in lines:
        if _CANDIDATE_LINE_PATTERN.search(line) is None:
            continue
        match = _TRANSACTION_DAY_PATTERN.search(line)
        if match is None:
            return None
        month = _MONTH_NUMBERS.get(match.group("month").casefold())
        if month is None:
            return None
        found.append((int(match.group("day")), month))
    return found


def _placed_dates(
    year: int,
    day_months: list[tuple[int, int]],
    *,
    shift_late_months: bool,
) -> list[date] | None:
    placed: list[date] = []
    for day, month in day_months:
        used_year = year - 1 if shift_late_months and month >= 11 else year
        parsed = _calendar_date(used_year, month, day)
        if parsed is None:
            return None
        placed.append(parsed)
    return placed


def _span_days(dates: list[date]) -> int:
    return (max(dates) - min(dates)).days


def _zero_balance_statement_date(lines: list[str]) -> date | None:
    """Month-end for an empty zero-total statement with a blank due date.

    This runs only when no transaction date can be read. Inventing a day would
    forge ``citi:{date}:{digest}``. One printed ``Month YYYY`` that is not
    itself a day-month date supplies the cycle end. Several of those months
    conflict. Anything else stays missing.
    """
    day_months = _transaction_day_months(lines)
    if day_months is None or day_months:
        return None
    if not _blank_due_tokens(lines):
        return None
    if _grand_total_amounts(lines) != ["0.00"]:
        return None
    month_ends = _printed_month_ends(lines)
    if len(month_ends) > 1:
        raise _metadata_failure(
            "statement_date",
            "ambiguous",
            [item.isoformat() for item in month_ends],
        )
    if len(month_ends) == 1:
        return month_ends[0]
    return None


def _printed_month_ends(lines: list[str]) -> list[date]:
    found: list[date] = []
    for line in lines:
        if _CANDIDATE_LINE_PATTERN.search(line) is not None:
            continue
        for match in _MONTH_YEAR_PATTERN.finditer(line):
            month = _MONTH_NUMBERS.get(match.group("month").casefold())
            if month is None:
                continue
            year = int(match.group("year"))
            month_end = date(year, month, calendar.monthrange(year, month)[1])
            if month_end not in found:
                found.append(month_end)
    return found


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
