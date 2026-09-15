"""Statement Extraction coverage for calendar months in the reporting timezone."""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from billzebub.persistence.models import Extraction, FinancialAccount, FinancialAccountKind

if TYPE_CHECKING:
    from billzebub.persistence.database import Database

REPORTING_TIMEZONE = "Asia/Singapore"
DEFAULT_WINDOW_MONTHS = 6
MAX_WINDOW_MONTHS = 24


class CoverageStatus(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    PARTIAL = "partial"


class StatementCoverageError(ValueError):
    """A statement coverage request violated the window contract."""


@dataclass(frozen=True, slots=True)
class AccountMonthCoverage:
    month: date
    status: CoverageStatus


@dataclass(frozen=True, slots=True)
class AccountStatementCoverage:
    financial_account_id: UUID
    display_name: str
    slug: str
    months: tuple[AccountMonthCoverage, ...]


@dataclass(frozen=True, slots=True)
class StatementCoverageReport:
    as_of: date
    timezone: str
    window_months: int
    accounts: tuple[AccountStatementCoverage, ...]


@dataclass(frozen=True, slots=True)
class ExtractionPeriod:
    financial_account_id: UUID
    period_start: date
    period_end: date


def reporting_today(*, instant: datetime | None = None) -> date:
    """Calendar date in the Reporting timezone used for the rolling window."""
    clock = instant if instant is not None else datetime.now(ZoneInfo(REPORTING_TIMEZONE))
    return clock.astimezone(ZoneInfo(REPORTING_TIMEZONE)).date()


def rolling_months(as_of: date, months: int = DEFAULT_WINDOW_MONTHS) -> tuple[date, ...]:
    """Return the last `months` calendar months including `as_of`, oldest first."""
    _require_window(months)
    year, month = as_of.year, as_of.month
    window: list[date] = []
    for _ in range(months):
        window.append(date(year, month, 1))
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return tuple(reversed(window))


def month_end(month: date) -> date:
    """Last calendar day of the month containing `month`."""
    start = month.replace(day=1)
    return date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])


def coverage_status(
    month: date,
    periods: Sequence[tuple[date, date]],
) -> CoverageStatus:
    """Classify one calendar month from accepted Extraction period bounds."""
    start = month.replace(day=1)
    end = month_end(start)
    overlaps: list[tuple[date, date]] = []
    for period_start, period_end in periods:
        if period_start > period_end:
            continue
        clipped_start = max(start, period_start)
        clipped_end = min(end, period_end)
        if clipped_start <= clipped_end:
            overlaps.append((clipped_start, clipped_end))
    if not overlaps:
        return CoverageStatus.MISSING
    merged = _merge_days(overlaps)
    if merged == ((start, end),):
        return CoverageStatus.PRESENT
    return CoverageStatus.PARTIAL


def coverage_for_accounts(
    accounts: Sequence[tuple[UUID, str, str]],
    periods: Sequence[ExtractionPeriod],
    *,
    as_of: date,
    months: int = DEFAULT_WINDOW_MONTHS,
    timezone: str = REPORTING_TIMEZONE,
) -> StatementCoverageReport:
    """Project per-account month chips from Extraction periods already on Imports."""
    window = rolling_months(as_of, months)
    by_account: dict[UUID, list[tuple[date, date]]] = defaultdict(list)
    for period in periods:
        by_account[period.financial_account_id].append((period.period_start, period.period_end))
    return StatementCoverageReport(
        as_of=as_of,
        timezone=timezone,
        window_months=months,
        accounts=tuple(
            AccountStatementCoverage(
                financial_account_id=account_id,
                display_name=display_name,
                slug=slug,
                months=tuple(
                    AccountMonthCoverage(
                        month=month,
                        status=coverage_status(month, by_account[account_id]),
                    )
                    for month in window
                ),
            )
            for account_id, display_name, slug in accounts
        ),
    )


class StatementCoverageCatalog:
    """Owner projection of which calendar months lack an accepted Extraction."""

    def __init__(
        self,
        database: Database,
        *,
        reporting_timezone: str = REPORTING_TIMEZONE,
    ) -> None:
        self._database = database
        self._reporting_timezone = reporting_timezone

    def report(
        self,
        *,
        months: int = DEFAULT_WINDOW_MONTHS,
        as_of: date | None = None,
    ) -> StatementCoverageReport:
        _require_window(months)
        as_of_date = as_of if as_of is not None else reporting_today()
        with self._database.transaction() as session:
            return report_for_session(
                session,
                as_of=as_of_date,
                months=months,
                timezone=self._reporting_timezone,
            )


def report_for_session(
    session: Session,
    *,
    as_of: date,
    months: int = DEFAULT_WINDOW_MONTHS,
    timezone: str = REPORTING_TIMEZONE,
) -> StatementCoverageReport:
    _require_window(months)
    accounts = session.scalars(
        select(FinancialAccount)
        .where(FinancialAccount.kind == FinancialAccountKind.CREDIT_CARD)
        .order_by(FinancialAccount.created_at, FinancialAccount.slug, FinancialAccount.id)
    ).all()
    account_ids = [account.id for account in accounts]
    periods: list[ExtractionPeriod] = []
    if account_ids:
        extractions = session.scalars(
            select(Extraction).where(
                Extraction.status == "accepted",
                Extraction.financial_account_id.in_(account_ids),
                Extraction.period_start.is_not(None),
                Extraction.period_end.is_not(None),
            )
        ).all()
        for extraction in extractions:
            if (
                extraction.financial_account_id is None
                or extraction.period_start is None
                or extraction.period_end is None
            ):
                continue
            periods.append(
                ExtractionPeriod(
                    financial_account_id=extraction.financial_account_id,
                    period_start=extraction.period_start,
                    period_end=extraction.period_end,
                )
            )
    return coverage_for_accounts(
        tuple((account.id, account.display_name, account.slug) for account in accounts),
        periods,
        as_of=as_of,
        months=months,
        timezone=timezone,
    )


def _require_window(months: int) -> None:
    if not 1 <= months <= MAX_WINDOW_MONTHS:
        raise StatementCoverageError("window months must be between 1 and 24")


def _merge_days(intervals: Sequence[tuple[date, date]]) -> tuple[tuple[date, date], ...]:
    ordered = sorted(intervals)
    merged: list[tuple[date, date]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + timedelta(days=1):
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)
