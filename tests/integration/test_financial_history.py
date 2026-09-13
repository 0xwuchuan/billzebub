from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from uuid6 import uuid7

from billzebub.claims import ClaimBook, ClaimDisposition, ClaimDraft, ClaimType
from billzebub.financial_history import (
    Confirmation,
    FinancialHistory,
    FinancialHistoryError,
    PostingDirection,
    TransactionKind,
)
from billzebub.money import Money
from billzebub.persistence.database import Database
from billzebub.persistence.models import Extraction, FinancialAccount, SourceArtifact


@pytest.fixture
def evidence_ids(database: Database) -> tuple[UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-card-history",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Card",
                default_currency="SGD",
            )
        )
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256="b" * 64,
                size=128,
                media_type="application/pdf",
                content_path="sha256/bb/" + "b" * 64,
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
def test_statement_and_real_time_claims_confirm_one_balanced_expense(
    database: Database,
    evidence_ids: tuple[UUID, UUID, UUID],
) -> None:
    account_id, artifact_id, extraction_id = evidence_ids
    claims = ClaimBook(database)
    statement_claim = claims.record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="SYNTHETIC COFFEE POSTED",
            posted_amount=Money.parse("-12.34", "SGD"),
            provider_transaction_date=date(2026, 1, 2),
            posting_date=date(2026, 1, 3),
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )
    real_time_claim = claims.record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="SYNTHETIC COFFEE",
            authorized_amount=Money.parse("-12.00", "SGD"),
            occurrence_at=datetime(2026, 1, 2, 16, 30, tzinfo=UTC),
        )
    )

    history = FinancialHistory(database, reporting_timezone="Asia/Singapore")
    confirmation = Confirmation(
        statement_claim_id=statement_claim.id,
        real_time_claim_id=real_time_claim.id,
        kind=TransactionKind.EXPENSE,
        counterparty="Synthetic Coffee",
    )
    transaction = history.confirm(confirmation)
    repeated = history.confirm(confirmation)

    assert repeated.id == transaction.id
    assert transaction.version == 1
    assert transaction.kind is TransactionKind.EXPENSE
    assert transaction.posted_amount == Money.parse("-12.34", "SGD")
    assert transaction.authorized_amount == Money.parse("-12.00", "SGD")
    assert transaction.effective_date == date(2026, 1, 3)
    assert len(transaction.category_splits) == 1
    assert transaction.category_splits[0].category_name == "Uncategorized"
    assert transaction.category_splits[0].amount == Money.parse("12.34", "SGD")

    audit = history.audit(transaction.id)
    assert len(audit.versions) == 1
    assert len(audit.journals) == 1
    assert [(posting.direction, posting.amount) for posting in audit.journals[0].postings] == [
        (PostingDirection.DEBIT, Money.parse("12.34", "SGD")),
        (PostingDirection.CREDIT, Money.parse("12.34", "SGD")),
    ]
    assert audit.journals[0].is_balanced
    assert claims.current_disposition(statement_claim.id) is ClaimDisposition.CONFIRMED
    assert claims.current_disposition(real_time_claim.id) is ClaimDisposition.CONFIRMED


@pytest.mark.integration
def test_real_time_claim_alone_cannot_enter_financial_history(
    database: Database,
    evidence_ids: tuple[UUID, UUID, UUID],
) -> None:
    account_id, artifact_id, extraction_id = evidence_ids
    claim = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="SYNTHETIC PENDING",
            authorized_amount=Money.parse("-9.99", "SGD"),
            occurrence_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )

    with pytest.raises(FinancialHistoryError, match="Statement Claim"):
        FinancialHistory(database).confirm(
            Confirmation(
                statement_claim_id=claim.id,
                kind=TransactionKind.EXPENSE,
                counterparty="Synthetic Pending",
            )
        )

    assert ClaimBook(database).current_disposition(claim.id) is ClaimDisposition.PROVISIONAL
