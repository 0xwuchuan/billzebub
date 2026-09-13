from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from uuid6 import uuid7

from billzebub.categories import CategoryCatalog
from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.financial_history import (
    CategoryAllocation,
    Confirmation,
    FinancialHistory,
    TransactionKind,
)
from billzebub.money import Money
from billzebub.persistence.database import Database
from billzebub.persistence.models import Extraction, FinancialAccount, SourceArtifact


@pytest.fixture
def property_evidence(database: Database) -> tuple[UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-card-properties",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Card",
                default_currency="SGD",
            )
        )
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256="e" * 64,
                size=128,
                media_type="application/pdf",
                content_path="sha256/ee/" + "e" * 64,
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


@pytest.fixture
def property_categories(database: Database) -> tuple[UUID, UUID]:
    categories = CategoryCatalog(database)
    return categories.create("Property First").id, categories.create("Property Second").id


def record_statement_claim(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    amount: Decimal,
) -> UUID:
    account_id, artifact_id, extraction_id = evidence
    return (
        ClaimBook(database)
        .record(
            ClaimDraft(
                claim_type=ClaimType.STATEMENT,
                financial_account_id=account_id,
                source_artifact_id=artifact_id,
                extraction_id=extraction_id,
                raw_description="SYNTHETIC PROPERTY",
                posted_amount=Money(amount, "SGD"),
                provider_transaction_date=date(2026, 3, 1),
                posting_date=date(2026, 3, 2),
            )
        )
        .id
    )


_KIND_DIRECTIONS = st.sampled_from(
    [
        (TransactionKind.EXPENSE, -1),
        (TransactionKind.CASH_WITHDRAWAL, -1),
        (TransactionKind.INCOME, 1),
        (TransactionKind.REFUND, 1),
        (TransactionKind.REIMBURSEMENT, 1),
        (TransactionKind.TRANSFER, -1),
        (TransactionKind.TRANSFER, 1),
    ]
)


@pytest.mark.integration
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(cents=st.integers(min_value=1, max_value=100_000_000), case=_KIND_DIRECTIONS)
def test_every_confirmed_movement_is_balanced_for_exact_generated_amounts(
    database: Database,
    property_evidence: tuple[UUID, UUID, UUID],
    cents: int,
    case: tuple[TransactionKind, int],
) -> None:
    kind, direction = case
    amount = (Decimal(cents) / Decimal(100)) * direction
    claim_id = record_statement_claim(database, property_evidence, amount)

    transaction = FinancialHistory(database).confirm(
        Confirmation(
            statement_claim_id=claim_id,
            kind=kind,
            counterparty="Synthetic Property",
        )
    )

    journals = FinancialHistory(database).audit(transaction.id).journals
    assert len(journals) == 1
    assert journals[0].is_balanced
    assert all(posting.amount.amount > 0 for posting in journals[0].postings)


@pytest.mark.integration
@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    first_cents=st.integers(min_value=1, max_value=1_000_000),
    second_cents=st.integers(min_value=1, max_value=1_000_000),
)
def test_generated_category_splits_preserve_exact_expense_total(
    database: Database,
    property_evidence: tuple[UUID, UUID, UUID],
    property_categories: tuple[UUID, UUID],
    first_cents: int,
    second_cents: int,
) -> None:
    first_category_id, second_category_id = property_categories
    first = Decimal(first_cents) / Decimal(100)
    second = Decimal(second_cents) / Decimal(100)
    total = first + second
    claim_id = record_statement_claim(database, property_evidence, -total)
    transaction = FinancialHistory(database).confirm(
        Confirmation(
            statement_claim_id=claim_id,
            kind=TransactionKind.EXPENSE,
            counterparty="Synthetic Split Property",
            category_splits=(
                CategoryAllocation(first_category_id, Money(first, "SGD")),
                CategoryAllocation(second_category_id, Money(second, "SGD")),
            ),
        )
    )

    assert (
        sum(
            (split.amount.amount for split in transaction.category_splits),
            Decimal(0),
        )
        == total
    )
    assert FinancialHistory(database).audit(transaction.id).journals[0].is_balanced
