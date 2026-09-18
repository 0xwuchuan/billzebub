from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from uuid6 import uuid7

from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.financial_history import Confirmation, FinancialHistory, TransactionKind
from billzebub.money import Money
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    CorrectionEvent,
    Extraction,
    FinancialAccount,
    SourceArtifact,
)
from billzebub.reconciliation import Reconciliation
from billzebub.uob_ref_no_backfill import UobRefNoBackfill


def _digest() -> str:
    return (uuid7().hex + uuid7().hex)[:64]


def _statement_account(
    database: Database,
    *,
    slug: str,
    institution: str,
    adapter_key: str,
) -> tuple[UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    digest = _digest()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug=slug,
                institution=institution,
                kind="credit_card",
                display_name=slug,
                default_currency="SGD",
                statement_adapter_key=adapter_key,
            )
        )
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256=digest,
                size=128,
                media_type="application/pdf",
                content_path=f"sha256/{digest[:2]}/{digest}",
                captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(
            Extraction(
                id=extraction_id,
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key=adapter_key,
                parser_version="synthetic-v1",
                status="accepted",
                accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    return account_id, artifact_id, extraction_id


def _confirm_statement(
    database: Database,
    *,
    account_id: UUID,
    artifact_id: UUID,
    extraction_id: UUID,
    description: str,
    counterparty: str,
    day: date = date(2026, 1, 10),
) -> UUID:
    claim = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description=description,
            posted_amount=Money.parse("-10.00", "SGD"),
            provider_transaction_date=day,
            posting_date=day,
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )
    snapshot = FinancialHistory(database).confirm(
        Confirmation(
            statement_claim_id=claim.id,
            kind=TransactionKind.EXPENSE,
            counterparty=counterparty,
        )
    )
    return snapshot.id


@pytest.mark.integration
def test_uob_ref_no_backfill_rewrites_current_counterparty_with_a_correction(
    database: Database,
) -> None:
    uob = _statement_account(
        database, slug="uob-ppv", institution="uob", adapter_key="uob-credit-card"
    )
    dbs = _statement_account(
        database, slug="dbs-primary", institution="dbs", adapter_key="dbs-credit-card"
    )
    dirty_id = _confirm_statement(
        database,
        account_id=uob[0],
        artifact_id=uob[1],
        extraction_id=uob[2],
        description="DIN TAI FUNG-JEWEL CHANGISINGAPORE Ref No. : 12345678",
        counterparty="DIN TAI FUNG-JEWEL CHANGISINGAPORE Ref No. : 12345678",
    )
    clean_id = _confirm_statement(
        database,
        account_id=uob[0],
        artifact_id=uob[1],
        extraction_id=uob[2],
        description="FICTIONAL BOOKSHOP",
        counterparty="FICTIONAL BOOKSHOP",
        day=date(2026, 1, 11),
    )
    empty_id = _confirm_statement(
        database,
        account_id=uob[0],
        artifact_id=uob[1],
        extraction_id=uob[2],
        description="Ref No. : 555",
        counterparty="Ref No. : 555",
        day=date(2026, 1, 12),
    )
    dbs_id = _confirm_statement(
        database,
        account_id=dbs[0],
        artifact_id=dbs[1],
        extraction_id=dbs[2],
        description="DIN TAI FUNG-JEWEL CHANGISINGAPORE Ref No. : 12345678",
        counterparty="DIN TAI FUNG-JEWEL CHANGISINGAPORE Ref No. : 12345678",
    )

    dry = UobRefNoBackfill(database).run(dry_run=True)
    history = FinancialHistory(database)
    assert dry.rewritten_transaction_ids == (dirty_id,)
    assert dry.skipped_empty_transaction_ids == (empty_id,)
    assert history.audit(dirty_id).versions[0].counterparty.endswith("12345678")

    executed = UobRefNoBackfill(database).run(dry_run=False)
    assert executed.rewritten_transaction_ids == (dirty_id,)
    assert executed.skipped_empty_transaction_ids == (empty_id,)

    dirty = history.audit(dirty_id)
    assert dirty.versions[-1].counterparty == "DIN TAI FUNG-JEWEL CHANGISINGAPORE"
    assert dirty.versions[-1].version == 2
    assert dirty.versions[0].counterparty.endswith("12345678")
    with database.transaction() as session:
        reason = session.scalar(
            select(CorrectionEvent.reason).where(CorrectionEvent.transaction_id == dirty_id)
        )
    assert reason == "Strip trailing UOB statement Ref No. from Counterparty"
    assert history.audit(clean_id).versions[-1].version == 1
    assert history.audit(empty_id).versions[-1].counterparty == "Ref No. : 555"
    assert history.audit(dbs_id).versions[-1].counterparty.endswith("12345678")

    repeated = UobRefNoBackfill(database).run(dry_run=False)
    assert repeated.rewritten_transaction_ids == ()
    assert ClaimBook(database).for_extraction(uob[2])[0].raw_description.endswith("12345678")


@pytest.mark.integration
def test_reconciliation_strips_uob_ref_no_when_establishing_counterparty(
    database: Database,
) -> None:
    account_id, artifact_id, extraction_id = _statement_account(
        database, slug="uob-ladys", institution="uob", adapter_key="uob-credit-card"
    )
    claim = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="BUS/MRT RIDE Ref No. : 99887766",
            posted_amount=Money.parse("-3.20", "SGD"),
            provider_transaction_date=date(2026, 1, 10),
            posting_date=date(2026, 1, 10),
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )

    run = Reconciliation(database).reconcile_account(account_id)

    assert len(run.confirmations) == 1
    snapshot = FinancialHistory(database).audit(run.confirmations[0].transaction_id)
    assert snapshot.versions[0].counterparty == "BUS/MRT RIDE"
    assert claim.raw_description == "BUS/MRT RIDE Ref No. : 99887766"
