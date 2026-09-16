from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from uuid6 import uuid7

from billzebub.imports import ImportCatalog
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    ArtifactArrival,
    Claim,
    Extraction,
    FinancialAccount,
    InboxFileObservation,
    PendingReview,
    SourceArtifact,
)
from billzebub.reviews import ReviewCondition, ReviewInbox, ReviewSeverity


def _digest() -> str:
    return (uuid7().hex + uuid7().hex)[:64]


def _add_account(database: Database) -> UUID:
    account_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug=f"synthetic-purge-{account_id.hex[:8]}",
                display_name="Synthetic Purge Card",
                institution="synthetic",
                kind="credit_card",
                default_currency="SGD",
            )
        )
    return account_id


def _add_artifact_and_extraction(
    database: Database,
    *,
    status: str,
    failure_code: str | None,
    adapter_key: str | None,
    claim_count: int = 0,
    with_review: bool = False,
) -> tuple[UUID, UUID]:
    artifact_id = uuid7()
    extraction_id = uuid7()
    digest = _digest()
    with database.transaction() as session:
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256=digest,
                size=32,
                media_type="application/json",
                content_path=f"sha256/{digest[:2]}/{digest}",
                captured_at=datetime(2026, 3, 7, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(
            ArtifactArrival(
                artifact_id=artifact_id,
                source_type="apple_wallet_shortcut",
                original_name=None,
                received_at=datetime(2026, 3, 7, tzinfo=UTC),
            )
        )
        session.add(
            Extraction(
                id=extraction_id,
                artifact_id=artifact_id,
                adapter_key=adapter_key,
                parser_version="2",
                status=status,
                claim_count=claim_count,
                failure_code=failure_code,
                accepted_at=None if status == "failed" else datetime(2026, 3, 7, tzinfo=UTC),
            )
        )
        session.flush()
        if with_review:
            ReviewInbox.synchronize_in_session(
                session,
                ReviewCondition(
                    subject_type="source_artifact",
                    subject_id=artifact_id,
                    condition_code="shortcut_payload_invalid",
                    severity=ReviewSeverity.ATTENTION,
                    allowed_decisions=("exclude_source_artifact",),
                    context={"failure_code": failure_code or "invalid_payload_shape"},
                ),
                active=True,
            )
    return extraction_id, artifact_id


@pytest.mark.integration
def test_purge_failed_dry_run_does_not_delete_junk_rows(database: Database) -> None:
    junk_id, artifact_id = _add_artifact_and_extraction(
        database,
        status="failed",
        failure_code="invalid_payload_shape",
        adapter_key="apple_wallet_shortcut",
        with_review=True,
    )
    statement_id, _ = _add_artifact_and_extraction(
        database,
        status="failed",
        failure_code="account_mismatch",
        adapter_key="synthetic-credit",
    )
    catalog = ImportCatalog(database)

    report = catalog.purge_failed(dry_run=True)

    assert report.dry_run is True
    assert report.extraction_ids == (junk_id,)
    assert report.artifact_ids == (artifact_id,)
    assert statement_id not in report.extraction_ids
    with database.transaction() as session:
        assert session.get(Extraction, junk_id) is not None
        assert session.get(SourceArtifact, artifact_id) is not None
        assert session.get(Extraction, statement_id) is not None
        assert session.scalar(select(func.count()).select_from(PendingReview)) == 1


@pytest.mark.integration
def test_purge_failed_deletes_junk_and_orphan_artifacts(database: Database) -> None:
    junk_id, artifact_id = _add_artifact_and_extraction(
        database,
        status="failed",
        failure_code="unsupported_source",
        adapter_key="apple_wallet_shortcut",
        with_review=True,
    )
    unmapped_id, unmapped_artifact = _add_artifact_and_extraction(
        database,
        status="failed",
        failure_code="unmapped_card",
        adapter_key="apple_wallet_shortcut",
        with_review=True,
    )
    statement_id, statement_artifact = _add_artifact_and_extraction(
        database,
        status="failed",
        failure_code="account_mismatch",
        adapter_key="synthetic-credit",
    )
    accepted_id, accepted_artifact = _add_artifact_and_extraction(
        database,
        status="accepted",
        failure_code=None,
        adapter_key="apple_wallet_shortcut",
    )
    catalog = ImportCatalog(database)

    report = catalog.purge_failed(dry_run=False)

    assert report.dry_run is False
    assert set(report.extraction_ids) == {junk_id, unmapped_id}
    assert set(report.artifact_ids) == {artifact_id, unmapped_artifact}
    with database.transaction() as session:
        assert session.get(Extraction, junk_id) is None
        assert session.get(Extraction, unmapped_id) is None
        assert session.get(SourceArtifact, artifact_id) is None
        assert session.get(SourceArtifact, unmapped_artifact) is None
        assert session.get(Extraction, statement_id) is not None
        assert session.get(SourceArtifact, statement_artifact) is not None
        assert session.get(Extraction, accepted_id) is not None
        assert session.get(SourceArtifact, accepted_artifact) is not None
        assert session.scalar(select(func.count()).select_from(PendingReview)) == 0
        assert session.scalar(select(func.count()).select_from(ArtifactArrival)) == 2


@pytest.mark.integration
def test_purge_failed_refuses_rows_with_claims_and_keeps_inbox_artifacts(
    database: Database,
) -> None:
    account_id = _add_account(database)
    claimed_id, claimed_artifact = _add_artifact_and_extraction(
        database,
        status="failed",
        failure_code="invalid_payload_shape",
        adapter_key="apple_wallet_shortcut",
        claim_count=1,
    )
    inbox_id, inbox_artifact = _add_artifact_and_extraction(
        database,
        status="failed",
        failure_code="invalid_json",
        adapter_key="apple_wallet_shortcut",
    )
    with database.transaction() as session:
        session.add(
            Claim(
                financial_account_id=account_id,
                source_artifact_id=claimed_artifact,
                extraction_id=claimed_id,
                claim_type="real_time",
                raw_description="synthetic claimed junk",
                authorized_amount=Decimal("1.00"),
                authorized_currency="SGD",
                occurrence_at=datetime(2026, 3, 7, tzinfo=UTC),
            )
        )
        session.add(
            InboxFileObservation(
                financial_account_id=account_id,
                file_name="synthetic.pdf",
                size=32,
                modified_ns=1,
                first_observed_at=datetime(2026, 3, 7, tzinfo=UTC),
                last_observed_at=datetime(2026, 3, 7, tzinfo=UTC),
                status="captured",
                artifact_id=inbox_artifact,
            )
        )

    report = ImportCatalog(database).purge_failed(dry_run=False, all_failed=True)

    assert claimed_id in report.skipped_extraction_ids
    assert claimed_id not in report.extraction_ids
    assert inbox_id in report.extraction_ids
    assert inbox_artifact not in report.artifact_ids
    with database.transaction() as session:
        assert session.get(Extraction, claimed_id) is not None
        assert session.scalar(select(func.count()).select_from(Claim)) == 1
        assert session.get(Extraction, inbox_id) is None
        assert session.get(SourceArtifact, inbox_artifact) is not None
        assert session.get(SourceArtifact, claimed_artifact) is not None
