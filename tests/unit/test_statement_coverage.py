from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from billzebub.api import create_app
from billzebub.config import Settings
from billzebub.imports import ImportNotFoundError, ImportRecord
from billzebub.statement_coverage import (
    AccountMonthCoverage,
    AccountStatementCoverage,
    CoverageStatus,
    ExtractionPeriod,
    StatementCoverageError,
    StatementCoverageReport,
    coverage_for_accounts,
    coverage_status,
    reporting_today,
    rolling_months,
)


class FakeDatabase:
    def ping(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeImportCatalog:
    def __init__(self, report: StatementCoverageReport) -> None:
        self.report = report
        self.months: list[int] = []

    def list(self) -> tuple[ImportRecord, ...]:
        return ()

    def get(self, extraction_id: UUID) -> ImportRecord:
        raise ImportNotFoundError(str(extraction_id))

    def coverage(
        self,
        *,
        months: int = 6,
        as_of: date | None = None,
    ) -> StatementCoverageReport:
        del as_of
        self.months.append(months)
        if not 1 <= months <= 24:
            raise StatementCoverageError("window months must be between 1 and 24")
        if months != 6:
            return StatementCoverageReport(
                as_of=self.report.as_of,
                timezone=self.report.timezone,
                window_months=months,
                accounts=self.report.accounts,
            )
        return self.report


def test_rolling_months_include_the_current_month_oldest_first() -> None:
    assert rolling_months(date(2026, 9, 15), 6) == (
        date(2026, 4, 1),
        date(2026, 5, 1),
        date(2026, 6, 1),
        date(2026, 7, 1),
        date(2026, 8, 1),
        date(2026, 9, 1),
    )
    assert rolling_months(date(2026, 1, 31), 3) == (
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
    )


def test_rolling_months_reject_windows_outside_one_to_twenty_four() -> None:
    with pytest.raises(StatementCoverageError, match="window months"):
        rolling_months(date(2026, 9, 15), 0)
    with pytest.raises(StatementCoverageError, match="window months"):
        rolling_months(date(2026, 9, 15), 25)


def test_coverage_status_uses_extraction_period_bounds_without_inventing_them() -> None:
    january = date(2026, 1, 1)
    assert (
        coverage_status(january, ((date(2026, 1, 1), date(2026, 1, 31)),)) is CoverageStatus.PRESENT
    )
    assert (
        coverage_status(january, ((date(2025, 12, 16), date(2026, 1, 15)),))
        is CoverageStatus.PARTIAL
    )
    assert (
        coverage_status(january, ((date(2026, 2, 1), date(2026, 2, 28)),)) is CoverageStatus.MISSING
    )
    assert (
        coverage_status(
            january,
            (
                (date(2025, 12, 16), date(2026, 1, 15)),
                (date(2026, 1, 16), date(2026, 2, 15)),
            ),
        )
        is CoverageStatus.PRESENT
    )
    assert (
        coverage_status(january, ((date(2026, 1, 31), date(2026, 1, 1)),)) is CoverageStatus.MISSING
    )


def test_coverage_for_accounts_ignores_unrelated_account_periods() -> None:
    card_id = uuid4()
    other_id = uuid4()
    report = coverage_for_accounts(
        ((card_id, "Synthetic Statement Card", "synthetic-card"),),
        (
            ExtractionPeriod(card_id, date(2026, 4, 1), date(2026, 4, 30)),
            ExtractionPeriod(other_id, date(2026, 5, 1), date(2026, 5, 31)),
        ),
        as_of=date(2026, 9, 15),
        months=6,
    )
    by_month = {month.month.isoformat()[:7]: month.status for month in report.accounts[0].months}
    assert report.timezone == "Asia/Singapore"
    assert report.window_months == 6
    assert report.as_of == date(2026, 9, 15)
    assert by_month == {
        "2026-04": CoverageStatus.PRESENT,
        "2026-05": CoverageStatus.MISSING,
        "2026-06": CoverageStatus.MISSING,
        "2026-07": CoverageStatus.MISSING,
        "2026-08": CoverageStatus.MISSING,
        "2026-09": CoverageStatus.MISSING,
    }


def test_reporting_today_uses_asia_singapore_calendar_date() -> None:
    utc_evening = datetime(2026, 9, 15, 16, 30, tzinfo=UTC)
    assert reporting_today(instant=utc_evening) == date(2026, 9, 16)
    singapore = datetime(2026, 9, 15, 23, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    assert reporting_today(instant=singapore) == date(2026, 9, 15)


def test_statement_coverage_resource_is_documented_and_fail_closed(tmp_path: Path) -> None:
    app = create_app(Settings(artifact_root=tmp_path), FakeDatabase())

    assert "/api/v1/statement-coverage" in app.openapi()["paths"]
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/v1/statement-coverage")

    assert response.status_code == 401
    assert response.json()["detail"] == "owner_identity_required"


def test_owner_statement_coverage_resource_projects_synthetic_periods(tmp_path: Path) -> None:
    account_id = uuid4()
    catalog = FakeImportCatalog(
        StatementCoverageReport(
            as_of=date(2026, 9, 15),
            timezone="Asia/Singapore",
            window_months=6,
            accounts=(
                AccountStatementCoverage(
                    financial_account_id=account_id,
                    display_name="Synthetic Statement Card",
                    slug="synthetic-card",
                    months=(
                        AccountMonthCoverage(date(2026, 4, 1), CoverageStatus.PRESENT),
                        AccountMonthCoverage(date(2026, 5, 1), CoverageStatus.MISSING),
                        AccountMonthCoverage(date(2026, 6, 1), CoverageStatus.PARTIAL),
                        AccountMonthCoverage(date(2026, 7, 1), CoverageStatus.MISSING),
                        AccountMonthCoverage(date(2026, 8, 1), CoverageStatus.MISSING),
                        AccountMonthCoverage(date(2026, 9, 1), CoverageStatus.MISSING),
                    ),
                ),
            ),
        )
    )
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="developer@example.test"),
        FakeDatabase(),
        import_catalog=catalog,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        listed = client.get("/api/v1/statement-coverage")
        invalid = client.get("/api/v1/statement-coverage", params={"months": 0})

    assert listed.status_code == 200
    assert listed.json() == {
        "as_of": "2026-09-15",
        "timezone": "Asia/Singapore",
        "window_months": 6,
        "accounts": [
            {
                "id": str(account_id),
                "display_name": "Synthetic Statement Card",
                "slug": "synthetic-card",
                "months": [
                    {"month": "2026-04", "status": "present"},
                    {"month": "2026-05", "status": "missing"},
                    {"month": "2026-06", "status": "partial"},
                    {"month": "2026-07", "status": "missing"},
                    {"month": "2026-08", "status": "missing"},
                    {"month": "2026-09", "status": "missing"},
                ],
            }
        ],
    }
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "statement_coverage_invalid"
    assert catalog.months == [6, 0]
