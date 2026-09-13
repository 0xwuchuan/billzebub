from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from billzebub.agent_facade import (
    AgentCategory,
    AgentCategoryAllocation,
    AgentMutation,
    AgentReview,
    AgentTransaction,
    AgentTransactionPage,
)
from billzebub.api import create_app
from billzebub.config import Settings
from billzebub.financial_history import TransactionKind
from billzebub.money import Money
from billzebub.tokens import TokenPrincipal, TokenScope


class FakeDatabase:
    def ping(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeAgentFacade:
    def __init__(self) -> None:
        self.transaction_id = uuid4()
        self.category_id = uuid4()
        self.commands: list[object] = []
        category = AgentCategory(id=self.category_id, name="Synthetic Food", parent_id=None)
        self.transaction = AgentTransaction(
            id=self.transaction_id,
            version=3,
            counterparty="Synthetic Coffee",
            amount=Money.parse("-12.34", "SGD"),
            effective_date=date(2026, 1, 10),
            kind=TransactionKind.EXPENSE,
            categories=(
                AgentCategoryAllocation(
                    category=category,
                    amount=Money.parse("12.34", "SGD"),
                ),
            ),
            review_choices=("categorize",),
        )

    def list_transactions(
        self, *, cursor: str | None = None, limit: int = 50
    ) -> AgentTransactionPage:
        assert cursor is None
        assert limit == 50
        return AgentTransactionPage(items=(self.transaction,), next_cursor=None)

    def get_transaction(self, transaction_id: UUID) -> AgentTransaction:
        assert transaction_id == self.transaction_id
        return self.transaction

    def list_categories(self) -> tuple[AgentCategory, ...]:
        return (self.transaction.categories[0].category,)

    def list_reviews(self) -> tuple[AgentReview, ...]:
        return (AgentReview(transaction_id=self.transaction_id, choices=("categorize",)),)

    def categorize(
        self,
        command: object,
        *,
        principal: str,
        idempotency_key: str,
    ) -> AgentMutation:
        self.commands.append(command)
        assert principal == "token:00000000-0000-0000-0000-000000000001"
        assert idempotency_key == "synthetic-key"
        return AgentMutation(body=self.transaction.to_wire(), replayed=False)

    def propose(
        self,
        command: object,
        *,
        principal: str,
        idempotency_key: str,
    ) -> AgentMutation:
        self.commands.append(command)
        assert principal == "token:00000000-0000-0000-0000-000000000001"
        assert idempotency_key == "synthetic-key"
        return AgentMutation(
            body={
                "transaction_id": str(self.transaction_id),
                "proposal_type": "correction",
                "status": "pending",
            },
            replayed=False,
        )


class FakeTokenManager:
    def __init__(self) -> None:
        self.required_scopes: list[frozenset[TokenScope]] = []

    def authenticate(
        self,
        plaintext: str,
        *,
        required_scopes: frozenset[TokenScope] = frozenset(),
    ) -> TokenPrincipal:
        assert plaintext == "synthetic-agent-token"
        self.required_scopes.append(required_scopes)
        return TokenPrincipal(
            token_id=UUID("00000000-0000-0000-0000-000000000001"),
            actor_id=uuid4(),
            scopes=frozenset(TokenScope),
        )


def test_agent_resources_are_scoped_versioned_and_exclude_forbidden_fields(tmp_path: Path) -> None:
    facade = FakeAgentFacade()
    tokens = FakeTokenManager()
    app = create_app(
        Settings(artifact_root=tmp_path),
        FakeDatabase(),
        agent_facade=facade,
        token_manager=tokens,
    )
    headers = {"Authorization": "Bearer synthetic-agent-token"}

    with TestClient(app) as client:
        unauthenticated = client.get("/api/v1/agent/transactions")
        listed = client.get("/api/v1/agent/transactions", headers=headers)
        detail = client.get(f"/api/v1/agent/transactions/{facade.transaction_id}", headers=headers)
        categorized = client.post(
            f"/api/v1/agent/transactions/{facade.transaction_id}/category",
            headers={
                **headers,
                "Idempotency-Key": "synthetic-key",
                "If-Match": detail.headers["etag"],
            },
            json={"category_id": str(facade.category_id)},
        )

    assert unauthenticated.status_code == 401
    assert listed.status_code == 200
    assert detail.status_code == 200
    assert detail.headers["etag"] == f'"transaction:{facade.transaction_id}:v3"'
    assert categorized.status_code == 200
    assert categorized.headers["etag"] == detail.headers["etag"]
    assert tokens.required_scopes == [
        frozenset({TokenScope.AGENT_READ}),
        frozenset({TokenScope.AGENT_READ}),
        frozenset({TokenScope.AGENT_CATEGORIZE}),
    ]
    assert len(facade.commands) == 1
    forbidden = {
        "financial_account_id",
        "source_artifact_id",
        "claim_id",
        "raw_description",
        "audit",
    }
    assert forbidden.isdisjoint(_keys(listed.json()))


def test_agent_openapi_documents_only_safe_projected_resources(tmp_path: Path) -> None:
    app = create_app(
        Settings(artifact_root=tmp_path),
        FakeDatabase(),
        agent_facade=FakeAgentFacade(),
        token_manager=FakeTokenManager(),
    )

    document = app.openapi()

    assert document["info"] == {"title": "Billzebub", "version": "1.0.0"}
    assert "/api/v1/agent/transactions" in document["paths"]
    assert "AgentTransactionWire" in document["components"]["schemas"]
    assert {
        "financial_account_id",
        "source_artifact_id",
        "claim_id",
        "raw_description",
        "audit",
    }.isdisjoint(_keys(document["components"]["schemas"]))


def test_agent_mutations_require_idempotency_and_current_etag(tmp_path: Path) -> None:
    facade = FakeAgentFacade()
    app = create_app(
        Settings(artifact_root=tmp_path),
        FakeDatabase(),
        agent_facade=facade,
        token_manager=FakeTokenManager(),
    )
    headers = {"Authorization": "Bearer synthetic-agent-token"}

    with TestClient(app) as client:
        missing_key = client.post(
            f"/api/v1/agent/transactions/{facade.transaction_id}/category",
            headers={**headers, "If-Match": f'"transaction:{facade.transaction_id}:v3"'},
            json={"category_id": str(facade.category_id)},
        )
        missing_etag = client.post(
            f"/api/v1/agent/transactions/{facade.transaction_id}/proposals",
            headers={**headers, "Idempotency-Key": "synthetic-key"},
            json={"proposal_type": "correction", "summary": "Synthetic proposal"},
        )

    assert missing_key.status_code == 400
    assert missing_key.json()["detail"] == "idempotency_key_required"
    assert missing_etag.status_code == 428
    assert missing_etag.json()["detail"] == "resource_version_required"


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value)) if value else set()
    return set()
