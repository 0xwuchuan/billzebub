import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.apple_wallet import AppleWalletCaptureStatus, AppleWalletIngestion
from billzebub.artifact_capture import ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.categories import CategoryCatalog
from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.config import Settings
from billzebub.financial_account_aliases import FinancialAccountAliases
from billzebub.financial_history import Confirmation, FinancialHistory, TransactionKind
from billzebub.money import Money
from billzebub.owner_workspace import OwnerWorkspace, OwnerWorkspaceError
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    Extraction,
    FinancialAccount,
    FinancialAccountKind,
    SourceArtifact,
)
from billzebub.reviews import ReviewCondition, ReviewInbox, ReviewSeverity


@pytest.fixture
def workspace_transactions(database: Database) -> tuple[UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-owner-workspace-card",
                display_name="Synthetic Owner Workspace Card",
                institution="synthetic",
                kind="credit_card",
                default_currency="SGD",
            )
        )
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256="f" * 64,
                size=128,
                media_type="application/pdf",
                content_path="sha256/ff/" + "f" * 64,
                captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(
            Extraction(
                id=extraction_id,
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key="synthetic-owner-workspace",
                parser_version="v1",
                status="accepted",
                period_end=date(2026, 1, 31),
                accepted_at=datetime(2026, 2, 1, tzinfo=UTC),
            )
        )

    claims = ClaimBook(database)
    history = FinancialHistory(database)
    transactions: list[UUID] = []
    for day, amount, counterparty in (
        (date(2026, 1, 10), "-12.34", "Synthetic Older Coffee"),
        (date(2026, 1, 11), "-45.67", "Synthetic Newer Groceries"),
    ):
        statement = claims.record(
            ClaimDraft(
                claim_type=ClaimType.STATEMENT,
                financial_account_id=account_id,
                source_artifact_id=artifact_id,
                extraction_id=extraction_id,
                raw_description=f"{counterparty} posted",
                posted_amount=Money.parse(amount, "SGD"),
                provider_transaction_date=day,
                posting_date=day,
                transaction_kind_hint=TransactionKind.EXPENSE.value,
            )
        )
        transactions.append(
            history.confirm(
                Confirmation(
                    statement_claim_id=statement.id,
                    kind=TransactionKind.EXPENSE,
                    counterparty=counterparty,
                )
            ).id
        )
    return account_id, transactions[0], transactions[1]


@pytest.mark.integration
def test_owner_workspace_projects_current_transactions_and_review_queue(
    database: Database,
    workspace_transactions: tuple[UUID, UUID, UUID],
) -> None:
    account_id, older_id, newer_id = workspace_transactions
    workspace = OwnerWorkspace(database)

    first_page = workspace.list_transactions(
        limit=1,
        financial_account_id=account_id,
        needs_review=True,
    )
    second_page = workspace.list_transactions(
        limit=1,
        financial_account_id=account_id,
        cursor=first_page.next_cursor,
    )
    review_page = workspace.list_reviews(limit=10)

    assert first_page.items[0].id == newer_id
    assert first_page.items[0].financial_account_id == account_id
    assert first_page.items[0].posted_amount == Money.parse("-45.67", "SGD")
    assert first_page.items[0].category_splits[0].category_name == "Uncategorized"
    assert first_page.items[0].reviews[0].condition_code == "categorization_needed"
    assert first_page.next_cursor is not None
    assert second_page.items[0].id == older_id
    assert second_page.next_cursor is None
    assert {review.subject_id for review in review_page.items} == {older_id, newer_id}
    assert all(review.condition_code == "categorization_needed" for review in review_page.items)
    assert workspace.get_transaction(older_id).counterparty == "Synthetic Older Coffee"


@pytest.mark.integration
def test_owner_http_categorizes_a_transaction_with_an_audit_actor(
    database: Database,
    tmp_path: Path,
    workspace_transactions: tuple[UUID, UUID, UUID],
) -> None:
    _account_id, transaction_id, _newer_id = workspace_transactions
    category = CategoryCatalog(database).create("Synthetic Owner Food")
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        detail = client.get(f"/api/v1/transactions/{transaction_id}")
        categorized = client.put(
            f"/api/v1/transactions/{transaction_id}/category",
            headers={
                "Origin": "http://testserver",
                "X-Billzebub-CSRF": "bzb-spa",
                "If-Match": detail.headers["etag"],
            },
            json={"category_id": str(category.id)},
        )

    assert detail.status_code == 200
    assert categorized.status_code == 200
    assert categorized.json()["version"] == 2
    assert categorized.json()["category_splits"] == [
        {
            "id": str(category.id),
            "name": "Synthetic Owner Food",
            "amount": {"amount": "12.34", "currency": "SGD"},
        }
    ]
    assert categorized.json()["reviews"] == []


@pytest.mark.integration
def test_owner_http_decides_a_proposal_with_owner_identity(
    database: Database,
    tmp_path: Path,
    workspace_transactions: tuple[UUID, UUID, UUID],
) -> None:
    _account_id, transaction_id, _newer_id = workspace_transactions
    review = ReviewInbox(database).synchronize(
        ReviewCondition(
            subject_type="transaction",
            subject_id=transaction_id,
            condition_code="agent_proposal:correction",
            severity=ReviewSeverity.ATTENTION,
            allowed_decisions=("accept", "reject"),
            context={"proposal_type": "correction", "summary": "Synthetic proposal"},
        ),
        active=True,
    )
    assert review is not None
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        detail = client.get(f"/api/v1/reviews/{review.id}")
        decided = client.post(
            f"/api/v1/reviews/{review.id}/decisions",
            headers={
                "Origin": "http://testserver",
                "X-Billzebub-CSRF": "bzb-spa",
                "If-Match": detail.headers["etag"],
            },
            json={"choice": "accept"},
        )

    assert detail.status_code == 200
    assert decided.status_code == 200
    assert decided.json()["status"] == "resolved"
    assert decided.headers["etag"] == f'"review:{review.id}:v2"'


@pytest.mark.integration
def test_owner_workspace_rejects_invalid_cursors(
    database: Database,
    workspace_transactions: tuple[UUID, UUID, UUID],
) -> None:
    workspace = OwnerWorkspace(database)

    with pytest.raises(OwnerWorkspaceError, match="cursor"):
        workspace.list_transactions(cursor="not-a-cursor")
    with pytest.raises(OwnerWorkspaceError, match="cursor"):
        workspace.list_reviews(cursor="not-a-cursor")


def _realtime_wallet_body() -> bytes:
    return json.dumps(
        {
            "schema_version": "realtime-1",
            "source": "apple_wallet",
            "name": "Synthetic name",
            "merchant": "Synthetic merchant",
            "instrument": "Synthetic Wallet Card",
            "amount": "$12.34",
            "date": "7 Mar 2026 at 9:05 PM",
        },
        separators=(",", ":"),
    ).encode()


def _realtime_paylah_body() -> bytes:
    return json.dumps(
        {
            "schema_version": "realtime-1",
            "source": "paylah",
            "name": "Synthetic PayLah name",
            "amount": "$8.50",
            "date": "7 Mar 2026 at 9:05 PM",
        },
        separators=(",", ":"),
    ).encode()


def _add_account(
    database: Database,
    *,
    slug: str,
    display_name: str,
    kind: FinancialAccountKind,
) -> UUID:
    account_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug=slug,
                display_name=display_name,
                institution="synthetic",
                kind=kind,
                default_currency="SGD",
            )
        )
    return account_id


def _statement_extraction(database: Database, account_id: UUID) -> tuple[UUID, UUID]:
    artifact_id = uuid7()
    extraction_id = uuid7()
    digest = (artifact_id.hex + artifact_id.hex)[:64]
    with database.transaction() as session:
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256=digest,
                size=64,
                media_type="application/pdf",
                content_path=f"sha256/{digest[:2]}/{digest}",
                captured_at=datetime(2026, 3, 31, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(
            Extraction(
                id=extraction_id,
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key="synthetic-owner-statement",
                parser_version=f"v1-{extraction_id.hex}",
                status="accepted",
                period_end=date(2026, 3, 31),
                accepted_at=datetime(2026, 4, 1, tzinfo=UTC),
            )
        )
    return artifact_id, extraction_id


@pytest.mark.integration
def test_owner_workspace_projects_realtime_claims_until_statement_confirmation(
    database: Database,
    tmp_path: Path,
) -> None:
    card_id = _add_account(
        database,
        slug="synthetic-owner-wallet-card",
        display_name="Synthetic Owner Wallet Card",
        kind=FinancialAccountKind.CREDIT_CARD,
    )
    paylah_id = _add_account(
        database,
        slug="synthetic-owner-paylah",
        display_name="Synthetic Owner PayLah",
        kind=FinancialAccountKind.PAYLAH,
    )
    aliases = FinancialAccountAliases(database)
    aliases.add_apple_wallet_card(
        account_slug="synthetic-owner-wallet-card",
        card_label="Synthetic Wallet Card",
    )
    ingestion = AppleWalletIngestion(
        database,
        ArtifactCapture(ContentAddressedStore(tmp_path), database),
        aliases,
        timezone=ZoneInfo("Asia/Singapore"),
    )

    wallet = ingestion.ingest(_realtime_wallet_body(), received_at=datetime.now(UTC), actor_id=None)
    paylah = ingestion.ingest(_realtime_paylah_body(), received_at=datetime.now(UTC), actor_id=None)
    assert wallet.status is AppleWalletCaptureStatus.ACCEPTED
    assert paylah.status is AppleWalletCaptureStatus.ACCEPTED

    transfer_artifact_id, transfer_extraction_id = _statement_extraction(database, card_id)
    ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=card_id,
            source_artifact_id=transfer_artifact_id,
            extraction_id=transfer_extraction_id,
            raw_description="Synthetic PayLah funding",
            authorized_amount=Money.parse("-20.00", "SGD"),
            occurrence_at=datetime(2026, 3, 7, 8, tzinfo=UTC),
            transaction_kind_hint=TransactionKind.TRANSFER.value,
        )
    )

    workspace = OwnerWorkspace(database)
    page = workspace.list_transactions(limit=20)
    by_counterparty = {item.counterparty: item for item in page.items}

    wallet_item = by_counterparty["Synthetic merchant — Synthetic name"]
    paylah_item = by_counterparty["Synthetic PayLah name"]
    transfer_item = by_counterparty["Synthetic PayLah funding"]

    assert wallet_item.financial_account_id == card_id
    assert wallet_item.posted_amount == Money.parse("0", "SGD")
    assert wallet_item.authorized_amount == Money.parse("-12.34", "SGD")
    assert wallet_item.effective_date == "2026-03-07"
    assert wallet_item.kind is TransactionKind.EXPENSE
    assert paylah_item.financial_account_id == paylah_id
    assert paylah_item.authorized_amount == Money.parse("-8.50", "SGD")
    assert paylah_item.posted_amount == Money.parse("0", "SGD")
    assert transfer_item.kind is TransactionKind.TRANSFER
    assert workspace.get_transaction(wallet_item.id).id == wallet_item.id

    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        listed = client.get("/api/v1/transactions")
    assert listed.status_code == 200
    payload = listed.json()
    assert "schema_version" not in listed.text
    assert "$12.34" not in listed.text
    wire_by_id = {item["id"]: item for item in payload["items"]}
    assert wire_by_id[str(wallet_item.id)]["authorized_amount"] == {
        "amount": "-12.34",
        "currency": "SGD",
    }
    assert wire_by_id[str(wallet_item.id)]["posted_amount"] == {"amount": "0", "currency": "SGD"}
    assert wire_by_id[str(paylah_item.id)]["kind"] == "expense"
    assert wire_by_id[str(transfer_item.id)]["kind"] == "transfer"

    artifact_id, extraction_id = _statement_extraction(database, card_id)
    statement = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=card_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="SYNTHETIC MERCHANT POSTED",
            posted_amount=Money.parse("-12.34", "SGD"),
            provider_transaction_date=date(2026, 3, 7),
            posting_date=date(2026, 3, 8),
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )
    confirmed = FinancialHistory(database).confirm(
        Confirmation(
            statement_claim_id=statement.id,
            real_time_claim_id=wallet_item.id,
            kind=TransactionKind.EXPENSE,
            counterparty="Synthetic merchant",
        )
    )

    after = workspace.list_transactions(limit=20)
    after_ids = {item.id for item in after.items}
    after_by_counterparty = {item.counterparty: item for item in after.items}
    assert wallet_item.id not in after_ids
    assert confirmed.id in after_ids
    confirmed_item = after_by_counterparty["Synthetic merchant"]
    assert confirmed_item.posted_amount == Money.parse("-12.34", "SGD")
    assert confirmed_item.authorized_amount == Money.parse("-12.34", "SGD")
    assert after_by_counterparty["Synthetic PayLah name"].posted_amount == Money.parse("0", "SGD")
    assert len([item for item in after.items if item.counterparty == "Synthetic merchant"]) == 1
