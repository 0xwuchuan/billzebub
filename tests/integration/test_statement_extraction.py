from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.artifact_capture import ArtifactArrivalInput, ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.claims import ClaimBook
from billzebub.config import Environment, Settings
from billzebub.imports import ImportCatalog
from billzebub.persistence.database import Database
from billzebub.persistence.models import FinancialAccount
from billzebub.reviews import ReviewInbox
from billzebub.statement_extraction import (
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
        self.received_password_count = -1
        self.received_account_identifier: str | None = None

    def extract(
        self,
        path: Path,
        passwords: tuple[SecretStr, ...],
        expected_account_identifier: str | None = None,
    ) -> StatementCandidate:
        assert path.is_file()
        self.received_account_identifier = expected_account_identifier
        self.received_password_count = len(passwords)
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


@pytest.fixture
def statement_source(
    database: Database,
    tmp_path: Path,
) -> tuple[UUID, UUID, ContentAddressedStore]:
    account_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-statement-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Statement Card",
                default_currency="SGD",
                statement_adapter_key="synthetic-credit",
                statement_account_identifier="SYNTHETIC-001",
            )
        )
    store = ContentAddressedStore(tmp_path / "artifacts")
    artifact = ArtifactCapture(store, database).capture_bytes(
        b"%PDF-1.7\nsynthetic statement bytes\n%%EOF\n",
        ArtifactArrivalInput(
            source_type="statement_inbox",
            media_type="application/pdf",
            received_at=datetime(2026, 2, 1, tzinfo=UTC),
            original_name="statement.pdf",
        ),
    )
    return account_id, artifact.id, store


@pytest.mark.integration
def test_valid_statement_is_accepted_atomically_with_exact_claims(
    database: Database,
    statement_source: tuple[UUID, UUID, ContentAddressedStore],
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = statement_source
    adapter = SyntheticStatementAdapter(valid_candidate())
    extraction = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([adapter]),
        password_root=tmp_path / "passwords",
    )

    outcome = extraction.extract(artifact_id=artifact_id, financial_account_id=account_id)

    assert outcome.status is ExtractionStatus.ACCEPTED
    assert outcome.claim_count == 2
    assert outcome.failure is None
    claims = ClaimBook(database).for_extraction(outcome.extraction_id)
    assert [claim.posted_amount.to_wire() for claim in claims if claim.posted_amount] == [
        {"amount": "-10.00", "currency": "SGD"},
        {"amount": "5.00", "currency": "SGD"},
    ]
    assert [claim.transaction_kind_hint for claim in claims] == ["expense", "transfer"]
    assert claims[0].original_amount is not None
    assert claims[0].original_amount.to_wire() == {"amount": "-9.00", "currency": "USD"}
    locator = ClaimBook(database).source_locator(claims[0].id)
    assert (locator.page_number, locator.line_number, locator.text_start, locator.text_end) == (
        1,
        20,
        0,
        36,
    )
    assert adapter.received_password_count == 0
    assert adapter.received_account_identifier == "SYNTHETIC-001"
    import_record = ImportCatalog(database).get(outcome.extraction_id)
    assert import_record.status == "accepted"
    assert import_record.financial_account_name == "Synthetic Statement Card"
    assert import_record.validation_report["balance_validation"] is True
    assert "SYNTHETIC PURCHASE" not in repr(import_record)

    repeated = extraction.extract(artifact_id=artifact_id, financial_account_id=account_id)
    assert repeated.extraction_id == outcome.extraction_id
    assert repeated.duplicate is True
    assert len(ClaimBook(database).for_extraction(outcome.extraction_id)) == 2

    repackaged_artifact = ArtifactCapture(store, database).capture_bytes(
        b"%PDF-1.7\nsynthetic statement repackaged\n%%EOF\n",
        ArtifactArrivalInput(
            source_type="statement_inbox",
            media_type="application/pdf",
            received_at=datetime(2026, 2, 2, tzinfo=UTC),
            original_name="statement-repackaged.pdf",
        ),
    )
    duplicate_statement = extraction.extract(
        artifact_id=repackaged_artifact.id,
        financial_account_id=account_id,
    )
    assert duplicate_statement.extraction_id == outcome.extraction_id
    assert duplicate_statement.duplicate is True

    app = create_app(
        Settings(
            environment=Environment.TEST,
            artifact_root=tmp_path / "artifacts",
            development_identity="developer@example.test",
        ),
        database,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/v1/imports")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert "SYNTHETIC PURCHASE" not in response.text
    assert "account_identifier" not in response.text


@pytest.mark.integration
def test_account_mismatch_fails_with_no_claims_and_sanitized_report(
    database: Database,
    statement_source: tuple[UUID, UUID, ContentAddressedStore],
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = statement_source
    mismatched = replace(valid_candidate(), account_identifier="OTHER-ACCOUNT")
    extraction = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([SyntheticStatementAdapter(mismatched)]),
        password_root=tmp_path / "passwords",
    )

    outcome = extraction.extract(artifact_id=artifact_id, financial_account_id=account_id)

    assert outcome.status is ExtractionStatus.FAILED
    assert outcome.claim_count == 0
    assert outcome.failure is not None
    assert outcome.failure.code == "account_mismatch"
    assert "OTHER-ACCOUNT" not in repr(outcome.failure.details)
    assert ClaimBook(database).for_extraction(outcome.extraction_id) == ()
    assert outcome.review_id is not None


@pytest.mark.integration
def test_statement_accepts_activity_that_predates_the_billing_period(
    database: Database,
    statement_source: tuple[UUID, UUID, ContentAddressedStore],
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = statement_source
    late_row = replace(
        valid_candidate().rows[0],
        provider_transaction_date=date(2025, 12, 29),
        posting_date=date(2025, 12, 29),
    )
    candidate = replace(valid_candidate(), rows=(late_row, valid_candidate().rows[1]))

    outcome = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([SyntheticStatementAdapter(candidate)]),
        password_root=tmp_path / "passwords",
    ).extract(artifact_id=artifact_id, financial_account_id=account_id)

    assert outcome.status is ExtractionStatus.ACCEPTED


@pytest.mark.integration
@pytest.mark.parametrize(
    ("mutation", "failure_code"),
    [
        ("float_amount", "invalid_decimal_string"),
        ("row_coverage", "row_coverage_mismatch"),
        ("original_money", "original_money_incomplete"),
        ("balance", "balance_validation_failed"),
    ],
)
def test_strict_validation_rejects_incomplete_or_inexact_results_atomically(
    database: Database,
    statement_source: tuple[UUID, UUID, ContentAddressedStore],
    tmp_path: Path,
    mutation: str,
    failure_code: str,
) -> None:
    account_id, artifact_id, store = statement_source
    candidate = valid_candidate()
    if mutation == "float_amount":
        bad_row = replace(
            candidate.rows[0],
            posted_amount_text=cast(Any, -10.0),
        )
        candidate = replace(candidate, rows=(bad_row, candidate.rows[1]))
    elif mutation == "row_coverage":
        candidate = replace(candidate, candidate_row_count=3)
    elif mutation == "original_money":
        bad_row = replace(candidate.rows[0], original_currency=None)
        candidate = replace(candidate, rows=(bad_row, candidate.rows[1]))
    else:
        candidate = replace(candidate, closing_balance_text="104.99")
    extraction = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([SyntheticStatementAdapter(candidate)]),
        password_root=tmp_path / "passwords",
    )

    outcome = extraction.extract(artifact_id=artifact_id, financial_account_id=account_id)

    assert outcome.status is ExtractionStatus.FAILED
    assert outcome.failure is not None
    assert outcome.failure.code == failure_code
    assert ClaimBook(database).for_extraction(outcome.extraction_id) == ()


@pytest.mark.integration
def test_password_is_loaded_from_permission_restricted_host_file(
    database: Database,
    statement_source: tuple[UUID, UUID, ContentAddressedStore],
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = statement_source
    password_root = tmp_path / "passwords"
    password_root.mkdir(mode=0o700)
    password_file = password_root / "synthetic-card-password"
    password_file.write_text(  # pragma: allowlist secret
        "synthetic-test-value\n", encoding="utf-8"
    )
    password_file.chmod(0o600)
    with database.transaction() as session:
        account = session.get(FinancialAccount, account_id)
        assert account is not None
        account.statement_password_secret = password_file.name
    adapter = SyntheticStatementAdapter(valid_candidate())

    outcome = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([adapter]),
        password_root=password_root,
    ).extract(artifact_id=artifact_id, financial_account_id=account_id)

    assert outcome.status is ExtractionStatus.ACCEPTED
    assert adapter.received_password_count == 1


@pytest.mark.integration
def test_successful_reprocessing_requires_review_of_an_exact_diff(
    database: Database,
    statement_source: tuple[UUID, UUID, ContentAddressedStore],
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = statement_source
    first = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([SyntheticStatementAdapter(valid_candidate())]),
        password_root=tmp_path / "passwords",
    ).extract(artifact_id=artifact_id, financial_account_id=account_id)
    corrected_row = replace(
        valid_candidate().rows[0],
        raw_description="SYNTHETIC PURCHASE CORRECTED",
    )
    second_candidate = replace(
        valid_candidate(),
        rows=(corrected_row, valid_candidate().rows[1]),
    )
    second_adapter = SyntheticStatementAdapter(second_candidate)
    second_adapter.version = "2.0.0"
    extraction = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([second_adapter]),
        password_root=tmp_path / "passwords",
    )

    preview = extraction.extract(artifact_id=artifact_id, financial_account_id=account_id)

    assert preview.status is ExtractionStatus.REPROCESS_REQUIRED
    assert preview.failure is not None
    assert preview.failure.code == "successful_reprocess_requires_approval"
    assert preview.failure.details["diff"]["changed_rows"] == 1
    assert preview.review_id is not None
    assert len(ClaimBook(database).for_extraction(first.extraction_id)) == 2
    candidate_hash = preview.failure.details["candidate_hash"]

    accepted = extraction.extract(
        artifact_id=artifact_id,
        financial_account_id=account_id,
        approved_reprocess_hash=candidate_hash,
    )

    assert accepted.status is ExtractionStatus.ACCEPTED
    assert accepted.extraction_id != first.extraction_id
    assert len(ClaimBook(database).for_extraction(accepted.extraction_id)) == 2
    assert ReviewInbox(database).history(preview.review_id)[-1].event_type == "cancelled"


@pytest.mark.integration
def test_failed_extraction_retries_only_after_adapter_version_changes(
    database: Database,
    statement_source: tuple[UUID, UUID, ContentAddressedStore],
    tmp_path: Path,
) -> None:
    account_id, artifact_id, store = statement_source
    failing_adapter = SyntheticStatementAdapter(replace(valid_candidate(), candidate_row_count=3))
    extraction = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([failing_adapter]),
        password_root=tmp_path / "passwords",
    )
    failed = extraction.extract(artifact_id=artifact_id, financial_account_id=account_id)
    duplicate = extraction.extract(artifact_id=artifact_id, financial_account_id=account_id)

    assert failed.status is ExtractionStatus.FAILED
    assert duplicate.extraction_id == failed.extraction_id
    assert duplicate.duplicate is True

    corrected_adapter = SyntheticStatementAdapter(valid_candidate())
    corrected_adapter.version = "1.0.1"
    accepted = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry([corrected_adapter]),
        password_root=tmp_path / "passwords",
    ).extract(artifact_id=artifact_id, financial_account_id=account_id)

    assert accepted.status is ExtractionStatus.ACCEPTED
    assert accepted.extraction_id != failed.extraction_id
