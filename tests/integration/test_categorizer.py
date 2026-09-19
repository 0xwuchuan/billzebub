from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import inspect, select, text
from typesafe_sdk import TypeSafeError
from uuid6 import uuid7

from billzebub.categories import CategoryCatalog
from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.financial_history import Confirmation, FinancialHistory, TransactionKind
from billzebub.identity import OwnerIdentity
from billzebub.jev import JevError, JevSubject, Proposal
from billzebub.jev_categorizer import JevCategorizer
from billzebub.money import Money
from billzebub.owner_actors import OwnerActors
from billzebub.owner_transaction_actions import OwnerCategorizationCommand, OwnerTransactionActions
from billzebub.owner_workspace import OwnerWorkspace
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    Extraction,
    FinancialAccount,
    JevCategorizationAttempt,
    PendingReview,
    SourceArtifact,
)
from billzebub.reviews import PendingReviewStatus


@pytest.fixture
def evidence(database: Database) -> tuple[UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-categorizer-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Categorizer Card",
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
                financial_account_id=account_id,
                adapter_key="synthetic-categorizer",
                parser_version="v1",
                status="accepted",
                accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    return account_id, artifact_id, extraction_id


def _confirm_expense(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    *,
    counterparty: str,
    amount: str = "-12.34",
    day: date = date(2026, 3, 7),
    kind: TransactionKind = TransactionKind.EXPENSE,
) -> UUID:
    account_id, artifact_id, extraction_id = evidence
    statement = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description=f"{counterparty} posted",
            posted_amount=Money.parse(amount, "SGD"),
            provider_transaction_date=day,
            posting_date=day,
            transaction_kind_hint=kind.value,
        )
    )
    return (
        FinancialHistory(database)
        .confirm(
            Confirmation(
                statement_claim_id=statement.id,
                kind=kind,
                counterparty=counterparty,
            )
        )
        .id
    )


def _pending_categorization(database: Database, transaction_id: UUID) -> PendingReview | None:
    with database.transaction() as session:
        return session.scalar(
            select(PendingReview).where(
                PendingReview.subject_type == "transaction",
                PendingReview.subject_id == transaction_id,
                PendingReview.condition_code == "categorization_needed",
                PendingReview.status == PendingReviewStatus.PENDING.value,
            )
        )


@pytest.mark.integration
def test_confirmed_expense_stays_uncategorized_with_attention_review(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    CategoryCatalog(database).create("Groceries")
    CategoryCatalog(database).create("Dining")
    unknown_id = _confirm_expense(database, evidence, counterparty="Synthetic Unknown Vendor")
    grocer_id = _confirm_expense(
        database,
        evidence,
        counterparty="Synthetic Grocer",
        amount="-8.00",
        day=date(2026, 3, 8),
    )
    named_id = _confirm_expense(
        database,
        evidence,
        counterparty="Synthetic Groceries Hall",
        amount="-9.00",
        day=date(2026, 3, 9),
    )

    for transaction_id in (unknown_id, grocer_id, named_id):
        current = FinancialHistory(database).get(transaction_id)
        review = _pending_categorization(database, transaction_id)
        assert current.category_splits[0].category_name == "Uncategorized"
        assert review is not None


@pytest.mark.integration
def test_owner_categorization_does_not_upsert_a_reusable_map(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    gifts = CategoryCatalog(database).create("Gifts")
    first_id = _confirm_expense(database, evidence, counterparty="Synthetic Rare Merchant")
    actor_id = OwnerActors(database).resolve(
        OwnerIdentity(login="owner@example.test", name="Synthetic Owner")
    )
    categorized = OwnerTransactionActions(database).categorize(
        OwnerCategorizationCommand(
            transaction_id=first_id,
            expected_version=1,
            category_id=gifts.id,
            actor_id=actor_id,
        )
    )
    second_id = _confirm_expense(
        database,
        evidence,
        counterparty="Synthetic Rare Merchant",
        amount="-20.00",
        day=date(2026, 3, 8),
    )
    second = FinancialHistory(database).get(second_id)
    with database.transaction() as session:
        tables = set(inspect(database.engine).get_table_names())
        map_rows = session.execute(text("SELECT to_regclass('counterparty_category_map')")).scalar()

    assert categorized.category_splits[0].category_id == gifts.id
    assert _pending_categorization(database, first_id) is None
    assert second.category_splits[0].category_name == "Uncategorized"
    assert _pending_categorization(database, second_id) is not None
    assert "counterparty_category_map" not in tables
    assert map_rows is None


@pytest.mark.integration
def test_transfers_are_not_forced_into_expense_categories(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    CategoryCatalog(database).create("Transport")
    transaction_id = _confirm_expense(
        database,
        evidence,
        counterparty="Synthetic Taxi Transfer",
        amount="-50.00",
        kind=TransactionKind.TRANSFER,
    )

    current = FinancialHistory(database).get(transaction_id)

    assert current.kind is TransactionKind.TRANSFER
    assert current.category_splits == ()
    assert _pending_categorization(database, transaction_id) is None


@pytest.mark.integration
def test_provisional_claim_projection_does_not_guess_categories(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    account_id, artifact_id, extraction_id = evidence
    gifts = CategoryCatalog(database).create("Gifts")
    CategoryCatalog(database).create("Groceries")
    actor_id = OwnerActors(database).resolve(
        OwnerIdentity(login="owner@example.test", name="Synthetic Owner")
    )
    taught_id = _confirm_expense(
        database, evidence, counterparty="Synthetic Taught Merchant", day=date(2026, 3, 1)
    )
    OwnerTransactionActions(database).categorize(
        OwnerCategorizationCommand(
            transaction_id=taught_id,
            expected_version=1,
            category_id=gifts.id,
            actor_id=actor_id,
        )
    )
    ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="Synthetic Groceries",
            authorized_amount=Money.parse("-8.50", "SGD"),
            occurrence_at=datetime(2026, 3, 7, 12, tzinfo=UTC),
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )
    ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="Synthetic Taught Merchant",
            authorized_amount=Money.parse("-4.00", "SGD"),
            occurrence_at=datetime(2026, 3, 7, 13, tzinfo=UTC),
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )
    ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="Synthetic Unknown Vendor",
            authorized_amount=Money.parse("-3.00", "SGD"),
            occurrence_at=datetime(2026, 3, 7, 14, tzinfo=UTC),
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )
    ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="Synthetic Taxi Transfer",
            authorized_amount=Money.parse("-9.00", "SGD"),
            occurrence_at=datetime(2026, 3, 7, 15, tzinfo=UTC),
            transaction_kind_hint=TransactionKind.TRANSFER.value,
        )
    )

    items = {
        item.counterparty: item
        for item in OwnerWorkspace(database).list_transactions().items
        if item.authorized_amount is not None and item.posted_amount == Money.parse("0", "SGD")
    }

    assert items["Synthetic Groceries"].category_splits == ()
    assert items["Synthetic Taught Merchant"].category_splits == ()
    assert items["Synthetic Unknown Vendor"].category_splits == ()
    assert items["Synthetic Taxi Transfer"].category_splits == ()
    assert items["Synthetic Taxi Transfer"].kind is TransactionKind.TRANSFER


class _FixedProposer:
    def __init__(self, proposal: Proposal) -> None:
        self.proposal = proposal
        self.subjects: list[JevSubject] = []

    def propose(self, subject: JevSubject, categories: object) -> Proposal:
        del categories
        self.subjects.append(subject)
        return self.proposal


@pytest.mark.integration
def test_worker_jev_applies_category_at_half_confidence(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    gifts = CategoryCatalog(database).create("Gifts")
    transaction_id = _confirm_expense(database, evidence, counterparty="Synthetic Florist")
    proposer = _FixedProposer(
        Proposal(
            action="apply",
            category_id=gifts.id,
            category_name="Gifts",
            confidence=Decimal("0.5"),
            model="jev-1.13.0",
            choice="Gifts",
        )
    )

    updated = JevCategorizer(database, proposer).categorize_transaction(transaction_id)
    current = FinancialHistory(database).get(transaction_id)

    assert updated is not None
    assert current.category_splits[0].category_id == gifts.id
    assert _pending_categorization(database, transaction_id) is None
    assert proposer.subjects[0].counterparty == "Synthetic Florist"
    assert str(transaction_id) not in proposer.subjects[0].counterparty
    attempt = _latest_attempt(database, transaction_id)
    assert attempt is not None
    assert attempt.action == "apply"
    assert attempt.choice == "Gifts"
    assert attempt.choice_confidence == Decimal("0.5")
    assert attempt.noul is None
    assert attempt.category_id == gifts.id
    assert attempt.category_name == "Gifts"
    assert attempt.counterparty == "Synthetic Florist"
    assert attempt.amount == Decimal("-12.34")
    assert attempt.currency == "SGD"
    assert attempt.kind == "expense"
    assert attempt.model == "jev-1.13.0"
    assert attempt.error_class is None


@pytest.mark.integration
def test_worker_jev_below_threshold_or_missing_key_leaves_review(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    CategoryCatalog(database).create("Gifts")
    skipped_id = _confirm_expense(database, evidence, counterparty="Synthetic Skip Shop")
    missing_key_id = _confirm_expense(
        database,
        evidence,
        counterparty="Synthetic No Key",
        amount="-3.00",
        day=date(2026, 3, 8),
    )
    skip_proposer = _FixedProposer(
        Proposal(
            action="skip",
            category_id=None,
            category_name=None,
            confidence=Decimal("0.49"),
            model="jev-1.13.0",
            choice="Gifts",
        )
    )

    assert JevCategorizer(database, skip_proposer).categorize_transaction(skipped_id) is None
    assert JevCategorizer(database, None).categorize_transaction(missing_key_id) is None
    assert FinancialHistory(database).get(skipped_id).category_splits[0].category_name == (
        "Uncategorized"
    )
    assert _pending_categorization(database, skipped_id) is not None
    assert _pending_categorization(database, missing_key_id) is not None
    assert JevCategorizer(database, skip_proposer).pending_transaction_ids() == (
        skipped_id,
        missing_key_id,
    )
    skip_attempt = _latest_attempt(database, skipped_id)
    assert skip_attempt is not None
    assert skip_attempt.action == "skip"
    assert skip_attempt.choice == "Gifts"
    assert skip_attempt.choice_confidence == Decimal("0.49")
    assert skip_attempt.noul is None
    assert skip_attempt.category_id is None
    assert skip_attempt.category_name is None
    assert _latest_attempt(database, missing_key_id) is None
    review = _pending_categorization(database, skipped_id)
    assert review is not None
    owner_review = OwnerWorkspace(database).get_review(review.id)
    attempt_context = owner_review.context["jev_attempt"]
    assert attempt_context["action"] == "skip"
    assert attempt_context["choice"] == "Gifts"
    assert attempt_context["choice_confidence"] == "0.49"
    assert attempt_context["noul"] is None
    assert attempt_context["category_name"] is None
    assert attempt_context["model"] == "jev-1.13.0"


class _BoomProposer:
    def propose(self, subject: JevSubject, categories: object) -> Proposal:
        del subject, categories
        raise JevError("typesafe systemone failed") from TypeSafeError("nope")


@pytest.mark.integration
def test_worker_jev_persists_typesafe_errors_then_retries(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    CategoryCatalog(database).create("Gifts")
    transaction_id = _confirm_expense(database, evidence, counterparty="Synthetic Timeout Shop")

    with pytest.raises(JevError, match="systemone failed"):
        JevCategorizer(database, _BoomProposer()).categorize_transaction(transaction_id)

    assert _pending_categorization(database, transaction_id) is not None
    attempt = _latest_attempt(database, transaction_id)
    assert attempt is not None
    assert attempt.action == "skip"
    assert attempt.error_class == "TypeSafeError"
    assert attempt.error_message == "nope"
    assert "api_key" not in (attempt.error_message or "").casefold()
    review = _pending_categorization(database, transaction_id)
    assert review is not None
    context = OwnerWorkspace(database).get_review(review.id).context["jev_attempt"]
    assert context["error_class"] == "TypeSafeError"
    assert context["error_message"] == "nope"


def _latest_attempt(database: Database, transaction_id: UUID) -> JevCategorizationAttempt | None:
    with database.transaction() as session:
        return session.scalar(
            select(JevCategorizationAttempt)
            .where(JevCategorizationAttempt.transaction_id == transaction_id)
            .order_by(
                JevCategorizationAttempt.attempted_at.desc(),
                JevCategorizationAttempt.id.desc(),
            )
        )
