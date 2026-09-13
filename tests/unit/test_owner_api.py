from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from billzebub.api import create_app
from billzebub.config import Settings
from billzebub.financial_history import CategorySplitRecord, TransactionKind
from billzebub.identity import OwnerIdentity
from billzebub.money import Money
from billzebub.owner_workspace import (
    OwnerReview,
    OwnerReviewPage,
    OwnerReviewSummary,
    OwnerTransaction,
    OwnerTransactionPage,
)
from billzebub.reviews import PendingReviewStatus, ReviewDecision, ReviewSeverity


class FakeDatabase:
    def ping(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeOwnerActors:
    def __init__(self) -> None:
        self.actor_id = uuid4()
        self.identities: list[OwnerIdentity] = []

    def resolve(self, identity: OwnerIdentity) -> UUID:
        self.identities.append(identity)
        return self.actor_id


class FakeReviewActions:
    def __init__(self, review: OwnerReview) -> None:
        self.review = review
        self.commands: list[ReviewDecision] = []

    def decide(self, command: ReviewDecision) -> OwnerReview:
        self.commands.append(command)
        assert command.review_id == self.review.id
        return replace(
            self.review,
            status=PendingReviewStatus.RESOLVED,
            version=self.review.version + 1,
        )


class FakeOwnerWorkspace:
    def __init__(self) -> None:
        self.account_id = uuid4()
        self.transaction_id = uuid4()
        self.review_id = uuid4()
        self.transaction = OwnerTransaction(
            id=self.transaction_id,
            version=2,
            financial_account_id=self.account_id,
            financial_account_name="Synthetic Owner Card",
            counterparty="Synthetic Coffee",
            posted_amount=Money.parse("-12.34", "SGD"),
            authorized_amount=None,
            effective_date="2026-01-10",
            kind=TransactionKind.EXPENSE,
            category_splits=(
                CategorySplitRecord(
                    category_id=uuid4(),
                    category_name="Synthetic Food",
                    amount=Money.parse("12.34", "SGD"),
                ),
            ),
            reviews=(
                OwnerReviewSummary(
                    id=self.review_id,
                    condition_code="categorization_needed",
                    severity=ReviewSeverity.ATTENTION,
                    version=1,
                    allowed_decisions=("categorize",),
                ),
            ),
        )
        self.review = OwnerReview(
            id=self.review_id,
            subject_type="transaction",
            subject_id=self.transaction_id,
            condition_code="categorization_needed",
            severity=ReviewSeverity.ATTENTION,
            status=PendingReviewStatus.PENDING,
            version=1,
            allowed_decisions=("categorize",),
            context={},
            created_at=datetime(2026, 1, 10, tzinfo=UTC),
            updated_at=datetime(2026, 1, 10, tzinfo=UTC),
        )

    def list_transactions(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        financial_account_id: UUID | None = None,
        kind: TransactionKind | None = None,
        needs_review: bool | None = None,
    ) -> OwnerTransactionPage:
        assert cursor is None
        assert limit == 50
        assert financial_account_id is None
        assert kind is None
        assert needs_review is None
        return OwnerTransactionPage(items=(self.transaction,), next_cursor=None)

    def get_transaction(self, transaction_id: UUID) -> OwnerTransaction:
        assert transaction_id == self.transaction_id
        return self.transaction

    def list_reviews(
        self,
        *,
        cursor: str | None = None,
        limit: int = 50,
        review_status: PendingReviewStatus = PendingReviewStatus.PENDING,
    ) -> OwnerReviewPage:
        assert cursor is None
        assert limit == 50
        assert review_status is PendingReviewStatus.PENDING
        return OwnerReviewPage(items=(self.review,), next_cursor=None)

    def get_review(self, review_id: UUID) -> OwnerReview:
        assert review_id == self.review_id
        return self.review


def test_owner_transaction_and_review_resources_use_owner_identity_and_etags(
    tmp_path: Path,
) -> None:
    workspace = FakeOwnerWorkspace()
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="developer@example.test"),
        FakeDatabase(),
        owner_workspace=workspace,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        transactions = client.get("/api/v1/transactions")
        transaction = client.get(f"/api/v1/transactions/{workspace.transaction_id}")
        reviews = client.get("/api/v1/reviews")
        review = client.get(f"/api/v1/reviews/{workspace.review_id}")

    assert transactions.status_code == 200
    assert transaction.status_code == 200
    assert reviews.status_code == 200
    assert review.status_code == 200
    assert transaction.headers["etag"] == f'"transaction:{workspace.transaction_id}:v2"'
    assert review.headers["etag"] == f'"review:{workspace.review_id}:v1"'
    assert transactions.json()["items"][0]["financial_account"] == {
        "id": str(workspace.account_id),
        "name": "Synthetic Owner Card",
    }
    assert reviews.json()["items"][0]["allowed_decisions"] == ["categorize"]


def test_owner_review_decision_requires_browser_protection_and_current_etag(tmp_path: Path) -> None:
    workspace = FakeOwnerWorkspace()
    actors = FakeOwnerActors()
    actions = FakeReviewActions(workspace.review)
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="developer@example.test"),
        FakeDatabase(),
        owner_actors=actors,
        review_actions=actions,
        owner_workspace=workspace,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        review = client.get(f"/api/v1/reviews/{workspace.review_id}")
        blocked = client.post(
            f"/api/v1/reviews/{workspace.review_id}/decisions",
            headers={"If-Match": review.headers["etag"]},
            json={"choice": "categorize"},
        )
        decided = client.post(
            f"/api/v1/reviews/{workspace.review_id}/decisions",
            headers={
                "Origin": "http://testserver",
                "X-Billzebub-CSRF": "bzb-spa",
                "If-Match": review.headers["etag"],
            },
            json={"choice": "categorize"},
        )

    assert blocked.status_code == 403
    assert decided.status_code == 200
    assert decided.headers["etag"] == f'"review:{workspace.review_id}:v2"'
    assert decided.json()["status"] == "resolved"
    assert actions.commands[0].expected_version == 1
    assert actions.commands[0].actor_id == actors.actor_id
    assert actors.identities[0].login == "developer@example.test"


def test_owner_workspace_resources_fail_closed_without_owner_identity(tmp_path: Path) -> None:
    app = create_app(
        Settings(artifact_root=tmp_path),
        FakeDatabase(),
        owner_workspace=FakeOwnerWorkspace(),
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/v1/transactions")

    assert response.status_code == 401
    assert response.json()["detail"] == "owner_identity_required"
