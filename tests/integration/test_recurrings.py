from datetime import UTC, date, datetime
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
    RecurringSeries,
    TransactionVersion,
)
from billzebub.recurrings import (
    RecurringCreate,
    RecurringDetection,
    Recurrings,
    RecurringUpdate,
    advance_expected,
)


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


_SPOTIFY_LABELS = (
    "Spotify P45AE6BD59 Stockholm SE",
    "Spotify P449A6A149 Stockholm SE",
    "Spotify P7C3E91A4B Stockholm SE",
    "Spotify P8D12F6A03 Stockholm SE",
    "Spotify P2B90C4E17 Stockholm SE",
    "Spotify P6A18D3F52 Stockholm SE",
    "Spotify P9E4B70C21 Stockholm SE",
    "Spotify P3F81A2D64 Stockholm SE",
    "Spotify P5C27B9E08 Stockholm SE",
)
_SPOTIFY_DATES = (
    date(2025, 12, 15),
    date(2026, 1, 15),
    date(2026, 2, 15),
    date(2026, 3, 15),
    date(2026, 4, 15),
    date(2026, 5, 15),
    date(2026, 6, 15),
    date(2026, 7, 15),
    date(2026, 8, 15),
)


def _series_updated_at(database: Database, series_id: UUID) -> datetime:
    with database.transaction() as session:
        series = session.get(RecurringSeries, series_id)
        assert series is not None
        return series.updated_at


def _occurrence_series_id(database: Database, transaction_id: UUID) -> UUID | None:
    with database.transaction() as session:
        return session.scalar(
            select(RecurringOccurrence.series_id).where(
                RecurringOccurrence.transaction_id == transaction_id
            )
        )


@pytest.mark.integration
def test_detect_links_manual_series_to_historical_charges_with_opaque_refs(
    database: Database,
) -> None:
    recurrings = Recurrings(database)
    with database.transaction() as session:
        account_id = _account(session)
        charge_ids = [
            _spend(session, account_id, label, "-20.98", when)
            for label, when in zip(_SPOTIFY_LABELS, _SPOTIFY_DATES, strict=True)
        ]
        off_cadence_id = _spend(
            session,
            account_id,
            "Spotify P45AE6BD59 Stockholm SE",
            "-20.98",
            date(2026, 4, 2),
        )
        off_amount_id = _spend(
            session,
            account_id,
            "Spotify P449A6A149 Stockholm SE",
            "-40.00",
            date(2026, 3, 20),
        )

    created = recurrings.create_series(
        RecurringCreate(
            counterparty="Spotify Stockholm SE",
            amount=Decimal("20.98"),
            currency="SGD",
            cadence="monthly",
            next_expected_date=date(2025, 12, 15),
        )
    )
    assert created.status == "active"
    assert created.source == "manual"
    assert created.linked_count == 0

    detection = recurrings.detect(as_of=date(2026, 9, 1))
    series = recurrings.list_series()

    assert detection == RecurringDetection(proposed=0, updated=0, matched=9)
    assert len(series) == 1
    linked = series[0]
    assert linked.id == created.id
    assert linked.status == "active"
    assert linked.source == "manual"
    assert linked.linked_count == 9
    assert linked.last_matched_tx_id == charge_ids[-1]
    assert linked.next_expected_date == date(2026, 9, 15)
    assert linked.next_expected_date > _SPOTIFY_DATES[-1]
    assert _occurrence_series_id(database, off_cadence_id) is None
    assert _occurrence_series_id(database, off_amount_id) is None
    with database.transaction() as session:
        kinds = set(
            session.scalars(
                select(RecurringOccurrence.match_kind).where(
                    RecurringOccurrence.series_id == created.id
                )
            ).all()
        )
    assert kinds == {"auto"}

    stamped = _series_updated_at(database, created.id)
    again = recurrings.detect(as_of=date(2026, 9, 1))
    rerun = recurrings.list_series()[0]

    assert again == RecurringDetection(proposed=0, updated=0, matched=0)
    assert rerun.linked_count == 9
    assert rerun.last_matched_tx_id == charge_ids[-1]
    assert rerun.next_expected_date == date(2026, 9, 15)
    assert _series_updated_at(database, created.id) == stamped


@pytest.mark.integration
def test_detect_backfill_leaves_a_dismissed_series_untouched(database: Database) -> None:
    recurrings = Recurrings(database)
    with database.transaction() as session:
        account_id = _account(session)
        for label, when in zip(_SPOTIFY_LABELS, _SPOTIFY_DATES, strict=True):
            _spend(session, account_id, label, "-20.98", when)

    proposed_detection = recurrings.detect(as_of=date(2026, 9, 1))
    proposed = recurrings.list_series(status="proposed")
    assert proposed_detection.proposed == 1
    assert len(proposed) == 1
    dismissed = recurrings.dismiss_series(proposed[0].id)
    assert dismissed.status == "dismissed"
    assert dismissed.linked_count == 9
    stamped = _series_updated_at(database, dismissed.id)

    with database.transaction() as session:
        extra_id = _spend(
            session,
            account_id,
            "Spotify P1A2B3C4D5 Stockholm SE",
            "-20.98",
            date(2026, 9, 15),
        )

    again = recurrings.detect(as_of=date(2026, 9, 20))
    rows = recurrings.list_series()

    assert again == RecurringDetection(proposed=0, updated=0, matched=0)
    assert len(rows) == 1
    assert rows[0].id == dismissed.id
    assert rows[0].status == "dismissed"
    assert rows[0].linked_count == 9
    assert rows[0].next_expected_date == dismissed.next_expected_date
    assert rows[0].last_matched_tx_id == dismissed.last_matched_tx_id
    assert _series_updated_at(database, dismissed.id) == stamped
    assert _occurrence_series_id(database, extra_id) is None


@pytest.mark.integration
def test_detect_backfill_does_not_steal_a_linked_transaction(database: Database) -> None:
    recurrings = Recurrings(database)
    with database.transaction() as session:
        account_id = _account(session)
        charge_ids = [
            _spend(session, account_id, label, "-20.98", when)
            for label, when in zip(_SPOTIFY_LABELS, _SPOTIFY_DATES, strict=True)
        ]

    spotify = recurrings.create_series(
        RecurringCreate(
            counterparty="Spotify Stockholm SE",
            amount=Decimal("20.98"),
            currency="SGD",
            cadence="monthly",
            next_expected_date=date(2026, 9, 15),
        )
    )
    other = recurrings.create_series(
        RecurringCreate(
            counterparty="Other Service",
            amount=Decimal("10.00"),
            currency="SGD",
            cadence="monthly",
            next_expected_date=date(2026, 3, 15),
        )
    )
    stolen_id = charge_ids[3]
    claimed = recurrings.match_series(other.id, stolen_id)
    assert claimed.id == other.id
    assert claimed.linked_count == 1
    assert _occurrence_series_id(database, stolen_id) == other.id

    detection = recurrings.detect(as_of=date(2026, 9, 1))
    rows = {row.id: row for row in recurrings.list_series()}

    assert detection == RecurringDetection(proposed=0, updated=0, matched=8)
    assert set(rows) == {spotify.id, other.id}
    assert rows[spotify.id].linked_count == 8
    assert rows[spotify.id].last_matched_tx_id == charge_ids[-1]
    assert rows[spotify.id].next_expected_date == date(2026, 9, 15)
    assert _occurrence_series_id(database, stolen_id) == other.id
    assert rows[other.id].linked_count == 1
    assert rows[other.id].next_expected_date == date(2026, 8, 15)
    assert rows[other.id].missed is True
    for charge_id in charge_ids:
        if charge_id == stolen_id:
            continue
        assert _occurrence_series_id(database, charge_id) == spotify.id

    again = recurrings.detect(as_of=date(2026, 9, 1))
    assert again == RecurringDetection(proposed=0, updated=0, matched=0)
    assert recurrings.list_series()[0].linked_count + recurrings.list_series()[1].linked_count == 9


@pytest.mark.integration
def test_detect_recomputes_stale_next_expected_and_clears_missed_from_latest_link(
    database: Database,
) -> None:
    """A linked manual series keeps a stale schedule until detect recomputes it.

    Production matched nine Spotify charges and set last_matched_tx, then left
    next_expected_date at 2026-09-15 and missed true. History continues through
    the latest month, so the next date is one cadence after that charge and
    the series is not missed. A later detect that matches nothing must do the
    same recompute, and a third run changes nothing.
    """
    recurrings = Recurrings(database)
    latest = date(2026, 9, 15)
    as_of = date(2026, 10, 13)
    dates = (*_SPOTIFY_DATES, latest)
    labels = (*_SPOTIFY_LABELS, "Spotify P99AE6BD59 Stockholm SE")
    with database.transaction() as session:
        account_id = _account(session)
        charge_ids = [
            _spend(session, account_id, label, "-20.98", when)
            for label, when in zip(labels, dates, strict=True)
        ]
    created = recurrings.create_series(
        RecurringCreate(
            counterparty="Spotify Stockholm SE",
            amount=Decimal("20.98"),
            currency="SGD",
            cadence="monthly",
            next_expected_date=date(2026, 9, 15),
        )
    )
    with database.transaction() as session:
        series = session.get(RecurringSeries, created.id)
        assert series is not None
        series.missed = True

    detection = recurrings.detect(as_of=as_of)
    linked = recurrings.list_series()[0]
    expected_next = advance_expected(latest, "monthly", None)

    assert detection == RecurringDetection(proposed=0, updated=0, matched=len(dates))
    assert linked.id == created.id
    assert linked.linked_count == len(dates)
    assert linked.last_matched_tx_id == charge_ids[-1]
    assert linked.next_expected_date == expected_next
    assert linked.next_expected_date == date(2026, 10, 15)
    assert linked.missed is False

    with database.transaction() as session:
        stale = session.get(RecurringSeries, created.id)
        assert stale is not None
        stale.next_expected_date = date(2026, 9, 15)
        stale.missed = True

    repaired_detection = recurrings.detect(as_of=as_of)
    repaired = recurrings.list_series()[0]

    assert repaired_detection == RecurringDetection(proposed=0, updated=0, matched=0)
    assert repaired.linked_count == len(dates)
    assert repaired.last_matched_tx_id == charge_ids[-1]
    assert repaired.next_expected_date == expected_next
    assert repaired.missed is False

    stamped = _series_updated_at(database, created.id)
    repeat = recurrings.detect(as_of=as_of)
    unchanged = recurrings.list_series()[0]

    assert repeat == RecurringDetection(proposed=0, updated=0, matched=0)
    assert unchanged.next_expected_date == expected_next
    assert unchanged.missed is False
    assert unchanged.last_matched_tx_id == charge_ids[-1]
    assert _series_updated_at(database, created.id) == stamped


@pytest.mark.integration
def test_detect_fixes_already_linked_spotify_schedule_with_nothing_new_to_match(
    database: Database,
) -> None:
    """Nine Spotify charges are already linked and detect has nothing new to match.

    Production series 01a113e0 kept next_expected_date at 2026-09-15 and
    missed true after a detect that returned proposed=0 updated=0 matched=0.
    The latest charge is 2026-08-15, so one cadence later is 2026-09-15, and
    on 2026-10-14 that slot is overdue while October's match window is open.
    One detect must move the next date to 2026-10-15 and clear missed.
    """
    as_of = date(2026, 10, 14)
    recurrings = Recurrings(database)
    with database.transaction() as session:
        account_id = _account(session)
        charge_ids = [
            _spend(session, account_id, label, "-20.98", when)
            for label, when in zip(_SPOTIFY_LABELS, _SPOTIFY_DATES, strict=True)
        ]
    created = recurrings.create_series(
        RecurringCreate(
            counterparty="Spotify Stockholm SE",
            amount=Decimal("20.98"),
            currency="SGD",
            cadence="monthly",
            next_expected_date=date(2026, 9, 15),
        )
    )
    matched_at = datetime.now(UTC)
    with database.transaction() as session:
        series = session.get(RecurringSeries, created.id)
        assert series is not None
        series.missed = True
        series.last_matched_tx_id = charge_ids[-1]
        session.add_all(
            RecurringOccurrence(
                id=uuid7(),
                series_id=created.id,
                transaction_id=charge_id,
                matched_at=matched_at,
                match_kind="auto",
            )
            for charge_id in charge_ids
        )

    detection = recurrings.detect(as_of=as_of)
    linked = recurrings.list_series()[0]

    assert detection == RecurringDetection(proposed=0, updated=0, matched=0)
    assert linked.id == created.id
    assert linked.status == "active"
    assert linked.source == "manual"
    assert linked.linked_count == 9
    assert linked.last_matched_tx_id == charge_ids[-1]
    assert linked.next_expected_date == date(2026, 10, 15)
    assert linked.missed is False

    stamped = _series_updated_at(database, created.id)
    repeat = recurrings.detect(as_of=as_of)
    unchanged = recurrings.list_series()[0]

    assert repeat == RecurringDetection(proposed=0, updated=0, matched=0)
    assert unchanged.next_expected_date == date(2026, 10, 15)
    assert unchanged.missed is False
    assert unchanged.last_matched_tx_id == charge_ids[-1]
    assert unchanged.linked_count == 9
    assert _series_updated_at(database, created.id) == stamped
