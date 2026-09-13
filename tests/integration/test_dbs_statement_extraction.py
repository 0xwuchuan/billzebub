from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pymupdf
import pytest
from uuid6 import uuid7

from billzebub.artifact_capture import ArtifactArrivalInput, ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.claims import ClaimBook
from billzebub.persistence.database import Database
from billzebub.persistence.models import FinancialAccount
from billzebub.statement_adapters import configured_statement_adapters
from billzebub.statement_extraction import (
    ExtractionStatus,
    StatementAdapterRegistry,
    StatementExtraction,
)


def _write_dbs_credit_card_statement(path: Path) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "\n".join(
            [
                "DBS",
                "31 Jan 2026",
                "CARD NUMBER 1111 2222 3333 4444",
                "PREVIOUS BALANCE 100.00",
                "DATE DESCRIPTION AMOUNT (S$)",
                "10 Jan FICTIONAL BOOKSHOP 10.00",
                "20 Jan DBS BILL PAYMENT 5.00 CR",
                "25 Jan FICTIONAL MERCHANT REFUND (2.00)",
                "TOTAL: 103.00",
            ]
        ),
        fontname="cour",
        fontsize=10,
    )
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]


@pytest.mark.integration
def test_dbs_credit_card_adapter_passes_strict_atomic_extraction(
    database: Database,
    tmp_path: Path,
) -> None:
    source_pdf = tmp_path / "dbs-credit-card.pdf"
    _write_dbs_credit_card_statement(source_pdf)
    store = ContentAddressedStore(tmp_path / "artifacts")
    artifact = ArtifactCapture(store, database).capture_file(
        source_pdf,
        ArtifactArrivalInput(
            source_type="statement_inbox",
            media_type="application/pdf",
            received_at=datetime(2026, 2, 1, tzinfo=UTC),
            original_name="dbs-credit-card.pdf",
        ),
    )
    account_id: UUID = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="dbs-fictional-card",
                display_name="DBS Fictional Card",
                institution="dbs",
                kind="credit_card",
                default_currency="SGD",
                statement_adapter_key="dbs-credit-card",
                statement_account_identifier="4444",
            )
        )

    outcome = StatementExtraction(
        database,
        store,
        StatementAdapterRegistry(configured_statement_adapters()),
        password_root=tmp_path / "statement-passwords",
    ).extract(artifact_id=artifact.id, financial_account_id=account_id)

    assert outcome.status is ExtractionStatus.ACCEPTED
    assert outcome.claim_count == 3
    claims = ClaimBook(database).for_extraction(outcome.extraction_id)
    assert [claim.posted_amount.to_wire() for claim in claims if claim.posted_amount] == [
        {"amount": "-10.00", "currency": "SGD"},
        {"amount": "5.00", "currency": "SGD"},
        {"amount": "2.00", "currency": "SGD"},
    ]
    assert [claim.transaction_kind_hint for claim in claims] == [
        "expense",
        "transfer",
        "refund",
    ]
    assert all(ClaimBook(database).source_locator(claim.id).text_sha256 for claim in claims)
