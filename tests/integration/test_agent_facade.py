import json
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from uuid6 import uuid7

from billzebub.agent_facade import (
    AgentFacade,
    AgentFacadeError,
    CategorizationCommand,
    ProposalCommand,
    ProposalType,
)
from billzebub.api import create_app
from billzebub.categories import CategoryCatalog
from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.config import Settings
from billzebub.money import Money
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    AuditActorKind,
    Extraction,
    FinancialAccount,
    PendingReview,
    SourceArtifact,
)
from billzebub.reconciliation import Reconciliation
from billzebub.tokens import TokenManager, TokenScope


@pytest.fixture
def agent_transaction(database: Database) -> tuple[UUID, UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-agent-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Agent Card",
                default_currency="SGD",
            )
        )
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256="e" * 64,
                size=128,
                media_type="application/pdf",
                content_path="sha256/ee/" + "e" * 64,
                captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        session.flush()
        session.add(
            Extraction(
                id=extraction_id,
                artifact_id=artifact_id,
                financial_account_id=account_id,
                adapter_key="synthetic-agent",
                parser_version="v1",
                status="accepted",
                period_end=date(2026, 1, 31),
                accepted_at=datetime(2026, 2, 1, tzinfo=UTC),
            )
        )

    claim = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="SYNTHETIC AGENT COFFEE POSTED",
            posted_amount=Money.parse("-12.34", "SGD"),
            provider_transaction_date=date(2026, 1, 10),
            posting_date=date(2026, 1, 11),
            transaction_kind_hint="expense",
        )
    )
    outcome = Reconciliation(database).reconcile_account(account_id)
    assert len(outcome.confirmations) == 1
    return account_id, artifact_id, claim.id, outcome.confirmations[0].transaction_id


def _agent_principal(database: Database) -> tuple[str, UUID]:
    issued = TokenManager(database).issue(
        name="Synthetic Agent",
        actor_kind=AuditActorKind.AGENT,
        scopes=frozenset({TokenScope.AGENT_READ, TokenScope.AGENT_CATEGORIZE}),
    )
    principal = TokenManager(database).authenticate(issued.plaintext)
    return f"token:{principal.token_id}", principal.actor_id


@pytest.mark.integration
def test_agent_facade_projects_only_safe_transaction_fields(
    database: Database,
    agent_transaction: tuple[UUID, UUID, UUID, UUID],
) -> None:
    account_id, artifact_id, claim_id, transaction_id = agent_transaction

    facade = AgentFacade(database)
    page = facade.list_transactions()
    transaction = facade.get_transaction(transaction_id)
    body = {"items": [item.to_wire() for item in page.items], "transaction": transaction.to_wire()}
    encoded = json.dumps(body, sort_keys=True)

    assert page.items == (transaction,)
    assert transaction.review_choices == ("categorize",)
    assert facade.list_reviews()[0].transaction_id == transaction_id
    assert str(account_id) not in encoded
    assert str(artifact_id) not in encoded
    assert str(claim_id) not in encoded
    forbidden_keys = {
        "financial_account_id",
        "source_artifact_id",
        "claim_id",
        "raw_description",
        "locator",
        "audit",
    }
    assert forbidden_keys.isdisjoint(key for item in _all_dicts(body) for key in item.keys())


@pytest.mark.integration
def test_agent_categorization_is_versioned_audited_and_idempotent(
    database: Database,
    agent_transaction: tuple[UUID, UUID, UUID, UUID],
) -> None:
    _account_id, _artifact_id, _claim_id, transaction_id = agent_transaction
    category = CategoryCatalog(database).create("Food")
    principal, actor_id = _agent_principal(database)
    facade = AgentFacade(database)
    assert [available.name for available in facade.list_categories()] == ["Food"]
    initial = facade.get_transaction(transaction_id)
    command = CategorizationCommand(
        transaction_id=transaction_id,
        expected_version=initial.version,
        category_id=category.id,
        actor_id=actor_id,
    )

    first = facade.categorize(
        command, principal=principal, idempotency_key="synthetic-categorize-1"
    )
    replay = facade.categorize(
        command, principal=principal, idempotency_key="synthetic-categorize-1"
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert first.body == replay.body
    assert first.body["version"] == 2
    assert first.body["categories"][0]["category"]["id"] == str(category.id)
    assert facade.list_reviews() == ()
    with database.transaction() as session:
        pending = session.scalar(
            select(PendingReview).where(
                PendingReview.subject_id == transaction_id,
                PendingReview.condition_code == "categorization_needed",
                PendingReview.status == "pending",
            )
        )
        assert pending is None

    with pytest.raises(AgentFacadeError, match="idempotency key"):
        facade.categorize(
            CategorizationCommand(
                transaction_id=transaction_id,
                expected_version=2,
                category_id=category.id,
                actor_id=actor_id,
            ),
            principal=principal,
            idempotency_key="synthetic-categorize-1",
        )


@pytest.mark.integration
def test_agent_proposal_creates_an_attention_review_without_changing_facts(
    database: Database,
    agent_transaction: tuple[UUID, UUID, UUID, UUID],
) -> None:
    _account_id, _artifact_id, _claim_id, transaction_id = agent_transaction
    principal, actor_id = _agent_principal(database)
    facade = AgentFacade(database)
    transaction = facade.get_transaction(transaction_id)

    result = facade.propose(
        ProposalCommand(
            transaction_id=transaction_id,
            expected_version=transaction.version,
            proposal_type=ProposalType.CORRECTION,
            summary="Synthetic rationale for owner review",
            actor_id=actor_id,
        ),
        principal=principal,
        idempotency_key="synthetic-proposal-1",
    )

    assert result.replayed is False
    assert result.body == {
        "transaction_id": str(transaction_id),
        "proposal_type": "correction",
        "status": "pending",
    }
    assert facade.get_transaction(transaction_id).version == transaction.version
    with database.transaction() as session:
        review = session.scalar(
            select(PendingReview).where(
                PendingReview.subject_id == transaction_id,
                PendingReview.condition_code == "agent_proposal:correction",
                PendingReview.status == "pending",
            )
        )
        assert review is not None
        assert review.allowed_decisions == ["accept", "reject"]
        assert review.context["expected_transaction_version"] == transaction.version


@pytest.mark.integration
def test_agent_http_resources_use_real_token_scopes_and_safe_projection(
    database: Database,
    tmp_path: Path,
    agent_transaction: tuple[UUID, UUID, UUID, UUID],
) -> None:
    account_id, artifact_id, claim_id, transaction_id = agent_transaction
    category = CategoryCatalog(database).create("Synthetic HTTP Food")
    issued = TokenManager(database).issue(
        name="Synthetic HTTP Agent",
        actor_kind=AuditActorKind.AGENT,
        scopes=frozenset({TokenScope.AGENT_READ, TokenScope.AGENT_CATEGORIZE}),
    )
    app = create_app(Settings(artifact_root=tmp_path), database)
    headers = {"Authorization": f"Bearer {issued.plaintext}"}

    with TestClient(app) as client:
        listed = client.get("/api/v1/agent/transactions", headers=headers)
        detail = client.get(f"/api/v1/agent/transactions/{transaction_id}", headers=headers)
        categorized = client.post(
            f"/api/v1/agent/transactions/{transaction_id}/category",
            headers={
                **headers,
                "Idempotency-Key": "synthetic-http-categorize",
                "If-Match": detail.headers["etag"],
            },
            json={"category_id": str(category.id)},
        )

    assert listed.status_code == 200
    assert categorized.status_code == 200
    assert categorized.json()["categories"][0]["category"]["id"] == str(category.id)
    projection = listed.text + categorized.text
    assert str(account_id) not in projection
    assert str(artifact_id) not in projection
    assert str(claim_id) not in projection


def _all_dicts(value: object) -> tuple[dict[str, object], ...]:
    if isinstance(value, dict):
        nested = tuple(child for item in value.values() for child in _all_dicts(item))
        return (value, *nested)
    if isinstance(value, list):
        return tuple(child for item in value for child in _all_dicts(item))
    return ()
