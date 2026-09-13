from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.categories import CategoryCatalog
from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.config import Settings
from billzebub.financial_history import Confirmation, FinancialHistory, TransactionKind
from billzebub.money import Money
from billzebub.owner_workspace import OwnerWorkspace, OwnerWorkspaceError
from billzebub.persistence.database import Database
from billzebub.persistence.models import Extraction, FinancialAccount, SourceArtifact
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
