from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from billzebub.claims import (
    ClaimBook,
    ClaimDisposition,
    ClaimDraft,
    ClaimType,
    InvalidClaimTransitionError,
)
from billzebub.money import Money
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    Claim,
    Extraction,
    FinancialAccount,
    SourceArtifact,
)


@pytest.fixture
def evidence_ids(database: Database) -> tuple[UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Card",
                default_currency="SGD",
            )
        )
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256="a" * 64,
                size=128,
                media_type="application/pdf",
                content_path="sha256/aa/" + "a" * 64,
                captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(
            Extraction(
                id=extraction_id,
                artifact_id=artifact_id,
                parser_version="synthetic-v1",
                status="accepted",
                accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    return account_id, artifact_id, extraction_id


@pytest.mark.integration
def test_claim_dispositions_are_append_only_conclusions(
    database: Database,
    evidence_ids: tuple[UUID, UUID, UUID],
) -> None:
    account_id, artifact_id, extraction_id = evidence_ids
    claims = ClaimBook(database)
    claim = claims.record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="SYNTHETIC COFFEE",
            authorized_amount=Money.parse("4.20", "SGD"),
            occurrence_at=datetime(2026, 1, 2, 16, 30, tzinfo=UTC),
        )
    )

    assert claims.current_disposition(claim.id) is ClaimDisposition.PROVISIONAL
    claims.mark_unconfirmed(claim.id, reason_code="confirmation_horizon_elapsed")
    assert claims.current_disposition(claim.id) is ClaimDisposition.UNCONFIRMED

    with pytest.raises(InvalidClaimTransitionError, match="Unconfirmed to Excluded"):
        claims.exclude(claim.id, reason_code="unsupported_source_event")

    assert claim.raw_description == "SYNTHETIC COFFEE"
    assert [event.disposition for event in claims.disposition_history(claim.id)] == [
        ClaimDisposition.PROVISIONAL,
        ClaimDisposition.UNCONFIRMED,
    ]

    with pytest.raises(IntegrityError, match="append-only"):
        with database.transaction() as session:
            session.execute(
                update(Claim)
                .where(Claim.id == claim.id)
                .values(raw_description="REWRITTEN EVIDENCE")
            )
    with pytest.raises(IntegrityError, match="append-only"):
        with database.transaction() as session:
            session.execute(delete(Claim).where(Claim.id == claim.id))
