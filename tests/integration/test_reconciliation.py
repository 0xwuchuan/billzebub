from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from uuid6 import uuid7

from billzebub.categories import CategoryCatalog
from billzebub.claims import ClaimBook, ClaimDisposition, ClaimDraft, ClaimType
from billzebub.financial_history import FinancialHistory
from billzebub.money import Money
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    Category,
    ClaimCategory,
    Extraction,
    FinancialAccount,
    PendingReview,
    ReconciledClaimPair,
    ReferenceExchangeRate,
    RejectedClaimPair,
    SourceArtifact,
)
from billzebub.reconciliation import Reconciliation, ReconciliationRun
from billzebub.reviews import PendingReviewStatus, ReviewDecision


@dataclass(frozen=True, slots=True)
class ReconciliationEvidence:
    database: Database
    account_id: UUID
    artifact_id: UUID
    extraction_id: UUID

    def real_time(
        self,
        *,
        amount: str,
        currency: str = "SGD",
        occurred_at: datetime = datetime(2026, 1, 10, 12, tzinfo=UTC),
        description: str = "SYNTHETIC COFFEE",
    ) -> UUID:
        return (
            ClaimBook(self.database)
            .record(
                ClaimDraft(
                    claim_type=ClaimType.REAL_TIME,
                    financial_account_id=self.account_id,
                    source_artifact_id=self.artifact_id,
                    extraction_id=self.extraction_id,
                    raw_description=description,
                    authorized_amount=Money.parse(amount, currency),
                    occurrence_at=occurred_at,
                )
            )
            .id
        )

    def statement(
        self,
        *,
        amount: str,
        currency: str = "SGD",
        provider_date: date = date(2026, 1, 10),
        posting_date: date | None = None,
        description: str = "SYNTHETIC COFFEE POSTED",
        kind: str = "expense",
    ) -> UUID:
        return (
            ClaimBook(self.database)
            .record(
                ClaimDraft(
                    claim_type=ClaimType.STATEMENT,
                    financial_account_id=self.account_id,
                    source_artifact_id=self.artifact_id,
                    extraction_id=self.extraction_id,
                    raw_description=description,
                    posted_amount=Money.parse(amount, currency),
                    provider_transaction_date=provider_date,
                    posting_date=posting_date or provider_date,
                    transaction_kind_hint=kind,
                )
            )
            .id
        )

    def extend_statement_history(self, period_end: date) -> None:
        with self.database.transaction() as session:
            session.add(
                Extraction(
                    id=uuid7(),
                    artifact_id=self.artifact_id,
                    financial_account_id=self.account_id,
                    adapter_key="synthetic-reconciliation",
                    parser_version=f"history-{period_end.isoformat()}",
                    status="accepted",
                    period_end=period_end,
                    accepted_at=datetime(2026, 2, 1, tzinfo=UTC),
                )
            )


@pytest.fixture
def evidence(database: Database) -> ReconciliationEvidence:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-reconciliation-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Reconciliation Card",
                default_currency="SGD",
            )
        )
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256="d" * 64,
                size=128,
                media_type="application/pdf",
                content_path="sha256/dd/" + "d" * 64,
                captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(
            Extraction(
                id=extraction_id,
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key="synthetic-reconciliation",
                parser_version="claims-v1",
                status="accepted",
                period_end=date(2026, 1, 11),
                accepted_at=datetime(2026, 1, 11, tzinfo=UTC),
            )
        )
    return ReconciliationEvidence(database, account_id, artifact_id, extraction_id)


@pytest.mark.integration
def test_exact_sgd_evidence_confirms_atomically_and_is_idempotent(
    database: Database,
    evidence: ReconciliationEvidence,
) -> None:
    real_time_id = evidence.real_time(amount="-12.34")
    statement_id = evidence.statement(amount="-12.34")

    barrier = Barrier(2)

    def run_reconciliation() -> ReconciliationRun:
        barrier.wait()
        return Reconciliation(database).reconcile_account(evidence.account_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(run_reconciliation) for _ in range(2))
        runs = tuple(future.result() for future in futures)
    first = next(run for run in runs if run.confirmations)
    repeated = Reconciliation(database).reconcile_account(evidence.account_id)

    assert len(first.confirmations) == 1
    confirmation = first.confirmations[0]
    assert confirmation.source == "automatic"
    assert confirmation.real_time_claim_id == real_time_id
    assert confirmation.statement_claim_id == statement_id
    assert first.candidates[0].reasons == (
        "same_financial_account",
        "amount_exact_posted",
        "activity_date_exact",
        "counterparty_exact",
    )
    assert repeated.confirmations == ()
    assert ClaimBook(database).current_disposition(real_time_id) is ClaimDisposition.CONFIRMED
    assert ClaimBook(database).current_disposition(statement_id) is ClaimDisposition.CONFIRMED
    assert FinancialHistory(database).audit(confirmation.transaction_id).journals[0].is_balanced
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(ReconciledClaimPair)) == 1


@pytest.mark.integration
def test_plausible_fx_uses_a_reference_rate_but_missing_reference_is_statement_only(
    database: Database,
    evidence: ReconciliationEvidence,
) -> None:
    real_time_id = evidence.real_time(amount="-10.00", currency="USD")
    statement_id = evidence.statement(amount="-13.50", currency="SGD")
    with database.transaction() as session:
        session.add(
            ReferenceExchangeRate(
                id=uuid7(),
                rate_date=date(2026, 1, 10),
                base_currency="USD",
                quote_currency="SGD",
                rate=Money.parse("1.35", "SGD").amount,
                source_name="synthetic-official-rate",
            )
        )

    fx_run = Reconciliation(database).reconcile_account(evidence.account_id)

    assert fx_run.confirmations[0].source == "automatic"
    assert fx_run.confirmations[0].real_time_claim_id == real_time_id
    assert fx_run.confirmations[0].statement_claim_id == statement_id
    assert "amount_fx_within_reference_band" in fx_run.candidates[0].reasons

    unmatched_real_time = evidence.real_time(
        amount="-20.00",
        currency="EUR",
        description="SYNTHETIC BOOKS",
    )
    unmatched_statement = evidence.statement(
        amount="-29.00",
        currency="SGD",
        description="SYNTHETIC BOOKS POSTED",
    )
    missing_rate_run = Reconciliation(database).reconcile_account(evidence.account_id)

    assert [item.statement_claim_id for item in missing_rate_run.confirmations] == [
        unmatched_statement
    ]
    assert missing_rate_run.confirmations[0].source == "statement_only"
    assert unmatched_real_time in missing_rate_run.no_match_real_time_claim_ids


@pytest.mark.integration
def test_reconcile_carries_claim_category_onto_posted_amount(
    database: Database,
    evidence: ReconciliationEvidence,
) -> None:
    gifts = CategoryCatalog(database).create("Gifts")
    real_time_id = evidence.real_time(amount="-10.00", currency="USD")
    evidence.statement(amount="-13.50", currency="SGD")
    with database.transaction() as session:
        session.add(
            ReferenceExchangeRate(
                id=uuid7(),
                rate_date=date(2026, 1, 10),
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.35"),
                source_name="synthetic-official-rate",
            )
        )
        session.add(
            ClaimCategory(
                id=uuid7(),
                claim_id=real_time_id,
                category_id=gifts.id,
                amount=Decimal("10.00"),
                currency="USD",
            )
        )

    run = Reconciliation(database).reconcile_account(evidence.account_id)
    current = FinancialHistory(database).get(run.confirmations[0].transaction_id)

    assert run.confirmations[0].real_time_claim_id == real_time_id
    assert current.category_splits[0].category_id == gifts.id
    assert current.category_splits[0].amount == Money.parse("13.50", "SGD")


@pytest.mark.integration
def test_reconcile_leaves_uncategorized_when_claim_category_is_inactive(
    database: Database,
    evidence: ReconciliationEvidence,
) -> None:
    gifts = CategoryCatalog(database).create("Gifts")
    real_time_id = evidence.real_time(amount="-12.34")
    evidence.statement(amount="-12.34")
    with database.transaction() as session:
        category = session.get(Category, gifts.id)
        assert category is not None
        category.active = False
        session.add(
            ClaimCategory(
                id=uuid7(),
                claim_id=real_time_id,
                category_id=gifts.id,
                amount=Decimal("12.34"),
                currency="SGD",
            )
        )

    run = Reconciliation(database).reconcile_account(evidence.account_id)
    current = FinancialHistory(database).get(run.confirmations[0].transaction_id)

    assert current.category_splits[0].category_name == "Uncategorized"


@pytest.mark.integration
def test_ambiguous_candidates_have_one_review_and_rejections_are_not_reproposed(
    database: Database,
    evidence: ReconciliationEvidence,
) -> None:
    real_time_id = evidence.real_time(amount="-8.00", description="SYNTHETIC TRANSIT")
    first_statement_id = evidence.statement(amount="-8.00", description="SYNTHETIC TRANSIT")
    second_statement_id = evidence.statement(amount="-8.00", description="SYNTHETIC TRANSIT")

    reconciliation = Reconciliation(database)
    ambiguous = reconciliation.reconcile_account(evidence.account_id)

    assert ambiguous.confirmations == ()
    assert len(ambiguous.ambiguous_review_ids) == 1
    review_id = ambiguous.ambiguous_review_ids[0]
    with database.transaction() as session:
        review = session.get(PendingReview, review_id)
        assert review is not None
        assert review.subject_id == real_time_id
        assert review.status == PendingReviewStatus.PENDING.value
        assert review.context["candidate_count"] == 2
        assert {entry["statement_claim_id"] for entry in review.context["candidates"]} == {
            str(first_statement_id),
            str(second_statement_id),
        }
        review_version = review.version

    decision = reconciliation.decide(
        ReviewDecision(
            review_id=review_id,
            expected_version=review_version,
            choice="reject_all",
        )
    )

    assert decision.review.status is PendingReviewStatus.RESOLVED
    assert len(decision.follow_up.confirmations) == 2
    assert all(item.source == "statement_only" for item in decision.follow_up.confirmations)
    assert ClaimBook(database).current_disposition(real_time_id) is ClaimDisposition.PROVISIONAL
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(RejectedClaimPair)) == 2
        rejected = session.scalar(select(RejectedClaimPair))
        assert rejected is not None
        rejected_id = rejected.id
    with pytest.raises(IntegrityError, match="append-only"):
        with database.transaction() as session:
            session.execute(delete(RejectedClaimPair).where(RejectedClaimPair.id == rejected_id))

    rerun = reconciliation.reconcile_account(evidence.account_id)
    assert rerun.candidates == ()
    assert rerun.ambiguous_review_ids == ()


@pytest.mark.integration
def test_reviewed_match_confirms_claims_and_records_its_review(
    database: Database,
    evidence: ReconciliationEvidence,
) -> None:
    real_time_id = evidence.real_time(amount="-8.00", description="SYNTHETIC TRANSIT")
    first_statement_id = evidence.statement(amount="-8.00", description="SYNTHETIC TRANSIT")
    evidence.statement(amount="-8.00", description="SYNTHETIC TRANSIT")

    reconciliation = Reconciliation(database)
    ambiguous = reconciliation.reconcile_account(evidence.account_id)
    review_id = ambiguous.ambiguous_review_ids[0]
    with database.transaction() as session:
        review = session.get(PendingReview, review_id)
        assert review is not None
        version = review.version

    decision = reconciliation.decide(
        ReviewDecision(
            review_id=review_id,
            expected_version=version,
            choice=f"match:{first_statement_id}",
        )
    )

    assert decision.confirmation is not None
    assert decision.confirmation.source == "review"
    assert decision.confirmation.real_time_claim_id == real_time_id
    assert decision.review.status is PendingReviewStatus.RESOLVED
    assert ClaimBook(database).current_disposition(real_time_id) is ClaimDisposition.CONFIRMED
    with database.transaction() as session:
        recorded = session.scalar(select(ReconciledClaimPair))
        assert recorded is not None
        assert recorded.decision_source == "review"
        assert recorded.review_id == review_id


@pytest.mark.integration
def test_cutoff_unconfirmed_claim_can_be_confirmed_by_late_statement_evidence(
    database: Database,
    evidence: ReconciliationEvidence,
) -> None:
    occurred_at = datetime(2026, 1, 1, 12, tzinfo=UTC)
    real_time_id = evidence.real_time(
        amount="-5.00",
        occurred_at=occurred_at,
        description="SYNTHETIC LATE MERCHANT",
    )
    cutoff_statement_id = evidence.statement(
        amount="-7.00",
        provider_date=date(2026, 1, 10),
        description="SYNTHETIC OTHER MERCHANT",
    )
    evidence.extend_statement_history(date(2026, 1, 15))

    reconciliation = Reconciliation(database)
    cutoff = reconciliation.reconcile_account(evidence.account_id)

    assert cutoff.confirmations[0].statement_claim_id == cutoff_statement_id
    assert cutoff.confirmations[0].source == "statement_only"
    assert cutoff.unconfirmed_claim_ids == (real_time_id,)
    assert ClaimBook(database).current_disposition(real_time_id) is ClaimDisposition.UNCONFIRMED
    with database.transaction() as session:
        review = session.scalar(
            select(PendingReview).where(
                PendingReview.subject_id == real_time_id,
                PendingReview.condition_code == "real_time_unconfirmed",
            )
        )
        assert review is not None
        assert review.severity == "attention"

    late_statement_id = evidence.statement(
        amount="-5.00",
        provider_date=date(2026, 1, 1),
        posting_date=date(2026, 1, 25),
        description="SYNTHETIC LATE MERCHANT POSTED",
    )
    late = reconciliation.reconcile_account(evidence.account_id)

    assert late.confirmations[0].statement_claim_id == late_statement_id
    assert late.confirmations[0].real_time_claim_id == real_time_id
    assert late.confirmations[0].source == "automatic"
    assert ClaimBook(database).current_disposition(real_time_id) is ClaimDisposition.CONFIRMED
    with database.transaction() as session:
        review = session.scalar(
            select(PendingReview).where(
                PendingReview.subject_id == real_time_id,
                PendingReview.condition_code == "real_time_unconfirmed",
            )
        )
        assert review is not None
        assert review.status == PendingReviewStatus.CANCELLED.value


@pytest.mark.integration
def test_statement_only_claim_establishes_a_transaction_without_a_review(
    database: Database,
    evidence: ReconciliationEvidence,
) -> None:
    statement_id = evidence.statement(amount="5.00", kind="refund")

    outcome = Reconciliation(database).reconcile_account(evidence.account_id)

    assert len(outcome.confirmations) == 1
    assert outcome.confirmations[0].statement_claim_id == statement_id
    assert outcome.confirmations[0].real_time_claim_id is None
    assert outcome.confirmations[0].source == "statement_only"
    assert outcome.ambiguous_review_ids == ()
    assert ClaimBook(database).current_disposition(statement_id) is ClaimDisposition.CONFIRMED
