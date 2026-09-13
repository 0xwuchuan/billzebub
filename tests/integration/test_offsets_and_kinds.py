from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from uuid6 import uuid7

from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.financial_history import (
    Confirmation,
    Correction,
    FinancialHistory,
    FinancialHistoryError,
    OffsetAllocationCommand,
    TransactionKind,
    TransactionSnapshot,
)
from billzebub.money import Money
from billzebub.persistence.database import Database
from billzebub.persistence.models import Extraction, FinancialAccount, SourceArtifact


@pytest.fixture
def statement_evidence(database: Database) -> tuple[UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-card-offsets",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Card",
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
                parser_version="synthetic-v1",
                status="accepted",
                accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    return account_id, artifact_id, extraction_id


def confirm_synthetic(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    *,
    amount: str,
    kind: TransactionKind,
    description: str,
) -> TransactionSnapshot:
    account_id, artifact_id, extraction_id = evidence
    claim = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description=description,
            posted_amount=Money.parse(amount, "SGD"),
            provider_transaction_date=date(2026, 2, 1),
            posting_date=date(2026, 2, 2),
        )
    )
    return FinancialHistory(database).confirm(
        Confirmation(
            statement_claim_id=claim.id,
            kind=kind,
            counterparty=description.title(),
        )
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("amount", "kind"),
    [
        ("90.00", TransactionKind.INCOME),
        ("50.00", TransactionKind.TRANSFER),
        ("-40.00", TransactionKind.TRANSFER),
        ("20.00", TransactionKind.REFUND),
        ("30.00", TransactionKind.REIMBURSEMENT),
        ("-80.00", TransactionKind.CASH_WITHDRAWAL),
    ],
)
def test_every_transaction_kind_produces_one_balanced_journal(
    database: Database,
    statement_evidence: tuple[UUID, UUID, UUID],
    amount: str,
    kind: TransactionKind,
) -> None:
    transaction = confirm_synthetic(
        database,
        statement_evidence,
        amount=amount,
        kind=kind,
        description=f"SYNTHETIC {kind.value}",
    )

    audit = FinancialHistory(database).audit(transaction.id)
    assert transaction.effective_date == date(2026, 2, 1)
    assert len(audit.journals) == 1
    assert audit.journals[0].is_balanced
    if kind is TransactionKind.CASH_WITHDRAWAL:
        assert transaction.category_splits[0].category_name == "Uncategorized"
    else:
        assert transaction.category_splits == ()


@pytest.mark.integration
def test_offsets_may_link_partially_and_multiply_but_never_overallocate(
    database: Database,
    statement_evidence: tuple[UUID, UUID, UUID],
) -> None:
    expense_one = confirm_synthetic(
        database,
        statement_evidence,
        amount="-100.00",
        kind=TransactionKind.EXPENSE,
        description="SYNTHETIC EXPENSE ONE",
    )
    expense_two = confirm_synthetic(
        database,
        statement_evidence,
        amount="-50.00",
        kind=TransactionKind.EXPENSE,
        description="SYNTHETIC EXPENSE TWO",
    )
    refund = confirm_synthetic(
        database,
        statement_evidence,
        amount="30.00",
        kind=TransactionKind.REFUND,
        description="SYNTHETIC REFUND",
    )
    reimbursement = confirm_synthetic(
        database,
        statement_evidence,
        amount="120.00",
        kind=TransactionKind.REIMBURSEMENT,
        description="SYNTHETIC REIMBURSEMENT",
    )
    history = FinancialHistory(database)

    history.allocate_offset(
        OffsetAllocationCommand(refund.id, expense_one.id, Money.parse("30.00", "SGD"))
    )
    history.allocate_offset(
        OffsetAllocationCommand(
            reimbursement.id,
            expense_one.id,
            Money.parse("70.00", "SGD"),
        )
    )
    history.allocate_offset(
        OffsetAllocationCommand(
            reimbursement.id,
            expense_two.id,
            Money.parse("50.00", "SGD"),
        )
    )

    with pytest.raises(FinancialHistoryError, match="Offset Allocation"):
        history.allocate_offset(
            OffsetAllocationCommand(
                reimbursement.id,
                expense_two.id,
                Money.parse("0.01", "SGD"),
            )
        )

    refund_audit = history.audit(refund.id)
    reimbursement_audit = history.audit(reimbursement.id)
    assert [journal.journal_type for journal in refund_audit.journals] == [
        "confirmation",
        "offset_allocation",
    ]
    assert [journal.journal_type for journal in reimbursement_audit.journals] == [
        "confirmation",
        "offset_allocation",
        "offset_allocation",
    ]
    assert all(journal.is_balanced for journal in refund_audit.journals)
    assert all(journal.is_balanced for journal in reimbursement_audit.journals)

    with pytest.raises(FinancialHistoryError, match="overallocate the offset"):
        history.correct(
            Correction(
                transaction_id=reimbursement.id,
                reason="Synthetic invalid reduction",
                posted_amount=Money.parse("119.99", "SGD"),
            )
        )
    with pytest.raises(FinancialHistoryError, match="overallocate the Expense"):
        history.correct(
            Correction(
                transaction_id=expense_one.id,
                reason="Synthetic invalid reduction",
                posted_amount=Money.parse("-99.99", "SGD"),
            )
        )
