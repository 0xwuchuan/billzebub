from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from uuid6 import uuid7

from billzebub.artifact_capture import ArtifactArrivalInput, ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.claims import ClaimBook
from billzebub.jobs import JobQueue
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    DurableJob,
    Extraction,
    FinancialAccount,
    PendingReview,
    ReviewEvent,
)
from billzebub.reviews import (
    PendingReviewRecord,
    ReviewDecision,
    ReviewInbox,
)
from billzebub.statement_adapters.citi import citi_credit_card_adapter
from billzebub.statement_extraction import (
    ExtractionOutcome,
    ExtractionStatus,
    SourceLocator,
    StatementAdapter,
    StatementAdapterRegistry,
    StatementCandidate,
    StatementExtraction,
    StatementRowCandidate,
)
from billzebub.statement_reextract import (
    StatementReextractAction,
    StatementReextractError,
    StatementReextractor,
    format_statement_reextract,
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


def _candidate(*, row_count: int | None = None) -> StatementCandidate:
    rows = (
        StatementRowCandidate(
            raw_description="SYNTHETIC PURCHASE",
            posted_amount_text="-10.00",
            provider_transaction_date=date(2026, 1, 10),
            posting_date=date(2026, 1, 11),
            transaction_kind_hint="expense",
            locator=SourceLocator(page_number=1, line_number=20, text_start=0, text_end=36),
        ),
        StatementRowCandidate(
            raw_description="SYNTHETIC CARD PAYMENT",
            posted_amount_text="5.00",
            provider_transaction_date=date(2026, 1, 20),
            posting_date=date(2026, 1, 21),
            transaction_kind_hint="transfer",
            locator=SourceLocator(page_number=1, line_number=28, text_start=0, text_end=40),
        ),
    )
    return StatementCandidate(
        statement_identity="synthetic-2026-01",
        account_identifier="SYNTHETIC-001",
        statement_date=date(2026, 1, 31),
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        currency="SGD",
        opening_balance_text="100.00",
        closing_balance_text="105.00",
        candidate_row_count=row_count if row_count is not None else len(rows),
        rows=rows,
    )


def _source(
    database: Database,
    tmp_path: Path,
    *,
    slug: str,
    adapter_key: str = "synthetic-credit",
    institution: str = "synthetic-bank",
    content: bytes = b"%PDF-1.7\nsynthetic review statement\n%%EOF\n",
) -> tuple[UUID, UUID, ContentAddressedStore]:
    account_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug=slug,
                institution=institution,
                kind="credit_card",
                display_name="Synthetic Review Card",
                default_currency="SGD",
                statement_adapter_key=adapter_key,
                statement_account_identifier="SYNTHETIC-001",
            )
        )
    store = ContentAddressedStore(tmp_path / slug)
    artifact = ArtifactCapture(store, database).capture_bytes(
        content,
        ArtifactArrivalInput(
            source_type="statement_inbox",
            media_type="application/pdf",
            received_at=datetime(2026, 2, 1, tzinfo=UTC),
            original_name="statement.pdf",
        ),
    )
    return account_id, artifact.id, store


def _service(
    database: Database,
    store: ContentAddressedStore,
    tmp_path: Path,
    adapter: StatementAdapter,
) -> StatementReextractor:
    extraction = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([adapter]),
        password_root=tmp_path / "passwords",
    )
    return StatementReextractor(
        database,
        extraction,
        StatementAdapterRegistry([adapter]),
        JobQueue(database),
    )


def _exclude(database: Database, review_id: UUID) -> None:
    with database.transaction() as session:
        review = session.get(PendingReview, review_id)
        assert review is not None
        version = review.version
    ReviewInbox(database).decide(
        ReviewDecision(
            review_id=review_id,
            expected_version=version,
            choice="exclude_source_artifact",
        )
    )


def _review(database: Database, review_id: UUID) -> PendingReviewRecord:
    with database.transaction() as session:
        review = session.get(PendingReview, review_id)
        assert review is not None
        return ReviewInbox._record(review)


def _fail(
    database: Database,
    store: ContentAddressedStore,
    tmp_path: Path,
    account_id: UUID,
    artifact_id: UUID,
    adapter: StatementAdapter | None = None,
) -> ExtractionOutcome:
    chosen = adapter or SyntheticStatementAdapter(_candidate(row_count=3))
    outcome = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([chosen]),
        password_root=tmp_path / "passwords",
    ).extract(artifact_id=artifact_id, financial_account_id=account_id)
    assert outcome.status is ExtractionStatus.FAILED
    assert outcome.review_id is not None
    return outcome


def _reconcile_count(database: Database, account_id: UUID) -> int:
    with database.transaction() as session:
        count = session.scalar(
            select(func.count())
            .select_from(DurableJob)
            .where(
                DurableJob.kind == "reconcile_financial_account",
                DurableJob.dedupe_key == str(account_id),
            )
        )
    assert count is not None
    return int(count)


def _request_count(database: Database, review_id: UUID) -> int:
    with database.transaction() as session:
        count = session.scalar(
            select(func.count())
            .select_from(ReviewEvent)
            .where(
                ReviewEvent.review_id == review_id,
                ReviewEvent.event_type == "reextract_requested",
            )
        )
    assert count is not None
    return int(count)


@pytest.mark.integration
def test_excluded_artifact_reextracts_once_at_a_new_parser_version(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = _source(database, tmp_path, slug="synthetic-excluded-card")
    failed = _fail(database, store, tmp_path, account_id, artifact_id)
    assert failed.review_id is not None
    _exclude(database, failed.review_id)
    adapter = SyntheticStatementAdapter(_candidate())
    adapter.version = "1.0.1"
    service = _service(database, store, tmp_path, adapter)

    first = service.reextract((artifact_id,))
    second = service.reextract((artifact_id,))

    assert len(first) == 1
    report = first[0]
    assert report.action is StatementReextractAction.EXTRACTED
    assert report.status == "accepted"
    assert report.claim_count == 2
    assert report.enqueued_reconciliation is True
    assert report.extraction_id is not None
    assert report.extraction_id != failed.extraction_id
    assert len(ClaimBook(database).for_extraction(report.extraction_id)) == 2
    assert _reconcile_count(database, account_id) == 1
    assert _request_count(database, failed.review_id) == 1
    resolved = _review(database, failed.review_id)
    assert resolved.status.value == "resolved"
    assert resolved.version == 3
    with database.transaction() as session:
        event = session.scalar(
            select(ReviewEvent).where(
                ReviewEvent.review_id == failed.review_id,
                ReviewEvent.event_type == "reextract_requested",
            )
        )
    assert event is not None
    assert event.decision is None
    assert event.version == 3
    assert event.actor_id is not None
    assert "reconcile=enqueued" in format_statement_reextract(report)
    assert second[0].action is StatementReextractAction.UNCHANGED
    assert second[0].enqueued_reconciliation is False
    assert _reconcile_count(database, account_id) == 1
    assert _request_count(database, failed.review_id) == 1
    assert len(ClaimBook(database).for_extraction(report.extraction_id)) == 2


@pytest.mark.integration
def test_same_parser_version_reextract_is_a_noop(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = _source(database, tmp_path, slug="synthetic-same-version")
    failed = _fail(database, store, tmp_path, account_id, artifact_id)
    assert failed.review_id is not None
    _exclude(database, failed.review_id)

    report = _service(
        database,
        store,
        tmp_path,
        SyntheticStatementAdapter(_candidate(row_count=3)),
    ).reextract((artifact_id,))[0]

    assert report.action is StatementReextractAction.VERSION_UNCHANGED
    assert report.extraction_id == failed.extraction_id
    assert report.enqueued_reconciliation is False
    assert format_statement_reextract(report).endswith("parser version bump required")
    assert _reconcile_count(database, account_id) == 0
    assert _request_count(database, failed.review_id) == 0
    assert ClaimBook(database).for_extraction(failed.extraction_id) == ()
    assert _review(database, failed.review_id).status.value == "resolved"


@pytest.mark.integration
def test_non_excluded_and_accepted_artifacts_are_refused(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = _source(database, tmp_path, slug="synthetic-pending-card")
    failed = _fail(database, store, tmp_path, account_id, artifact_id)
    adapter = SyntheticStatementAdapter(_candidate())
    adapter.version = "1.0.1"

    with pytest.raises(StatementReextractError, match="not an excluded statement failure"):
        _service(database, store, tmp_path, adapter).reextract((artifact_id,))

    assert failed.review_id is not None
    assert _review(database, failed.review_id).status.value == "pending"
    assert _reconcile_count(database, account_id) == 0
    assert _request_count(database, failed.review_id) == 0

    accepted_account, accepted_artifact, accepted_store = _source(
        database,
        tmp_path,
        slug="synthetic-accepted-card",
    )
    accepted = StatementExtraction(
        database,
        accepted_store,
        StatementAdapterRegistry([SyntheticStatementAdapter(_candidate())]),
        password_root=tmp_path / "passwords",
    ).extract(artifact_id=accepted_artifact, financial_account_id=accepted_account)
    assert accepted.status is ExtractionStatus.ACCEPTED
    later = SyntheticStatementAdapter(_candidate())
    later.version = "1.0.1"

    with pytest.raises(StatementReextractError, match="not an excluded statement failure"):
        _service(database, accepted_store, tmp_path, later).reextract((accepted_artifact,))

    assert len(ClaimBook(database).for_extraction(accepted.extraction_id)) == 2
    assert _reconcile_count(database, accepted_account) == 0


def _citi_version_adapter(version: str, *, failing: bool) -> SyntheticStatementAdapter:
    live = citi_credit_card_adapter()
    adapter = SyntheticStatementAdapter(_candidate(row_count=3 if failing else None))
    adapter.key = live.key
    adapter.version = version
    adapter.institution = live.institution
    return adapter


def _stored_parser_version(database: Database, extraction_id: UUID) -> str:
    with database.transaction() as session:
        extraction = session.get(Extraction, extraction_id)
    assert extraction is not None
    return extraction.parser_version


@pytest.mark.integration
def test_citi_credit_4_reextracts_and_citi_credit_5_stays_version_unchanged(
    database: Database,
    tmp_path: Path,
) -> None:
    live = citi_credit_card_adapter()
    previous_version = "monopoly-0.21.6+citi-credit-4"
    assert live.version == "monopoly-0.21.6+citi-credit-5"
    assert live.key == "citi-credit-card"

    previous_account, previous_artifact, previous_store = _source(
        database,
        tmp_path,
        slug="citi-credit-4-stored",
        adapter_key=live.key,
        institution=live.institution,
        content=b"%PDF-1.7\nsynthetic citi credit previous\n%%EOF\n",
    )
    current_account, current_artifact, current_store = _source(
        database,
        tmp_path,
        slug="citi-credit-5-stored",
        adapter_key=live.key,
        institution=live.institution,
        content=b"%PDF-1.7\nsynthetic citi credit current\n%%EOF\n",
    )
    previous_failed = _fail(
        database,
        previous_store,
        tmp_path,
        previous_account,
        previous_artifact,
        _citi_version_adapter(previous_version, failing=True),
    )
    current_failed = _fail(
        database,
        current_store,
        tmp_path,
        current_account,
        current_artifact,
        _citi_version_adapter(live.version, failing=True),
    )
    assert previous_failed.review_id is not None
    assert current_failed.review_id is not None
    assert _stored_parser_version(database, previous_failed.extraction_id) == previous_version
    assert _stored_parser_version(database, current_failed.extraction_id) == live.version
    _exclude(database, previous_failed.review_id)
    _exclude(database, current_failed.review_id)

    current_adapter = _citi_version_adapter(live.version, failing=False)
    previous_report = _service(
        database,
        previous_store,
        tmp_path,
        current_adapter,
    ).reextract((previous_artifact,))[0]
    current_report = _service(
        database,
        current_store,
        tmp_path,
        current_adapter,
    ).reextract((current_artifact,))[0]

    assert previous_report.action is StatementReextractAction.EXTRACTED
    assert previous_report.status == "accepted"
    assert previous_report.extraction_id != previous_failed.extraction_id
    assert previous_report.extraction_id is not None
    assert _stored_parser_version(database, previous_report.extraction_id) == live.version
    assert current_report.action is StatementReextractAction.VERSION_UNCHANGED
    assert current_report.extraction_id == current_failed.extraction_id
    assert current_report.status == "failed"
    assert format_statement_reextract(current_report).endswith("parser version bump required")
    assert _request_count(database, current_failed.review_id) == 0
    assert _request_count(database, previous_failed.review_id) == 1
