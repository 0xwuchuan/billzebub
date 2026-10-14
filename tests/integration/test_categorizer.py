from collections.abc import Sequence
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
from billzebub.jev import JevCategory, JevError, JevSubject, Proposal, parse_jev_proposal
from billzebub.jev_categorizer import JevCategorizer
from billzebub.money import Money
from billzebub.owner_actors import OwnerActors
from billzebub.owner_transaction_actions import OwnerCategorizationCommand, OwnerTransactionActions
from billzebub.owner_workspace import OwnerWorkspace
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    Category,
    ClaimCategory,
    Extraction,
    FinancialAccount,
    JevCategorizationAttempt,
    PendingReview,
    SourceArtifact,
)
from billzebub.reconciliation import Reconciliation
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


def _wallet_extraction(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    *,
    adapter_key: str = "apple_wallet_shortcut",
    parser_version: str = "wallet-v1",
) -> UUID:
    account_id, artifact_id, _extraction_id = evidence
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            Extraction(
                id=extraction_id,
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key=adapter_key,
                parser_version=parser_version,
                status="accepted",
                accepted_at=datetime(2026, 3, 1, tzinfo=UTC),
            )
        )
    return extraction_id


def _wallet_claim(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    extraction_id: UUID,
    *,
    description: str,
    amount: str = "-12.34",
    kind: str = TransactionKind.EXPENSE.value,
    occurred_at: datetime = datetime(2026, 3, 7, 13, 5, tzinfo=UTC),
) -> UUID:
    account_id, artifact_id, _extraction_id = evidence
    return (
        ClaimBook(database)
        .record(
            ClaimDraft(
                claim_type=ClaimType.REAL_TIME,
                financial_account_id=account_id,
                source_artifact_id=artifact_id,
                extraction_id=extraction_id,
                raw_description=description,
                authorized_amount=Money.parse(amount, "SGD"),
                occurrence_at=occurred_at,
                transaction_kind_hint=kind,
            )
        )
        .id
    )


def _latest_claim_attempt(database: Database, claim_id: UUID) -> JevCategorizationAttempt | None:
    with database.transaction() as session:
        return session.scalar(
            select(JevCategorizationAttempt)
            .where(JevCategorizationAttempt.claim_id == claim_id)
            .order_by(
                JevCategorizationAttempt.attempted_at.desc(),
                JevCategorizationAttempt.id.desc(),
            )
        )


class _RecordingProposer:
    def __init__(self, proposal: Proposal) -> None:
        self.proposal = proposal
        self.subjects: list[JevSubject] = []
        self.categories: list[Sequence[JevCategory]] = []

    def propose(self, subject: JevSubject, categories: Sequence[JevCategory]) -> Proposal:
        self.subjects.append(subject)
        self.categories.append(categories)
        return self.proposal


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
            skip_reason="low_confidence",
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
    assert skip_attempt.skip_reason == "low_confidence"
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
    assert attempt_context["skip_reason"] == "low_confidence"
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
    assert attempt.skip_reason == "jev_unavailable"
    assert attempt.error_message == "nope"
    assert "api_key" not in (attempt.error_message or "").casefold()
    review = _pending_categorization(database, transaction_id)
    assert review is not None
    context = OwnerWorkspace(database).get_review(review.id).context["jev_attempt"]
    assert context["error_class"] == "TypeSafeError"
    assert context["error_message"] == "nope"


@pytest.mark.integration
def test_worker_jev_categorizes_claim_only_wallet_rows_and_reconcile_carries_it(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    gifts = CategoryCatalog(database).create("Gifts")
    with database.transaction() as session:
        session.add(Category(id=uuid7(), name="Uncategorized", active=True, sort_order=0))
    extraction_id = _wallet_extraction(database, evidence)
    claim_id = _wallet_claim(
        database,
        evidence,
        extraction_id,
        description="SYNTHETIC COFFEE",
    )
    proposer = _RecordingProposer(
        Proposal(
            action="apply",
            category_id=gifts.id,
            category_name="Gifts",
            confidence=Decimal("0.5"),
            model="jev-1.13.0",
            choice="Gifts",
        )
    )

    applied = JevCategorizer(database, proposer).categorize_claim(claim_id)
    again = JevCategorizer(database, proposer).categorize_claim(claim_id)
    provisional = {
        item.counterparty: item
        for item in OwnerWorkspace(database).list_transactions().items
        if item.authorized_amount is not None and item.posted_amount == Money.parse("0", "SGD")
    }
    attempt = _latest_claim_attempt(database, claim_id)

    assert applied == gifts.id
    assert again is None
    assert len(proposer.subjects) == 1
    assert proposer.subjects[0] == JevSubject(
        counterparty="SYNTHETIC COFFEE",
        amount="-12.34",
        currency="SGD",
        effective_date="2026-03-07",
        kind="expense",
    )
    assert str(claim_id) not in proposer.subjects[0].counterparty
    offered = {category.name for category in proposer.categories[0]}
    assert offered == {"Gifts"}
    assert provisional["SYNTHETIC COFFEE"].category_splits[0].category_id == gifts.id
    assert provisional["SYNTHETIC COFFEE"].category_splits[0].category_name == "Gifts"
    assert attempt is not None
    assert attempt.transaction_id is None
    assert attempt.claim_id == claim_id
    assert attempt.action == "apply"
    assert attempt.choice_confidence == Decimal("0.5")
    assert attempt.noul is None
    assert attempt.category_id == gifts.id
    assert JevCategorizer(database, proposer).pending_claim_ids() == ()

    account_id, artifact_id, statement_extraction_id = evidence
    ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=statement_extraction_id,
            raw_description="SYNTHETIC COFFEE POSTED",
            posted_amount=Money.parse("-12.34", "SGD"),
            provider_transaction_date=date(2026, 3, 7),
            posting_date=date(2026, 3, 7),
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )
    run = Reconciliation(database).reconcile_account(account_id)

    assert len(run.confirmations) == 1
    assert run.confirmations[0].real_time_claim_id == claim_id
    current = FinancialHistory(database).get(run.confirmations[0].transaction_id)
    assert current.category_splits[0].category_id == gifts.id
    assert current.category_splits[0].amount == Money.parse("12.34", "SGD")
    assert _pending_categorization(database, current.id) is None
    remaining = [
        item for item in OwnerWorkspace(database).list_transactions().items if item.id == claim_id
    ]
    assert remaining == []


@pytest.mark.integration
def test_claim_jev_below_threshold_stays_uncategorized_for_catch_up(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    CategoryCatalog(database).create("Gifts")
    extraction_id = _wallet_extraction(database, evidence)
    claim_id = _wallet_claim(database, evidence, extraction_id, description="Synthetic Skip Shop")
    proposer = _FixedProposer(
        Proposal(
            action="skip",
            category_id=None,
            category_name=None,
            confidence=Decimal("0.49"),
            model="jev-1.13.0",
            choice="Gifts",
            skip_reason="low_confidence",
        )
    )

    assert JevCategorizer(database, proposer).categorize_claim(claim_id) is None
    projected = OwnerWorkspace(database).get_transaction(claim_id)
    attempt = _latest_claim_attempt(database, claim_id)

    assert projected.category_splits == ()
    assert projected.posted_amount == Money.parse("0", "SGD")
    assert attempt is not None
    assert attempt.action == "skip"
    assert attempt.choice_confidence == Decimal("0.49")
    assert attempt.noul is None
    assert attempt.category_id is None
    assert JevCategorizer(database, proposer).pending_claim_ids() == (claim_id,)

    class _Queue:
        def __init__(self) -> None:
            self.kinds: list[str] = []

        def enqueue(
            self,
            kind: str,
            payload: dict[str, object],
            *,
            dedupe_key: str | None = None,
            max_attempts: int = 5,
            available_at: object = None,
        ) -> object:
            del payload, dedupe_key, max_attempts, available_at
            self.kinds.append(kind)
            return object()

    queue = _Queue()
    assert JevCategorizer(database, proposer).enqueue_pending(queue) == 1
    assert queue.kinds == ["categorize_claim"]


@pytest.mark.integration
def test_claim_jev_ignores_linked_transfers_and_non_wallet_claims(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    CategoryCatalog(database).create("Gifts")
    wallet_extraction = _wallet_extraction(database, evidence)
    paylah_extraction = _wallet_extraction(
        database,
        evidence,
        adapter_key="paylah_shortcut",
        parser_version="paylah-v1",
    )
    transfer_id = _wallet_claim(
        database,
        evidence,
        wallet_extraction,
        description="Synthetic Taxi Transfer",
        amount="-9.00",
        kind=TransactionKind.TRANSFER.value,
        occurred_at=datetime(2026, 3, 7, 15, tzinfo=UTC),
    )
    paylah_id = _wallet_claim(
        database,
        evidence,
        paylah_extraction,
        description="Synthetic PayLah",
        amount="-8.50",
        occurred_at=datetime(2026, 3, 7, 16, tzinfo=UTC),
    )
    linked_id = _wallet_claim(
        database,
        evidence,
        wallet_extraction,
        description="SYNTHETIC LINKED",
        amount="-4.00",
        occurred_at=datetime(2026, 3, 7, 17, tzinfo=UTC),
    )
    account_id, artifact_id, statement_extraction_id = evidence
    ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=statement_extraction_id,
            raw_description="SYNTHETIC LINKED POSTED",
            posted_amount=Money.parse("-4.00", "SGD"),
            provider_transaction_date=date(2026, 3, 7),
            posting_date=date(2026, 3, 7),
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )
    Reconciliation(database).reconcile_account(account_id)
    proposer = _FixedProposer(
        Proposal(
            action="apply",
            category_id=uuid7(),
            category_name="Gifts",
            confidence=Decimal("0.9"),
            model="jev-1.13.0",
            choice="Gifts",
        )
    )

    assert JevCategorizer(database, proposer).categorize_claim(transfer_id) is None
    assert JevCategorizer(database, proposer).categorize_claim(paylah_id) is None
    assert JevCategorizer(database, proposer).categorize_claim(linked_id) is None
    assert proposer.subjects == []
    assert JevCategorizer(database, proposer).pending_claim_ids() == ()
    assert _latest_claim_attempt(database, transfer_id) is None
    assert _latest_claim_attempt(database, paylah_id) is None
    assert _latest_claim_attempt(database, linked_id) is None


@pytest.mark.integration
def test_claim_jev_persists_typesafe_errors_without_a_category(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    CategoryCatalog(database).create("Gifts")
    extraction_id = _wallet_extraction(database, evidence)
    claim_id = _wallet_claim(
        database, evidence, extraction_id, description="Synthetic Timeout Shop"
    )

    with pytest.raises(JevError, match="systemone failed"):
        JevCategorizer(database, _BoomProposer()).categorize_claim(claim_id)

    attempt = _latest_claim_attempt(database, claim_id)
    assert attempt is not None
    assert attempt.transaction_id is None
    assert attempt.action == "skip"
    assert attempt.error_class == "TypeSafeError"
    assert attempt.skip_reason == "jev_unavailable"
    assert attempt.error_message == "nope"
    with database.transaction() as session:
        stored = session.scalar(select(ClaimCategory).where(ClaimCategory.claim_id == claim_id))
    assert stored is None
    assert JevCategorizer(database, None).categorize_claim(claim_id) is None
    assert JevCategorizer(database, None).pending_claim_ids() == (claim_id,)


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


class _ParsingProposer:
    def __init__(self, choice: str) -> None:
        self.choice = choice
        self.model = "jev-1.13.0"

    def propose(self, subject: JevSubject, categories: Sequence[JevCategory]) -> Proposal:
        del subject
        return parse_jev_proposal(
            self.choice,
            Decimal("0.96"),
            categories,
            Decimal("0.5"),
            model=self.model,
        )


@pytest.mark.integration
def test_high_confidence_path_and_ambiguous_leaf_record_raw_choice_and_skip_reason(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    catalog = CategoryCatalog(database)
    bank = catalog.create("Bank")
    card = catalog.create("Card")
    bank_fees = catalog.create("Fees", parent_id=bank.id)
    catalog.create("Fees", parent_id=card.id)
    raw_choice = "  Bank / Fees "
    applied_id = _confirm_expense(database, evidence, counterparty="Synthetic Path Shop")
    ambiguous_id = _confirm_expense(
        database,
        evidence,
        counterparty="Synthetic Ambiguous Shop",
        amount="-4.00",
        day=date(2026, 3, 8),
    )

    updated = JevCategorizer(database, _ParsingProposer(raw_choice)).categorize_transaction(
        applied_id
    )
    assert (
        JevCategorizer(database, _ParsingProposer("Fees")).categorize_transaction(ambiguous_id)
        is None
    )

    assert updated is not None
    assert updated.category_splits[0].category_id == bank_fees.id
    applied = _latest_attempt(database, applied_id)
    skipped = _latest_attempt(database, ambiguous_id)
    assert applied is not None
    assert applied.action == "apply"
    assert applied.choice == raw_choice
    assert applied.skip_reason is None
    assert skipped is not None
    assert skipped.action == "skip"
    assert skipped.choice == "Fees"
    assert skipped.skip_reason == "ambiguous_category"
    assert skipped.category_id is None
