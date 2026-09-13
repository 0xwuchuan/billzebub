from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from uuid6 import uuid7

from billzebub.categories import CategoryCatalog, CategoryError
from billzebub.claims import ClaimBook, ClaimDisposition, ClaimDraft, ClaimType
from billzebub.financial_history import (
    CategoryAllocation,
    Confirmation,
    Correction,
    FinancialHistory,
    FinancialHistoryError,
    PostingDirection,
    TransactionKind,
)
from billzebub.money import Money
from billzebub.persistence.database import Database
from billzebub.persistence.models import Extraction, FinancialAccount, SourceArtifact


@pytest.fixture
def statement_claim(database: Database) -> tuple[UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-card-correction",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Card",
                default_currency="SGD",
            )
        )
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256="c" * 64,
                size=128,
                media_type="application/pdf",
                content_path="sha256/cc/" + "c" * 64,
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
    claim = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="SYNTHETIC MARKET",
            posted_amount=Money.parse("-10.00", "SGD"),
            provider_transaction_date=date(2026, 2, 1),
            posting_date=date(2026, 2, 2),
        )
    )
    return account_id, claim.id


@pytest.mark.integration
def test_categories_allow_only_top_level_and_one_subcategory(
    database: Database,
) -> None:
    categories = CategoryCatalog(database)
    food = categories.create("Food")
    dining = categories.create("Dining", parent_id=food.id)

    assert dining.parent_id == food.id
    with pytest.raises(CategoryError, match="two levels"):
        categories.create("Late night", parent_id=dining.id)
    with pytest.raises(CategoryError, match="reserved"):
        categories.create("Uncategorized")


@pytest.mark.integration
def test_category_split_must_exactly_equal_expense(
    database: Database,
    statement_claim: tuple[UUID, UUID],
) -> None:
    _, claim_id = statement_claim
    categories = CategoryCatalog(database)
    food = categories.create("Food")
    household = categories.create("Household")
    history = FinancialHistory(database)

    with pytest.raises(FinancialHistoryError, match="equal the Expense"):
        history.confirm(
            Confirmation(
                statement_claim_id=claim_id,
                kind=TransactionKind.EXPENSE,
                counterparty="Synthetic Market",
                category_splits=(
                    CategoryAllocation(food.id, Money.parse("6.00", "SGD")),
                    CategoryAllocation(household.id, Money.parse("3.99", "SGD")),
                ),
            )
        )

    assert ClaimBook(database).current_disposition(claim_id) is ClaimDisposition.PROVISIONAL


@pytest.mark.integration
def test_correction_reverses_prior_journal_and_preserves_versions(
    database: Database,
    statement_claim: tuple[UUID, UUID],
) -> None:
    _, claim_id = statement_claim
    food = CategoryCatalog(database).create("Food")
    history = FinancialHistory(database)
    original = history.confirm(
        Confirmation(
            statement_claim_id=claim_id,
            kind=TransactionKind.EXPENSE,
            counterparty="Synthetic Market",
        )
    )

    corrected = history.correct(
        Correction(
            transaction_id=original.id,
            reason="Correct posted amount and category",
            posted_amount=Money.parse("-12.00", "SGD"),
            category_splits=(CategoryAllocation(food.id, Money.parse("12.00", "SGD")),),
        )
    )

    assert corrected.version == 2
    assert corrected.posted_amount == Money.parse("-12.00", "SGD")
    assert corrected.category_splits[0].category_name == "Food"

    audit = history.audit(original.id)
    assert [version.version for version in audit.versions] == [1, 2]
    assert audit.versions[0].posted_amount == Money.parse("-10.00", "SGD")
    assert [journal.journal_type for journal in audit.journals] == [
        "confirmation",
        "correction_reversal",
        "correction_replacement",
    ]
    assert all(journal.is_balanced for journal in audit.journals)
    original_postings = audit.journals[0].postings
    reversal_postings = audit.journals[1].postings
    assert [(p.direction, p.amount, p.ledger_account_code) for p in reversal_postings] == [
        (
            PostingDirection.CREDIT
            if p.direction is PostingDirection.DEBIT
            else PostingDirection.DEBIT,
            p.amount,
            p.ledger_account_code,
        )
        for p in original_postings
    ]
    assert audit.journals[1].reverses_journal_id == audit.journals[0].id
