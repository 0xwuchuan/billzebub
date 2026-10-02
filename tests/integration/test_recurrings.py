from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.config import Environment, Settings
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    FinancialAccount,
    FinancialTransaction,
    RecurringOccurrence,
    TransactionVersion,
)
from billzebub.recurrings import Recurrings, RecurringUpdate


def _account(session: Session) -> UUID:
    account_id = uuid7()
    session.add(
        FinancialAccount(
            id=account_id,
            slug=f"synthetic-{account_id.hex[:12]}",
            display_name="Synthetic Card",
            institution="synthetic-bank",
            kind="credit_card",
            default_currency="SGD",
        )
    )
    session.flush()
    return account_id


def _spend(
    session: Session,
    account_id: UUID,
    counterparty: str,
    amount: str,
    when: date,
    *,
    kind: str = "expense",
) -> UUID:
    transaction_id = uuid7()
    session.add(
        FinancialTransaction(
            id=transaction_id,
            financial_account_id=account_id,
            current_version=1,
        )
    )
    session.flush()
    session.add(
        TransactionVersion(
            id=uuid7(),
            transaction_id=transaction_id,
            version=1,
            kind=kind,
            posted_amount=Decimal(amount),
            posted_currency="SGD",
            effective_date=when,
            posting_date=when,
            counterparty=counterparty,
        )
    )
    return transaction_id


def _mutation_headers() -> dict[str, str]:
    return {"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"}


@pytest.mark.integration
def test_detector_proposes_a_multi_hit_merchant_and_leaves_it_inactive(
    database: Database,
) -> None:
    with database.transaction() as session:
        account_id = _account(session)
        for when in (date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)):
            _spend(session, account_id, "NETFLIX.COM", "-15.98", when)
        _spend(session, account_id, "SYNTHETIC COFFEE", "-4.50", date(2026, 2, 2))
        for when in (date(2026, 1, 3), date(2026, 2, 3), date(2026, 3, 3)):
            _spend(session, account_id, "SALARY", "5000.00", when, kind="income")

    detection = Recurrings(database).detect(as_of=date(2026, 3, 20))
    series = Recurrings(database).list_series()

    assert detection.proposed == 1
    assert len(series) == 1
    proposed = series[0]
    assert proposed.status == "proposed"
    assert proposed.source == "detected"
    assert proposed.counterparty == "NETFLIX.COM"
    assert proposed.cadence == "monthly"
    assert proposed.amount.amount == Decimal("15.98")
    assert proposed.amount.currency == "SGD"
    assert proposed.next_expected_date == date(2026, 4, 5)
    assert proposed.linked_count == 3
    assert proposed.last_amount.amount == Decimal("15.98")
    assert not proposed.missed


@pytest.mark.integration
def test_amounts_inside_tolerance_persist_as_one_proposed_range(database: Database) -> None:
    with database.transaction() as session:
        account_id = _account(session)
        _spend(session, account_id, "NETFLIX.COM", "-15.98", date(2026, 1, 5))
        _spend(session, account_id, "NETFLIX.COM", "-16.40", date(2026, 2, 5))
        _spend(session, account_id, "NETFLIX.COM", "-15.98", date(2026, 3, 5))

    assert Recurrings(database).detect(as_of=date(2026, 3, 20)).proposed == 1
    series = Recurrings(database).list_series()[0]
    assert series.amount_min is not None
    assert series.amount_max is not None
    assert series.amount_min.amount == Decimal("15.98")
    assert series.amount_max.amount == Decimal("16.40")
    assert series.amount_min.amount <= series.amount.amount
    assert series.amount.amount <= series.amount_max.amount


@pytest.mark.integration
def test_dismissed_cluster_is_not_proposed_again(database: Database) -> None:
    recurrings = Recurrings(database)
    with database.transaction() as session:
        account_id = _account(session)
        for when in (date(2026, 1, 8), date(2026, 2, 8), date(2026, 3, 8)):
            _spend(session, account_id, "GRAB RIDE", "-18.00", when)

    recurrings.detect(as_of=date(2026, 3, 20))
    proposed = recurrings.list_series(status="proposed")
    assert len(proposed) == 1
    dismissed = recurrings.dismiss_series(proposed[0].id)
    assert dismissed.status == "dismissed"

    with database.transaction() as session:
        _spend(session, account_id, "grab ride", "-18.20", date(2026, 4, 8))

    again = recurrings.detect(as_of=date(2026, 4, 20))
    rows = recurrings.list_series()

    assert again.proposed == 0
    assert [(row.id, row.status, row.cluster_key) for row in rows] == [
        (dismissed.id, "dismissed", dismissed.cluster_key)
    ]


@pytest.mark.integration
def test_new_settled_transaction_auto_links_and_advances_next_expected(
    database: Database,
) -> None:
    recurrings = Recurrings(database)
    with database.transaction() as session:
        account_id = _account(session)
        for when in (date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)):
            _spend(session, account_id, "NETFLIX.COM", "-15.98", when)

    recurrings.detect(as_of=date(2026, 3, 20))
    proposed = recurrings.list_series(status="proposed")[0]
    active = recurrings.update_series(
        proposed.id,
        RecurringUpdate(set_fields=frozenset({"status"}), status="active"),
    )
    assert active.next_expected_date == date(2026, 4, 5)
    recurrings.detect(as_of=date(2026, 4, 20))
    assert recurrings.list_series()[0].missed is True

    with database.transaction() as session:
        renewal_id = _spend(session, account_id, "NETFLIX.COM", "-15.98", date(2026, 4, 6))

    matched = recurrings.match_transaction(renewal_id, as_of=date(2026, 4, 10))
    assert matched is not None
    assert matched.id == active.id
    assert matched.next_expected_date == date(2026, 5, 6)
    assert matched.linked_count == 4
    assert matched.missed is False
    assert matched.last_matched_tx_id == renewal_id

    with database.transaction() as session:
        match_kind = session.scalar(
            select(RecurringOccurrence.match_kind).where(
                RecurringOccurrence.transaction_id == renewal_id
            )
        )
    assert match_kind == "auto"

    recurrings.update_series(
        active.id,
        RecurringUpdate(set_fields=frozenset({"status"}), status="paused"),
    )
    with database.transaction() as session:
        extra_id = _spend(session, account_id, "NETFLIX.COM", "-15.98", date(2026, 5, 6))
    assert recurrings.match_transaction(extra_id, as_of=date(2026, 5, 6)) is None


@pytest.mark.integration
def test_summary_endpoint_returns_this_month_total_and_upcoming(
    database: Database,
    tmp_path: Path,
) -> None:
    recurrings = Recurrings(database)
    with database.transaction() as session:
        account_id = _account(session)
        for when in (date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)):
            _spend(session, account_id, "NETFLIX.COM", "-15.98", when)

    assert recurrings.detect(as_of=date(2026, 3, 20)).proposed == 1
    series_id = recurrings.list_series(status="proposed")[0].id
    app = create_app(
        Settings(
            environment=Environment.TEST,
            artifact_root=tmp_path,
            development_identity="developer@example.test",
        ),
        database,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        inbox = client.get("/api/v1/recurrings/proposed")
        assert inbox.status_code == 200
        assert [item["id"] for item in inbox.json()["items"]] == [str(series_id)]
        assert inbox.json()["items"][0]["status"] == "proposed"

        activated = client.patch(
            f"/api/v1/recurrings/{series_id}",
            headers=_mutation_headers(),
            json={"status": "active"},
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "active"

        with database.transaction() as session:
            renewal_id = _spend(session, account_id, "NETFLIX.COM", "-15.98", date(2026, 4, 6))
        matched = recurrings.match_transaction(renewal_id, as_of=date(2026, 4, 10))
        assert matched is not None

        summary = client.get("/api/v1/recurrings/summary", params={"as_of": "2026-04-10"})
        listed = client.get("/api/v1/recurrings", params={"status": "active"})
        blocked = client.post(
            "/api/v1/recurrings",
            json={
                "counterparty": "Landlord",
                "amount": "2500.00",
                "currency": "SGD",
                "cadence": "monthly",
                "next_expected_date": "2026-05-01",
            },
        )

        assert summary.status_code == 200
        body = summary.json()
        assert body["month"] == "2026-04"
        assert body["total"] == {"amount": "15.98", "currency": "SGD"}
        assert len(body["upcoming"]) == 1
        assert body["upcoming"][0]["id"] == str(series_id)
        assert body["upcoming"][0]["next_expected_date"] == "2026-05-06"
        assert listed.status_code == 200
        assert listed.json()["items"][0]["linked_count"] == 4
        assert blocked.status_code == 403

        created = client.post(
            "/api/v1/recurrings",
            headers=_mutation_headers(),
            json={
                "counterparty": "Landlord",
                "amount": "2500.00",
                "currency": "SGD",
                "cadence": "monthly",
                "next_expected_date": "2026-05-01",
                "notes": "Rent",
            },
        )
        assert created.status_code == 201
        created_body = created.json()
        assert created_body["status"] == "active"
        assert created_body["source"] == "manual"
        assert created_body["amount"] == {"amount": "2500.00", "currency": "SGD"}

        ended = client.patch(
            f"/api/v1/recurrings/{created_body['id']}",
            headers=_mutation_headers(),
            json={"status": "ended"},
        )
        assert ended.status_code == 200
        assert ended.json()["status"] == "ended"
