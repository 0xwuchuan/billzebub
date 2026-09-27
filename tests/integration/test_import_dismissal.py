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
from billzebub.owner_workspace import OwnerWorkspace
from billzebub.persistence.database import Database
from billzebub.persistence.models import Extraction, PendingReview, SourceArtifact
from billzebub.reviews import (
    PendingReviewStatus,
    ReviewCondition,
    ReviewInbox,
    ReviewSeverity,
)


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


def _artifact_id(database: Database, extraction_id: UUID) -> UUID:
    with database.transaction() as session:
        extraction = session.get(Extraction, extraction_id)
        assert extraction is not None
        return extraction.artifact_id


def _pending_review(
    database: Database,
    *,
    subject_type: str,
    subject_id: UUID,
    condition_code: str,
    allowed: tuple[str, ...] = ("exclude_source_artifact",),
) -> UUID:
    review = ReviewInbox(database).synchronize(
        ReviewCondition(
            subject_type=subject_type,
            subject_id=subject_id,
            condition_code=condition_code,
            severity=ReviewSeverity.ATTENTION,
            allowed_decisions=allowed,
        ),
        active=True,
    )
    assert review is not None
    assert review.status is PendingReviewStatus.PENDING
    return review.id


def _listed_review_ids(
    database: Database,
    *,
    review_status: PendingReviewStatus = PendingReviewStatus.PENDING,
) -> set[UUID]:
    page = OwnerWorkspace(database).list_reviews(limit=100, review_status=review_status)
    return {item.id for item in page.items}


@pytest.mark.integration
def test_dismiss_failed_shortcut_extraction_cancels_its_pending_review(
    database: Database,
) -> None:
    failed_id = _add_extraction(
        database,
        status="failed",
        failure_code="invalid_payload_shape",
        adapter_key="apple_wallet_shortcut",
    )
    artifact_id = _artifact_id(database, failed_id)
    shortcut_review_id = _pending_review(
        database,
        subject_type="source_artifact",
        subject_id=artifact_id,
        condition_code="shortcut_payload_invalid",
    )
    extraction_review_id = _pending_review(
        database,
        subject_type="extraction",
        subject_id=failed_id,
        condition_code="statement_extraction:account_mismatch",
        allowed=("retry_after_adapter_update", "exclude_source_artifact"),
    )
    reprocess_review_id = _pending_review(
        database,
        subject_type="source_artifact",
        subject_id=artifact_id,
        condition_code=f"statement_reprocess:{uuid7()}",
        allowed=("approve_exact_diff", "keep_previous_extraction"),
    )
    other_review_id = _pending_review(
        database,
        subject_type="transaction",
        subject_id=uuid7(),
        condition_code="categorization_needed",
        allowed=("categorize",),
    )
    catalog = ImportCatalog(database)

    dismissed = catalog.dismiss(failed_id)
    listed = _listed_review_ids(database)
    cancelled = _listed_review_ids(database, review_status=PendingReviewStatus.CANCELLED)

    assert dismissed.dismissed_at is not None
    assert dismissed.active_review_id == reprocess_review_id
    assert shortcut_review_id not in listed
    assert extraction_review_id not in listed
    assert {shortcut_review_id, extraction_review_id} <= cancelled
    assert {reprocess_review_id, other_review_id} <= listed
    with database.transaction() as session:
        extraction = session.get(Extraction, failed_id)
        shortcut = session.get(PendingReview, shortcut_review_id)
        extraction_review = session.get(PendingReview, extraction_review_id)
        reprocess = session.get(PendingReview, reprocess_review_id)
        assert extraction is not None
        assert extraction.status == "failed"
        assert shortcut is not None
        assert shortcut.status == "cancelled"
        assert shortcut.version == 2
        assert extraction_review is not None
        assert extraction_review.status == "cancelled"
        assert reprocess is not None
        assert reprocess.status == "pending"
    assert [event.event_type for event in ReviewInbox(database).history(shortcut_review_id)] == [
        "created",
        "cancelled",
    ]
    catalog.dismiss(failed_id)
    assert _listed_review_ids(database) == {reprocess_review_id, other_review_id}


@pytest.mark.integration
def test_dismiss_failed_cancels_shortcut_reviews_and_leaves_other_work(
    database: Database,
) -> None:
    first = _add_extraction(
        database,
        status="failed",
        failure_code="invalid_json",
        adapter_key="paylah_shortcut",
    )
    second = _add_extraction(
        database,
        status="failed",
        failure_code="invalid_payload_values",
        adapter_key="apple_wallet_shortcut",
    )
    accepted = _add_extraction(database, status="accepted")
    first_review = _pending_review(
        database,
        subject_type="source_artifact",
        subject_id=_artifact_id(database, first),
        condition_code="shortcut_payload_invalid",
    )
    second_review = _pending_review(
        database,
        subject_type="source_artifact",
        subject_id=_artifact_id(database, second),
        condition_code="shortcut_payload_invalid",
    )
    other_review = _pending_review(
        database,
        subject_type="transaction",
        subject_id=uuid7(),
        condition_code="categorization_needed",
        allowed=("categorize",),
    )
    catalog = ImportCatalog(database)

    assert catalog.dismiss_failed() == 2
    assert catalog.dismiss_failed() == 0

    listed = _listed_review_ids(database)
    assert first_review not in listed
    assert second_review not in listed
    assert other_review in listed
    assert catalog.get(accepted).dismissed_at is None
    with database.transaction() as session:
        for review_id in (first_review, second_review):
            review = session.get(PendingReview, review_id)
            assert review is not None
            assert review.status == "cancelled"
        assert session.get(Extraction, first) is not None
        assert session.get(Extraction, second) is not None


@pytest.mark.integration
def test_pending_review_for_dismissed_extraction_stays_out_of_the_inbox(
    database: Database,
) -> None:
    dismissed_id = _add_extraction(
        database,
        status="failed",
        failure_code="invalid_payload_shape",
        adapter_key="apple_wallet_shortcut",
    )
    live_id = _add_extraction(
        database,
        status="failed",
        failure_code="invalid_json",
        adapter_key="paylah_shortcut",
    )
    dismissed_artifact = _artifact_id(database, dismissed_id)
    slipped_shortcut = _pending_review(
        database,
        subject_type="source_artifact",
        subject_id=dismissed_artifact,
        condition_code="shortcut_payload_invalid",
    )
    slipped_extraction = _pending_review(
        database,
        subject_type="extraction",
        subject_id=dismissed_id,
        condition_code="statement_extraction:adapter_failed",
        allowed=("exclude_source_artifact",),
    )
    reprocess_review = _pending_review(
        database,
        subject_type="source_artifact",
        subject_id=dismissed_artifact,
        condition_code=f"statement_reprocess:{uuid7()}",
        allowed=("approve_exact_diff", "keep_previous_extraction"),
    )
    live_review = _pending_review(
        database,
        subject_type="source_artifact",
        subject_id=_artifact_id(database, live_id),
        condition_code="shortcut_payload_invalid",
    )
    with database.transaction() as session:
        session.execute(
            update(Extraction)
            .where(Extraction.id == dismissed_id)
            .values(dismissed_at=datetime.now(UTC))
        )

    listed = _listed_review_ids(database)

    assert slipped_shortcut not in listed
    assert slipped_extraction not in listed
    assert {reprocess_review, live_review} <= listed
    with database.transaction() as session:
        shortcut = session.get(PendingReview, slipped_shortcut)
        assert shortcut is not None
        assert shortcut.status == "pending"


@pytest.mark.integration
def test_owner_http_dismiss_removes_shortcut_review_from_the_default_inbox(
    database: Database,
    tmp_path: Path,
) -> None:
    failed_id = _add_extraction(
        database,
        status="failed",
        failure_code="unsupported_source",
        adapter_key="apple_wallet_shortcut",
    )
    review_id = _pending_review(
        database,
        subject_type="source_artifact",
        subject_id=_artifact_id(database, failed_id),
        condition_code="shortcut_payload_invalid",
    )
    other_id = _pending_review(
        database,
        subject_type="transaction",
        subject_id=uuid7(),
        condition_code="categorization_needed",
        allowed=("categorize",),
    )
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
        before = client.get("/api/v1/reviews")
        dismissed = client.post(f"/api/v1/imports/{failed_id}/dismiss", headers=headers, json={})
        after = client.get("/api/v1/reviews")

    assert before.status_code == 200
    assert {item["id"] for item in before.json()["items"]} == {str(review_id), str(other_id)}
    assert dismissed.status_code == 200
    assert dismissed.json()["dismissed_at"] is not None
    assert dismissed.json()["active_review_id"] is None
    assert after.status_code == 200
    assert [item["id"] for item in after.json()["items"]] == [str(other_id)]
