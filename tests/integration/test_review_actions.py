from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.apple_wallet import AppleWalletIngestion
from billzebub.artifact_capture import ArtifactArrivalInput, ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.claims import ClaimBook
from billzebub.config import Environment, Settings
from billzebub.financial_account_aliases import FinancialAccountAliases
from billzebub.identity import OwnerIdentity
from billzebub.owner_actors import OwnerActors
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    AuditActor,
    AuditActorKind,
    DurableJob,
    Extraction,
    FinancialAccount,
    PendingReview,
    ReviewEvent,
)
from billzebub.review_actions import (
    ReviewActionError,
    ReviewActions,
    ReviewConfigurationRequiredError,
)
from billzebub.reviews import (
    PendingReviewRecord,
    PendingReviewStatus,
    ReviewCondition,
    ReviewDecision,
    ReviewError,
    ReviewInbox,
    ReviewSeverity,
)
from billzebub.statement_extraction import (
    ExtractionOutcome,
    ExtractionStatus,
    SourceLocator,
    StatementAdapterRegistry,
    StatementCandidate,
    StatementExtraction,
    StatementRowCandidate,
)


class SyntheticStatementAdapter:
    key = "synthetic-credit"
    version = "1.0.0"
    institution = "synthetic-bank"

    def __init__(self, candidate: StatementCandidate) -> None:
        self.candidate = candidate

    def extract(
        self,
        path: Path,
        passwords: tuple[SecretStr, ...],
        expected_account_identifier: str | None = None,
    ) -> StatementCandidate:
        del passwords, expected_account_identifier
        assert path.is_file()
        return self.candidate


def valid_candidate() -> StatementCandidate:
    return StatementCandidate(
        statement_identity="synthetic-2026-01",
        account_identifier="SYNTHETIC-001",
        statement_date=date(2026, 1, 31),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        currency="SGD",
        opening_balance_text="100.00",
        closing_balance_text="105.00",
        candidate_row_count=2,
        rows=(
            StatementRowCandidate(
                raw_description="SYNTHETIC PURCHASE",
                posted_amount_text="-10.00",
                provider_transaction_date=date(2026, 1, 10),
                posting_date=date(2026, 1, 11),
                transaction_kind_hint="expense",
                locator=SourceLocator(page_number=1, line_number=20, text_start=0, text_end=36),
                original_amount_text="-9.00",
                original_currency="USD",
            ),
            StatementRowCandidate(
                raw_description="SYNTHETIC CARD PAYMENT",
                posted_amount_text="5.00",
                provider_transaction_date=date(2026, 1, 20),
                posting_date=date(2026, 1, 21),
                transaction_kind_hint="transfer",
                locator=SourceLocator(page_number=1, line_number=28, text_start=0, text_end=40),
            ),
        ),
    )


def _statement_source(
    database: Database, tmp_path: Path
) -> tuple[UUID, UUID, ContentAddressedStore]:
    account_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-review-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Review Card",
                default_currency="SGD",
                statement_adapter_key="synthetic-credit",
                statement_account_identifier="SYNTHETIC-001",
            )
        )
    store = ContentAddressedStore(tmp_path / "artifacts")
    artifact = ArtifactCapture(store, database).capture_bytes(
        b"%PDF-1.7\nsynthetic review statement\n%%EOF\n",
        ArtifactArrivalInput(
            source_type="statement_inbox",
            media_type="application/pdf",
            received_at=datetime(2026, 2, 1, tzinfo=UTC),
            original_name="statement.pdf",
        ),
    )
    return account_id, artifact.id, store


def _extraction(
    database: Database,
    store: ContentAddressedStore,
    tmp_path: Path,
    adapter: SyntheticStatementAdapter,
) -> StatementExtraction:
    return StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([adapter]),
        password_root=tmp_path / "passwords",
    )


def _actions(
    database: Database,
    store: ContentAddressedStore,
    tmp_path: Path,
    adapter: SyntheticStatementAdapter,
) -> ReviewActions:
    return ReviewActions(
        database,
        extraction=_extraction(database, store, tmp_path, adapter),
    )


def _review(database: Database, review_id: UUID) -> PendingReviewRecord:
    with database.transaction() as session:
        review = session.get(PendingReview, review_id)
        assert review is not None
        return ReviewInbox._record(review)


def _fail_extraction(
    database: Database,
    store: ContentAddressedStore,
    tmp_path: Path,
    account_id: UUID,
    artifact_id: UUID,
) -> ExtractionOutcome:
    outcome = _extraction(
        database,
        store,
        tmp_path,
        SyntheticStatementAdapter(replace(valid_candidate(), candidate_row_count=3)),
    ).extract(artifact_id=artifact_id, financial_account_id=account_id)
    assert outcome.status is ExtractionStatus.FAILED
    assert outcome.review_id is not None
    return outcome


def _reprocess_preview(
    database: Database,
    store: ContentAddressedStore,
    tmp_path: Path,
    account_id: UUID,
    artifact_id: UUID,
) -> tuple[ExtractionOutcome, SyntheticStatementAdapter]:
    first = _extraction(
        database, store, tmp_path, SyntheticStatementAdapter(valid_candidate())
    ).extract(artifact_id=artifact_id, financial_account_id=account_id)
    assert first.status is ExtractionStatus.ACCEPTED
    corrected_row = replace(
        valid_candidate().rows[0],
        raw_description="SYNTHETIC PURCHASE CORRECTED",
    )
    adapter = SyntheticStatementAdapter(
        replace(valid_candidate(), rows=(corrected_row, valid_candidate().rows[1]))
    )
    adapter.version = "2.0.0"
    preview = _extraction(database, store, tmp_path, adapter).extract(
        artifact_id=artifact_id,
        financial_account_id=account_id,
    )
    assert preview.status is ExtractionStatus.REPROCESS_REQUIRED
    assert preview.review_id is not None
    return preview, adapter


@pytest.mark.integration
def test_owner_review_action_resolves_agent_proposal_with_durable_actor(
    database: Database,
) -> None:
    review = ReviewInbox(database).synchronize(
        ReviewCondition(
            subject_type="transaction",
            subject_id=uuid7(),
            condition_code="agent_proposal:correction",
            severity=ReviewSeverity.ATTENTION,
            allowed_decisions=("accept", "reject"),
            context={"proposal_type": "correction", "summary": "Synthetic owner proposal"},
        ),
        active=True,
    )
    assert review is not None
    actor_id = OwnerActors(database).resolve(
        OwnerIdentity(login="owner@example.test", name="Synthetic Owner")
    )

    resolved = ReviewActions(database).decide(
        ReviewDecision(
            review_id=review.id,
            expected_version=review.version,
            choice="accept",
            actor_id=actor_id,
        )
    )

    assert resolved.status is PendingReviewStatus.RESOLVED
    assert resolved.version == 2
    with database.transaction() as session:
        actor = session.get(AuditActor, actor_id)
        event = session.scalar(
            select(ReviewEvent)
            .where(ReviewEvent.review_id == review.id, ReviewEvent.event_type == "resolved")
            .limit(1)
        )
        assert actor is not None
        assert actor.kind is AuditActorKind.OWNER
        assert event is not None
        assert event.actor_id == actor_id


@pytest.mark.integration
def test_generic_review_action_cannot_silently_clear_categorization(
    database: Database,
) -> None:
    review = ReviewInbox(database).synchronize(
        ReviewCondition(
            subject_type="transaction",
            subject_id=uuid7(),
            condition_code="categorization_needed",
            severity=ReviewSeverity.ATTENTION,
            allowed_decisions=("categorize",),
        ),
        active=True,
    )
    assert review is not None

    with pytest.raises(ReviewActionError, match="categorizing"):
        ReviewActions(database).decide(
            ReviewDecision(
                review_id=review.id,
                expected_version=review.version,
                choice="categorize",
            )
        )
    with database.transaction() as session:
        pending = session.get(PendingReview, review.id)
        assert pending is not None
        assert pending.status == "pending"


@pytest.mark.integration
def test_owner_http_decides_failed_extraction_review_without_400(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = _statement_source(database, tmp_path)
    outcome = _fail_extraction(database, store, tmp_path, account_id, artifact_id)
    assert outcome.review_id is not None
    app = create_app(
        Settings(
            environment=Environment.TEST,
            artifact_root=tmp_path / "http-artifacts",
            development_identity="owner@example.test",
        ),
        database,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        detail = client.get(f"/api/v1/reviews/{outcome.review_id}")
        decided = client.post(
            f"/api/v1/reviews/{outcome.review_id}/decisions",
            headers={
                "Origin": "http://testserver",
                "X-Billzebub-CSRF": "bzb-spa",
                "If-Match": detail.headers["etag"],
            },
            json={"choice": "exclude_source_artifact"},
        )

    assert detail.status_code == 200
    assert decided.status_code == 200
    assert decided.json()["status"] == "resolved"
    assert decided.json()["allowed_decisions"] == [
        "retry_after_adapter_update",
        "exclude_source_artifact",
    ]
    assert ClaimBook(database).for_extraction(outcome.extraction_id) == ()


@pytest.mark.integration
def test_extraction_review_rejects_unadvertised_decision(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = _statement_source(database, tmp_path)
    outcome = _fail_extraction(database, store, tmp_path, account_id, artifact_id)
    assert outcome.review_id is not None
    review = _review(database, outcome.review_id)

    with pytest.raises(ReviewError, match="not permitted"):
        ReviewActions(database).decide(
            ReviewDecision(
                review_id=review.id,
                expected_version=review.version,
                choice="accept",
            )
        )
    with database.transaction() as session:
        pending = session.get(PendingReview, review.id)
        assert pending is not None
        assert pending.status == "pending"


@pytest.mark.integration
def test_retry_after_adapter_update_accepts_only_after_version_change(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = _statement_source(database, tmp_path)
    outcome = _fail_extraction(database, store, tmp_path, account_id, artifact_id)
    assert outcome.review_id is not None
    review = _review(database, outcome.review_id)
    same_version = _actions(
        database,
        store,
        tmp_path,
        SyntheticStatementAdapter(replace(valid_candidate(), candidate_row_count=3)),
    )

    with pytest.raises(ReviewActionError, match="adapter version change"):
        same_version.decide(
            ReviewDecision(
                review_id=review.id,
                expected_version=review.version,
                choice="retry_after_adapter_update",
            )
        )
    with database.transaction() as session:
        pending = session.get(PendingReview, review.id)
        assert pending is not None
        assert pending.status == "pending"

    corrected = SyntheticStatementAdapter(valid_candidate())
    corrected.version = "1.0.1"
    retried = _actions(database, store, tmp_path, corrected).decide(
        ReviewDecision(
            review_id=review.id,
            expected_version=review.version,
            choice="retry_after_adapter_update",
        )
    )

    assert retried.status is PendingReviewStatus.RESOLVED
    assert ClaimBook(database).for_extraction(outcome.extraction_id) == ()
    with database.transaction() as session:
        accepted = session.scalar(
            select(Extraction).where(
                Extraction.artifact_id == artifact_id,
                Extraction.status == "accepted",
            )
        )
        job = session.scalar(
            select(DurableJob).where(DurableJob.kind == "reconcile_financial_account")
        )
        assert accepted is not None
        assert accepted.id != outcome.extraction_id
        assert job is not None
        assert job.payload == {"financial_account_id": str(account_id)}


@pytest.mark.integration
def test_reprocess_keep_previous_extraction_leaves_accepted_claims(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = _statement_source(database, tmp_path)
    preview, adapter = _reprocess_preview(database, store, tmp_path, account_id, artifact_id)
    assert preview.review_id is not None
    review = _review(database, preview.review_id)

    kept = _actions(database, store, tmp_path, adapter).decide(
        ReviewDecision(
            review_id=review.id,
            expected_version=review.version,
            choice="keep_previous_extraction",
        )
    )

    assert kept.status is PendingReviewStatus.RESOLVED
    assert len(ClaimBook(database).for_extraction(preview.extraction_id)) == 2
    with database.transaction() as session:
        accepted = session.scalars(select(Extraction).where(Extraction.status == "accepted")).all()
        jobs = session.scalars(select(DurableJob)).all()
        assert len(accepted) == 1
        assert jobs == []


@pytest.mark.integration
def test_reprocess_approve_exact_diff_accepts_the_previewed_candidate(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = _statement_source(database, tmp_path)
    preview, adapter = _reprocess_preview(database, store, tmp_path, account_id, artifact_id)
    assert preview.review_id is not None
    review = _review(database, preview.review_id)
    prior_id = preview.extraction_id

    approved = _actions(database, store, tmp_path, adapter).decide(
        ReviewDecision(
            review_id=review.id,
            expected_version=review.version,
            choice="approve_exact_diff",
        )
    )

    assert approved.status is PendingReviewStatus.CANCELLED
    assert len(ClaimBook(database).for_extraction(prior_id)) == 2
    with database.transaction() as session:
        newest = session.scalar(
            select(Extraction).where(
                Extraction.artifact_id == artifact_id,
                Extraction.status == "accepted",
                Extraction.id != prior_id,
            )
        )
        job = session.scalar(
            select(DurableJob).where(DurableJob.kind == "reconcile_financial_account")
        )
        assert newest is not None
        assert newest.supersedes_extraction_id == prior_id
        assert job is not None
        assert job.payload == {"financial_account_id": str(account_id)}
    assert len(ClaimBook(database).for_extraction(newest.id)) == 2


@pytest.mark.integration
def test_configure_card_alias_does_not_resolve_and_points_at_cli(
    database: Database,
    tmp_path: Path,
) -> None:
    ingestion = AppleWalletIngestion(
        database,
        ArtifactCapture(ContentAddressedStore(tmp_path / "wallet"), database),
        FinancialAccountAliases(database),
        timezone=ZoneInfo("Asia/Singapore"),
    )
    capture = ingestion.ingest(
        b'{"schema_version":"probe-2","name":"Synthetic name",'
        b'"merchant":"Synthetic merchant","card":"Unmapped Synthetic Wallet Card",'
        b'"amount":"$12.34","date":"7 Mar 2026 at 9:05 PM"}',
        received_at=datetime.now(UTC),
        actor_id=None,
    )
    assert capture.status.value == "review_required"
    with database.transaction() as session:
        stored = session.scalar(select(PendingReview))
        assert stored is not None
        review_id = stored.id
        version = stored.version

    with pytest.raises(ReviewConfigurationRequiredError) as raised:
        ReviewActions(database).decide(
            ReviewDecision(
                review_id=review_id,
                expected_version=version,
                choice="configure_card_alias",
            )
        )
    assert raised.value.next_step == "configure_via_setup"
    assert raised.value.command == "billzebub account apple-wallet-alias"
    assert raised.value.problem_code == "card_alias_configuration_required"
    assert raised.value.review.status is PendingReviewStatus.PENDING

    app = create_app(
        Settings(
            environment=Environment.TEST,
            artifact_root=tmp_path / "http-artifacts",
            development_identity="owner@example.test",
        ),
        database,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        detail = client.get(f"/api/v1/reviews/{review_id}")
        decided = client.post(
            f"/api/v1/reviews/{review_id}/decisions",
            headers={
                "Origin": "http://testserver",
                "X-Billzebub-CSRF": "bzb-spa",
                "If-Match": detail.headers["etag"],
            },
            json={"choice": "configure_card_alias"},
        )

    assert decided.status_code == 409
    assert decided.json() == {
        "type": "https://billzebub.local/problems/card_alias_configuration_required",
        "title": "Card alias configuration required",
        "status": 409,
        "detail": "card_alias_configuration_required",
        "next_step": "configure_via_setup",
        "command": "billzebub account apple-wallet-alias",
    }
    with database.transaction() as session:
        pending = session.get(PendingReview, review_id)
        assert pending is not None
        assert pending.status == "pending"
