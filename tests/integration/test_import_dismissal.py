from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.config import Environment, Settings
from billzebub.imports import ImportCatalog, ImportNotDismissableError
from billzebub.persistence.database import Database
from billzebub.persistence.models import Extraction, SourceArtifact


def _add_invalid_dismissed_accepted(database: Database) -> None:
    artifact_id = uuid7()
    digest = (uuid7().hex + uuid7().hex)[:64]
    with database.transaction() as session:
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256=digest,
                size=8,
                media_type="application/pdf",
                content_path=f"sha256/{digest[:2]}/{digest}",
                captured_at=datetime(2026, 4, 1, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(
            Extraction(
                artifact_id=artifact_id,
                parser_version="v1",
                status="accepted",
                claim_count=0,
                accepted_at=datetime(2026, 4, 2, tzinfo=UTC),
                dismissed_at=datetime.now(UTC),
            )
        )


def _add_extraction(
    database: Database,
    *,
    status: str,
    failure_code: str | None = None,
    adapter_key: str = "synthetic-credit",
    claim_count: int = 0,
) -> UUID:
    artifact_id = uuid7()
    extraction_id = uuid7()
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
                id=extraction_id,
                artifact_id=artifact_id,
                adapter_key=adapter_key,
                parser_version="v1",
                status=status,
                period_start=date(2026, 4, 1) if status == "accepted" else None,
                period_end=date(2026, 4, 30) if status == "accepted" else None,
                claim_count=claim_count,
                failure_code=failure_code,
                accepted_at=None if status == "failed" else datetime(2026, 4, 2, tzinfo=UTC),
            )
        )
    return extraction_id


@pytest.mark.integration
def test_dismiss_one_failed_extraction_and_default_list_hides_it(database: Database) -> None:
    failed_id = _add_extraction(database, status="failed", failure_code="account_mismatch")
    accepted_id = _add_extraction(database, status="accepted")
    catalog = ImportCatalog(database)

    dismissed = catalog.dismiss(failed_id)
    listed = catalog.list()
    included = catalog.list(include_dismissed=True)

    assert dismissed.status == "failed"
    assert dismissed.dismissed_at is not None
    assert dismissed.failure_code == "account_mismatch"
    assert [item.id for item in listed] == [accepted_id]
    assert {item.id for item in included} == {failed_id, accepted_id}
    assert catalog.get(failed_id).dismissed_at is not None


@pytest.mark.integration
def test_dismiss_all_failed_is_idempotent_and_skips_accepted(database: Database) -> None:
    first = _add_extraction(database, status="failed", failure_code="invalid_json")
    second = _add_extraction(database, status="failed", failure_code="unmapped_card")
    accepted = _add_extraction(database, status="accepted")
    catalog = ImportCatalog(database)

    assert catalog.dismiss_failed() == 2
    assert catalog.dismiss_failed() == 0
    listed = catalog.list()
    included = catalog.list(include_dismissed=True)

    assert [item.id for item in listed] == [accepted]
    assert catalog.get(first).dismissed_at is not None
    assert catalog.get(second).dismissed_at is not None
    assert catalog.get(accepted).dismissed_at is None
    assert len(included) == 3


@pytest.mark.integration
def test_only_failed_extractions_may_be_dismissed(database: Database) -> None:
    accepted = _add_extraction(database, status="accepted")
    catalog = ImportCatalog(database)

    with pytest.raises(ImportNotDismissableError):
        catalog.dismiss(accepted)
    assert catalog.get(accepted).dismissed_at is None


@pytest.mark.integration
def test_dismissed_at_constraint_and_append_only_guard(database: Database) -> None:
    accepted = _add_extraction(database, status="accepted")
    failed = _add_extraction(database, status="failed", failure_code="invalid_payload_shape")

    with pytest.raises(IntegrityError, match="dismissed_at_failed_only|append-only"):
        with database.transaction() as session:
            session.execute(
                update(Extraction)
                .where(Extraction.id == accepted)
                .values(dismissed_at=datetime.now(UTC))
            )
    with pytest.raises(IntegrityError, match="append-only"):
        with database.transaction() as session:
            session.execute(
                update(Extraction).where(Extraction.id == failed).values(parser_version="v2")
            )
    with pytest.raises(IntegrityError, match="append-only"):
        with database.transaction() as session:
            session.execute(text("DELETE FROM extraction WHERE id = :id"), {"id": failed})

    ImportCatalog(database).dismiss(failed)
    with pytest.raises(IntegrityError, match="dismissed_at_failed_only"):
        _add_invalid_dismissed_accepted(database)
    with database.transaction() as session:
        extraction = session.get(Extraction, failed)
        assert extraction is not None
        assert extraction.status == "failed"
        assert extraction.dismissed_at is not None


@pytest.mark.integration
def test_owner_http_dismisses_failed_imports_and_hides_them(
    database: Database,
    tmp_path: Path,
) -> None:
    failed_id = _add_extraction(
        database,
        status="failed",
        failure_code="unsupported_source",
        adapter_key="apple_wallet_shortcut",
    )
    accepted_id = _add_extraction(database, status="accepted")
    app = create_app(
        Settings(
            environment=Environment.TEST,
            artifact_root=tmp_path / "artifacts",
            development_identity="developer@example.test",
        ),
        database,
    )
    headers = {"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"}
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        before = client.get("/api/v1/imports")
        dismissed = client.post(f"/api/v1/imports/{failed_id}/dismiss", headers=headers, json={})
        after = client.get("/api/v1/imports")
        included = client.get("/api/v1/imports", params={"include_dismissed": True})
        blocked_accepted = client.post(
            f"/api/v1/imports/{accepted_id}/dismiss",
            headers=headers,
            json={},
        )
        bulk = client.post("/api/v1/imports/dismiss-failed", headers=headers, json={})

    assert before.status_code == 200
    assert len(before.json()["items"]) == 2
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "failed"
    assert dismissed.json()["dismissed_at"] is not None
    assert len(after.json()["items"]) == 1
    assert after.json()["items"][0]["status"] == "accepted"
    assert len(included.json()["items"]) == 2
    assert blocked_accepted.status_code == 409
    assert bulk.status_code == 200
    assert bulk.json() == {"dismissed_count": 0}
