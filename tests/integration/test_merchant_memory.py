from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.categories import CategoryCatalog
from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.config import Settings
from billzebub.financial_history import Confirmation, FinancialHistory, TransactionKind
from billzebub.identity import OwnerIdentity
from billzebub.jev import JevCategory, JevSubject, Proposal
from billzebub.jev_categorizer import JevCategorizer
from billzebub.jev_eval import eval_threshold_report
from billzebub.merchant_memory import backfill_merchant_memory
from billzebub.money import Money
from billzebub.owner_actors import OwnerActors
from billzebub.owner_transaction_actions import OwnerCategorizationCommand, OwnerTransactionActions
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    CorrectionEvent,
    Extraction,
    FinancialAccount,
    JevCategorizationAttempt,
    MerchantCategoryMemory,
    MerchantMemoryExclusion,
    SourceArtifact,
)


@pytest.fixture
def evidence(database: Database) -> tuple[UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-memory-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Memory Card",
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
                adapter_key="synthetic-memory",
                parser_version="v1",
                status="accepted",
                accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    return account_id, artifact_id, extraction_id


class _RaisingProposer:
    def propose(self, subject: JevSubject, categories: object) -> Proposal:
        raise AssertionError(f"Jev was called for {subject.counterparty}")


class _RecordingProposer:
    def __init__(self) -> None:
        self.subjects: list[JevSubject] = []
        self.categories: tuple[JevCategory, ...] = ()

    def propose(self, subject: JevSubject, categories: Sequence[JevCategory]) -> Proposal:
        self.subjects.append(subject)
        self.categories = tuple(categories)
        return Proposal(
            action="skip",
            category_id=None,
            category_name=None,
            confidence=Decimal("0.1"),
            model="synthetic-jev",
            choice="nope",
            skip_reason="low_confidence",
        )


class _ApplyProposer:
    def __init__(self, category_id: UUID, name: str, confidence: str) -> None:
        self._category_id = category_id
        self._name = name
        self._confidence = Decimal(confidence)

    def propose(self, subject: JevSubject, categories: object) -> Proposal:
        return Proposal(
            action="apply",
            category_id=self._category_id,
            category_name=self._name,
            confidence=self._confidence,
            model="synthetic-jev",
            choice=self._name,
        )


def _confirm(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    *,
    counterparty: str,
    amount: str,
    day: date,
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
            transaction_kind_hint=TransactionKind.EXPENSE.value,
        )
    )
    return (
        FinancialHistory(database)
        .confirm(
            Confirmation(
                statement_claim_id=statement.id,
                kind=TransactionKind.EXPENSE,
                counterparty=counterparty,
            )
        )
        .id
    )


def _owner(database: Database) -> UUID:
    return OwnerActors(database).resolve(
        OwnerIdentity(login="owner@example.test", name="Synthetic Owner")
    )


def _categorize(
    database: Database,
    transaction_id: UUID,
    category_id: UUID,
    version: int = 1,
) -> None:
    OwnerTransactionActions(database).categorize(
        OwnerCategorizationCommand(
            transaction_id=transaction_id,
            expected_version=version,
            category_id=category_id,
            actor_id=_owner(database),
        )
    )


def _rule(database: Database, key: str) -> MerchantCategoryMemory | None:
    with database.transaction() as session:
        return session.scalar(
            select(MerchantCategoryMemory).where(MerchantCategoryMemory.normalized_key == key)
        )


def _attempt_count(database: Database, transaction_id: UUID) -> int:
    with database.transaction() as session:
        rows = session.scalars(
            select(JevCategorizationAttempt.id).where(
                JevCategorizationAttempt.transaction_id == transaction_id
            )
        ).all()
        return len(rows)


@pytest.mark.integration
def test_unambiguous_owner_memory_skips_jev(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    groceries = CategoryCatalog(database).create(
        "Groceries",
        description="Food bought to cook at home",
    )
    taught = _confirm(
        database,
        evidence,
        counterparty="SPOTIFY SG",
        amount="-11.98",
        day=date(2026, 8, 15),
    )
    _categorize(database, taught, groceries.id)
    nxt = _confirm(
        database,
        evidence,
        counterparty="Spotify Pte Ltd",
        amount="-11.98",
        day=date(2026, 9, 15),
    )

    updated = JevCategorizer(database, _RaisingProposer()).categorize_transaction(nxt)

    assert updated is not None
    assert updated.category_splits[0].category_id == groceries.id
    assert _attempt_count(database, nxt) == 0
    with database.transaction() as session:
        reason = session.scalar(
            select(CorrectionEvent.reason)
            .where(CorrectionEvent.transaction_id == nxt)
            .order_by(CorrectionEvent.created_at.desc())
        )
    assert reason == "merchant_memory"
    rule = _rule(database, "spotify")
    assert rule is not None
    assert rule.source == "owner"
    assert rule.category_id == groceries.id


@pytest.mark.integration
def test_ambiguous_owner_memory_falls_through_to_jev(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    groceries = CategoryCatalog(database).create(
        "Groceries",
        description="Food bought to cook at home",
    )
    dining = CategoryCatalog(database).create("Dining")
    first = _confirm(
        database, evidence, counterparty="SPOTIFY SG", amount="-9.00", day=date(2026, 8, 1)
    )
    second = _confirm(
        database,
        evidence,
        counterparty="Spotify Pte Ltd",
        amount="-10.00",
        day=date(2026, 8, 2),
    )
    third = _confirm(
        database, evidence, counterparty="SPOTIFY 1234", amount="-11.00", day=date(2026, 8, 3)
    )
    _categorize(database, first, groceries.id)
    _categorize(database, second, dining.id)
    proposer = _RecordingProposer()

    JevCategorizer(database, proposer).categorize_transaction(third)

    assert _rule(database, "spotify") is None
    assert len(proposer.subjects) == 1
    assert proposer.subjects[0].similar_confirmed_transactions
    labels = {category.name: category.description for category in proposer.categories}
    assert labels["Groceries"] == "Food bought to cook at home"
    assert any(
        item.category == "Groceries" for item in proposer.subjects[0].similar_confirmed_transactions
    )


@pytest.mark.integration
def test_high_confidence_jev_seeds_memory_until_the_owner_corrects_it(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    groceries = CategoryCatalog(database).create("Groceries")
    dining = CategoryCatalog(database).create("Dining")
    first = _confirm(
        database, evidence, counterparty="SPOTIFY SG", amount="-11.98", day=date(2026, 7, 15)
    )
    JevCategorizer(
        database, _ApplyProposer(groceries.id, "Groceries", "0.91")
    ).categorize_transaction(first)
    seeded = _rule(database, "spotify")
    assert seeded is not None
    assert seeded.source == "jev"
    assert seeded.category_id == groceries.id

    low = _confirm(
        database, evidence, counterparty="NETFLIX COM", amount="-15.00", day=date(2026, 7, 16)
    )
    JevCategorizer(database, _ApplyProposer(dining.id, "Dining", "0.80")).categorize_transaction(
        low
    )
    assert _rule(database, "netflix") is None

    _categorize(database, first, dining.id, version=2)
    corrected = _rule(database, "spotify")
    assert corrected is not None
    assert corrected.source == "owner"
    assert corrected.category_id == dining.id
    report = eval_threshold_report(database)
    assert "threshold=0.50" in report
    assert "precision=" in report
    assert "coverage=" in report


@pytest.mark.integration
def test_memory_backfill_is_dry_run_by_default_and_idempotent(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    groceries = CategoryCatalog(database).create("Groceries")
    transaction_id = _confirm(
        database,
        evidence,
        counterparty="SPOTIFY SG",
        amount="-11.98",
        day=date(2026, 6, 15),
    )
    _categorize(database, transaction_id, groceries.id)
    with database.transaction() as session:
        session.execute(delete(MerchantCategoryMemory))

    preview = backfill_merchant_memory(database, apply=False)
    assert preview.applied is False
    assert preview.rules_before == 0
    assert preview.would_write == 1
    assert _rule(database, "spotify") is None

    applied = backfill_merchant_memory(database, apply=True)
    assert applied.written == 1
    assert applied.rules_after == 1
    assert _rule(database, "spotify") is not None

    again = backfill_merchant_memory(database, apply=True)
    assert again.written == 0
    assert again.cleared == 0
    assert again.rules_after == 1


@pytest.mark.integration
def test_merchant_group_apply_excludes_writes_memory_and_undoes(
    database: Database,
    tmp_path: Path,
    evidence: tuple[UUID, UUID, UUID],
) -> None:
    groceries = CategoryCatalog(database).create("Groceries")
    first = _confirm(
        database, evidence, counterparty="SPOTIFY SG", amount="-11.00", day=date(2026, 5, 1)
    )
    second = _confirm(
        database,
        evidence,
        counterparty="Spotify Pte Ltd",
        amount="-12.00",
        day=date(2026, 5, 2),
    )
    excluded = _confirm(
        database, evidence, counterparty="SPOTIFY 9988", amount="-13.00", day=date(2026, 5, 3)
    )
    _confirm(database, evidence, counterparty="NETFLIX COM", amount="-15.00", day=date(2026, 5, 4))
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )
    headers = {"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"}

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        listed = client.get("/api/v1/reviews/merchant-groups")
        spotify = next(
            item for item in listed.json()["items"] if item["normalized_key"] == "spotify"
        )
        stale = client.post(
            "/api/v1/reviews/merchant-groups/apply",
            headers={**headers, "If-Match": '"merchant-group:not-the-etag"'},
            json={
                "normalized_key": "spotify",
                "category_id": str(groceries.id),
                "exclude_transaction_ids": [],
            },
        )
        applied = client.post(
            "/api/v1/reviews/merchant-groups/apply",
            headers={**headers, "If-Match": spotify["etag"]},
            json={
                "normalized_key": "spotify",
                "category_id": str(groceries.id),
                "exclude_transaction_ids": [str(excluded)],
            },
        )
        rules = client.get("/api/v1/merchant-memory")

    assert listed.status_code == 200
    assert spotify["count"] == 3
    assert stale.status_code == 412
    assert applied.status_code == 200
    applied_ids = {item["transaction_id"] for item in applied.json()["applied"]}
    assert applied_ids == {str(first), str(second)}
    assert applied.json()["memory"]["source"] == "owner"
    assert applied.json()["memory"]["category_id"] == str(groceries.id)
    excluded_now = FinancialHistory(database).get(excluded)
    assert excluded_now.category_splits[0].category_name == "Uncategorized"
    assert rules.json()["items"][0]["normalized_key"] == "spotify"
    with database.transaction() as session:
        exclusion = session.get(MerchantMemoryExclusion, excluded)
    assert exclusion is not None
    fresh = _confirm(
        database,
        evidence,
        counterparty="SPOTIFY SG",
        amount="-14.00",
        day=date(2026, 5, 5),
    )
    remembered = JevCategorizer(database, _RaisingProposer()).categorize_transaction(fresh)
    assert remembered is not None
    assert remembered.category_splits[0].category_id == groceries.id
    caller = _RecordingProposer()
    JevCategorizer(database, caller).categorize_transaction(excluded)
    assert len(caller.subjects) == 1

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        undone = client.post(
            "/api/v1/reviews/merchant-groups/undo",
            headers={**headers, "If-Match": applied.json()["undo_etag"]},
            json={
                "normalized_key": "spotify",
                "category_id": str(groceries.id),
                "transactions": applied.json()["applied"],
                "excluded_transaction_ids": [str(excluded)],
            },
        )

    assert undone.status_code == 200
    assert set(undone.json()["restored_transaction_ids"]) == {str(first), str(second)}
    assert FinancialHistory(database).get(first).category_splits[0].category_name == "Uncategorized"
    assert _rule(database, "spotify") is None
