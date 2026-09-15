from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.config import Settings
from billzebub.imports import ImportCatalog
from billzebub.persistence.database import Database
from billzebub.persistence.models import Extraction, FinancialAccount, SourceArtifact
from billzebub.statement_coverage import CoverageStatus, StatementCoverageCatalog


def _add_account(
    database: Database,
    *,
    slug: str,
    display_name: str,
    kind: str = "credit_card",
) -> UUID:
    account_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug=slug,
                display_name=display_name,
                institution="synthetic",
                kind=kind,
                default_currency="SGD",
                statement_adapter_key="synthetic-credit" if kind == "credit_card" else None,
            )
        )
    return account_id


def _add_extraction(
    database: Database,
    *,
    account_id: UUID | None,
    status: str,
    period_start: date | None,
    period_end: date | None,
    failure_code: str | None = None,
) -> None:
    artifact_id = uuid7()
    digest = uuid7().hex + uuid7().hex
    digest = digest[:64]
    with database.transaction() as session:
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256=digest,
                size=32,
                media_type="application/pdf",
                content_path=f"sha256/{digest[:2]}/{digest}",
                captured_at=datetime(2026, 4, 1, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(
            Extraction(
                id=uuid7(),
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key="synthetic-credit",
                parser_version="v1",
                status=status,
                period_start=period_start,
                period_end=period_end,
                claim_count=0 if status == "failed" else 1,
                failure_code=failure_code,
                accepted_at=None if status == "failed" else datetime(2026, 4, 2, tzinfo=UTC),
            )
        )


@pytest.mark.integration
def test_statement_coverage_uses_accepted_extraction_periods(
    database: Database,
) -> None:
    card_id = _add_account(
        database, slug="synthetic-coverage-card", display_name="Synthetic Coverage Card"
    )
    missing_id = _add_account(
        database, slug="synthetic-empty-card", display_name="Synthetic Empty Card"
    )
    paylah_id = _add_account(
        database,
        slug="synthetic-paylah",
        display_name="Synthetic PayLah",
        kind="paylah",
    )
    _add_extraction(
        database,
        account_id=card_id,
        status="accepted",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    _add_extraction(
        database,
        account_id=card_id,
        status="accepted",
        period_start=date(2026, 5, 16),
        period_end=date(2026, 6, 15),
    )
    _add_extraction(
        database,
        account_id=card_id,
        status="failed",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        failure_code="account_mismatch",
    )
    _add_extraction(
        database,
        account_id=card_id,
        status="accepted",
        period_start=None,
        period_end=None,
    )
    _add_extraction(
        database,
        account_id=paylah_id,
        status="accepted",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 31),
    )
    report = StatementCoverageCatalog(database).report(as_of=date(2026, 9, 15), months=6)
    by_account = {account.financial_account_id: account for account in report.accounts}

    assert [account.slug for account in report.accounts] == [
        "synthetic-coverage-card",
        "synthetic-empty-card",
    ]
    assert paylah_id not in by_account
    assert missing_id in by_account
    card_months = {
        month.month.isoformat()[:7]: month.status for month in by_account[card_id].months
    }
    empty_months = {
        month.month.isoformat()[:7]: month.status for month in by_account[missing_id].months
    }
    assert card_months == {
        "2026-04": CoverageStatus.PRESENT,
        "2026-05": CoverageStatus.PARTIAL,
        "2026-06": CoverageStatus.PARTIAL,
        "2026-07": CoverageStatus.MISSING,
        "2026-08": CoverageStatus.MISSING,
        "2026-09": CoverageStatus.MISSING,
    }
    assert set(empty_months.values()) == {CoverageStatus.MISSING}


@pytest.mark.integration
def test_owner_http_lists_statement_coverage_from_imports(
    database: Database,
    tmp_path: Path,
) -> None:
    card_id = _add_account(database, slug="synthetic-http-card", display_name="Synthetic HTTP Card")
    _add_extraction(
        database,
        account_id=card_id,
        status="accepted",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    catalog = ImportCatalog(database)
    report = catalog.coverage(as_of=date(2026, 9, 15), months=6)
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        listed = client.get("/api/v1/statement-coverage", params={"months": 6})

    assert report.accounts[0].financial_account_id == card_id
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["timezone"] == "Asia/Singapore"
    assert payload["window_months"] == 6
    assert payload["accounts"][0]["display_name"] == "Synthetic HTTP Card"
    assert len(payload["accounts"][0]["months"]) == 6
    assert {month["status"] for month in payload["accounts"][0]["months"]} <= {
        "present",
        "missing",
        "partial",
    }
