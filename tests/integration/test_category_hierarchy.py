from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import Select
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.categories import CategoryCatalog, CategoryError
from billzebub.category_spend import CategorySpend
from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.config import Settings
from billzebub.financial_history import (
    CategoryAllocation,
    Confirmation,
    FinancialHistory,
    TransactionKind,
)
from billzebub.identity import OwnerIdentity
from billzebub.jev import choice_criteria, parse_jev_proposal
from billzebub.jev_categorizer import JevCategorizer
from billzebub.money import Money
from billzebub.owner_actors import OwnerActors
from billzebub.owner_transaction_actions import OwnerCategorizationCommand, OwnerTransactionActions
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    Category,
    ClaimCategory,
    Extraction,
    FinancialAccount,
    PendingReview,
    SourceArtifact,
)
from billzebub.review_actions import ReviewActionError, ReviewActions
from billzebub.reviews import (
    PendingReviewStatus,
    ReviewCondition,
    ReviewDecision,
    ReviewInbox,
    ReviewSeverity,
)

_CSRF = {"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"}
_JSON = {**_CSRF, "Content-Type": "application/json"}


@pytest.fixture
def evidence(database: Database) -> tuple[UUID, UUID, UUID]:
    account_id = uuid7()
    artifact_id = uuid7()
    extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-hierarchy-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic Hierarchy Card",
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


def _expense(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    *,
    amount: str,
    day: date,
    counterparty: str,
    category_id: UUID | None = None,
) -> UUID:
    account_id, artifact_id, extraction_id = evidence
    claim = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description=counterparty,
            posted_amount=Money.parse(amount, "SGD"),
            provider_transaction_date=day,
            posting_date=day,
            transaction_kind_hint="expense",
        )
    )
    splits: tuple[CategoryAllocation, ...] = ()
    if category_id is not None:
        splits = (
            CategoryAllocation(
                category_id,
                Money.parse(amount.removeprefix("-"), "SGD"),
            ),
        )
    return (
        FinancialHistory(database)
        .confirm(
            Confirmation(
                statement_claim_id=claim.id,
                kind=TransactionKind.EXPENSE,
                counterparty=counterparty,
                category_splits=splits,
            )
        )
        .id
    )


@pytest.mark.integration
def test_category_depth_limit_is_enforced_in_catalog_and_database(database: Database) -> None:
    catalog = CategoryCatalog(database)
    food = catalog.create("Food")
    dining = catalog.create("Dining", parent_id=food.id)

    with pytest.raises(CategoryError, match="two levels"):
        catalog.create("Late night", parent_id=dining.id)
    with pytest.raises(SQLAlchemyError, match="two levels"):
        with database.transaction() as session:
            session.execute(
                text(
                    """
                    INSERT INTO category (id, parent_id, name)
                    VALUES (:id, :parent_id, 'Late night')
                    """
                ),
                {"id": uuid7(), "parent_id": dining.id},
            )
    constraints = {
        item["name"] for item in inspect(database.engine).get_check_constraints("category")
    }
    indexes = {item["name"] for item in inspect(database.engine).get_indexes("category")}
    with database.transaction() as session:
        trigger = session.scalar(
            text("SELECT tgname FROM pg_trigger WHERE tgname = 'category_two_level_guard'")
        )

    assert "ck_category_category_parent_not_self" in constraints
    assert "ix_category_parent_id" in indexes
    assert "uq_category_parent_name" in {
        item["name"] for item in inspect(database.engine).get_unique_constraints("category")
    }
    assert trigger == "category_two_level_guard"


@pytest.mark.integration
def test_category_names_are_unique_per_parent(database: Database) -> None:
    catalog = CategoryCatalog(database)
    food = catalog.create("Food")
    travel = catalog.create("Travel")
    catalog.create("Dining", parent_id=food.id)
    travel_dining = catalog.create("Dining", parent_id=travel.id)

    assert travel_dining.parent_id == travel.id
    with pytest.raises(CategoryError, match="already exists"):
        catalog.create("Dining", parent_id=food.id)
    with pytest.raises(CategoryError, match="already exists"):
        catalog.create("Food")


@pytest.mark.integration
def test_category_http_renames_moves_archives_and_blocks_depth(
    database: Database,
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        blocked = client.post("/api/v1/categories", json={"name": "Food"})
        food = client.post("/api/v1/categories", headers=_CSRF, json={"name": "Food"})
        transport = client.post("/api/v1/categories", headers=_CSRF, json={"name": "Transport"})
        dining = client.post(
            "/api/v1/categories",
            headers=_CSRF,
            json={"name": "Dining", "parent_id": food.json()["id"]},
        )
        missing_match = client.patch(
            f"/api/v1/categories/{dining.json()['id']}",
            headers=_CSRF,
            json={"name": "Eating out"},
        )
        stale = client.patch(
            f"/api/v1/categories/{dining.json()['id']}",
            headers={**_CSRF, "If-Match": '"category:00000000-0000-0000-0000-000000000000:v1"'},
            json={"name": "Eating out"},
        )
        renamed = client.patch(
            f"/api/v1/categories/{dining.json()['id']}",
            headers={**_CSRF, "If-Match": dining.headers["etag"]},
            json={"name": "Eating out"},
        )
        moved = client.patch(
            f"/api/v1/categories/{dining.json()['id']}",
            headers={**_CSRF, "If-Match": renamed.headers["etag"]},
            json={"parent_id": transport.json()["id"]},
        )
        promoted = client.patch(
            f"/api/v1/categories/{dining.json()['id']}",
            headers={**_CSRF, "If-Match": moved.headers["etag"]},
            json={"parent_id": None},
        )
        late = client.post(
            "/api/v1/categories",
            headers=_CSRF,
            json={"name": "Late night", "parent_id": dining.json()["id"]},
        )
        grandchild = client.post(
            "/api/v1/categories",
            headers=_CSRF,
            json={"name": "After midnight", "parent_id": late.json()["id"]},
        )
        cycle = client.patch(
            f"/api/v1/categories/{dining.json()['id']}",
            headers={**_CSRF, "If-Match": promoted.headers["etag"]},
            json={"parent_id": late.json()["id"]},
        )
        archived = client.patch(
            f"/api/v1/categories/{dining.json()['id']}",
            headers={**_CSRF, "If-Match": promoted.headers["etag"]},
            json={"active": False},
        )
        removed = client.delete(
            f"/api/v1/categories/{dining.json()['id']}",
            headers={**_JSON, "If-Match": archived.headers["etag"]},
        )
        listed = {item["id"]: item for item in client.get("/api/v1/categories").json()["items"]}

    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "browser_mutation_forbidden"
    assert food.status_code == 201
    assert food.headers["etag"] == f'"category:{food.json()["id"]}:v1"'
    assert dining.json()["parent_id"] == food.json()["id"]
    assert missing_match.status_code == 428
    assert missing_match.json()["detail"] == "resource_version_required"
    assert stale.status_code == 412
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Eating out"
    assert renamed.json()["version"] == 2
    assert moved.json()["parent_id"] == transport.json()["id"]
    assert promoted.json()["parent_id"] is None
    assert late.status_code == 201
    assert grandchild.status_code == 400
    assert grandchild.json()["detail"] == "category_request_invalid"
    assert cycle.status_code == 400
    assert archived.status_code == 200
    assert archived.json()["active"] is False
    assert listed[late.json()["id"]]["active"] is False
    assert removed.status_code == 409
    assert removed.json()["detail"] == "category_in_use"


@pytest.mark.integration
def test_in_use_category_is_archived_instead_of_deleted(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    catalog = CategoryCatalog(database)
    food = catalog.create("Food")
    dining = catalog.create("Dining", parent_id=food.id)
    spare = catalog.create("Spare")
    transaction_id = _expense(
        database,
        evidence,
        amount="-12.00",
        day=date(2026, 3, 2),
        counterparty="Synthetic Dining",
        category_id=dining.id,
    )
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        current = client.get(f"/api/v1/categories/{dining.id}")
        refused = client.delete(
            f"/api/v1/categories/{dining.id}",
            headers={**_JSON, "If-Match": current.headers["etag"]},
        )
        archived = client.patch(
            f"/api/v1/categories/{dining.id}",
            headers={**_CSRF, "If-Match": current.headers["etag"]},
            json={"active": False},
        )
        parent_delete = client.delete(
            f"/api/v1/categories/{food.id}",
            headers={**_JSON, "If-Match": f'"category:{food.id}:v1"'},
        )
        spare_delete = client.delete(
            f"/api/v1/categories/{spare.id}",
            headers={**_JSON, "If-Match": f'"category:{spare.id}:v1"'},
        )

    assert current.status_code == 200
    assert refused.status_code == 409
    assert refused.json()["detail"] == "category_in_use"
    assert archived.json()["active"] is False
    assert parent_delete.status_code == 409
    assert spare_delete.status_code == 204
    with pytest.raises(CategoryError, match="not found"):
        catalog.get(spare.id)
    assert (
        FinancialHistory(database).get(transaction_id).category_splits[0].category_id == dining.id
    )


@pytest.mark.integration
def test_category_spend_rolls_child_totals_up_to_the_parent(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    catalog = CategoryCatalog(database)
    food = catalog.create("Food")
    dining = catalog.create("Dining", parent_id=food.id)
    groceries = catalog.create("Groceries", parent_id=food.id)
    transport = catalog.create("Transport")
    account_id, artifact_id, extraction_id = evidence
    _expense(
        database,
        evidence,
        amount="-10.00",
        day=date(2026, 3, 2),
        counterparty="Synthetic Grocer Parent",
        category_id=food.id,
    )
    _expense(
        database,
        evidence,
        amount="-15.00",
        day=date(2026, 3, 3),
        counterparty="Synthetic Dining",
        category_id=dining.id,
    )
    _expense(
        database,
        evidence,
        amount="-5.00",
        day=date(2026, 3, 4),
        counterparty="Synthetic Groceries",
        category_id=groceries.id,
    )
    _expense(
        database,
        evidence,
        amount="-7.00",
        day=date(2026, 3, 5),
        counterparty="Synthetic Transport",
        category_id=transport.id,
    )
    _expense(
        database,
        evidence,
        amount="-100.00",
        day=date(2026, 2, 1),
        counterparty="Synthetic February",
        category_id=food.id,
    )
    included = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="SYNTHETIC WALLET DINING",
            authorized_amount=Money.parse("-4.00", "SGD"),
            occurrence_at=datetime(2026, 2, 28, 16, 30, tzinfo=UTC),
            transaction_kind_hint="expense",
        )
    )
    excluded = ClaimBook(database).record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description="SYNTHETIC WALLET APRIL",
            authorized_amount=Money.parse("-99.00", "SGD"),
            occurrence_at=datetime(2026, 3, 31, 16, 0, tzinfo=UTC),
            transaction_kind_hint="expense",
        )
    )
    with database.transaction() as session:
        session.add(
            ClaimCategory(
                id=uuid7(),
                claim_id=included.id,
                category_id=dining.id,
                amount=Decimal("4.00"),
                currency="SGD",
            )
        )
        session.add(
            ClaimCategory(
                id=uuid7(),
                claim_id=excluded.id,
                category_id=transport.id,
                amount=Decimal("99.00"),
                currency="SGD",
            )
        )

    report = CategorySpend(database).for_month("2026-03")
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/v1/categories/spending", params={"month": "2026-03"})

    by_name = {item.name: item for item in report.items}
    assert by_name["Food"].direct == Money.parse("10.00", "SGD")
    assert by_name["Food"].total == Money.parse("34.00", "SGD")
    children = {child.name: child for child in by_name["Food"].children}
    assert children["Dining"].direct == Money.parse("19.00", "SGD")
    assert children["Groceries"].total == Money.parse("5.00", "SGD")
    assert by_name["Food"].total.amount == (
        by_name["Food"].direct.amount
        + sum(child.total.amount for child in by_name["Food"].children)
    )
    assert by_name["Transport"].total == Money.parse("7.00", "SGD")
    assert response.status_code == 200
    body = {item["name"]: item for item in response.json()["items"]}
    assert body["Food"]["total"] == {"amount": "34.00", "currency": "SGD"}
    assert body["Food"]["direct"] == {"amount": "10.00", "currency": "SGD"}
    assert {child["name"]: child["total"]["amount"] for child in body["Food"]["children"]} == {
        "Dining": "19.00",
        "Groceries": "5.00",
    }


@pytest.mark.integration
def test_owner_categorization_and_review_decide_accept_a_child(
    database: Database,
    evidence: tuple[UUID, UUID, UUID],
    tmp_path: Path,
) -> None:
    food = CategoryCatalog(database).create("Food")
    dining = CategoryCatalog(database).create("Dining", parent_id=food.id)
    parent_transaction = _expense(
        database,
        evidence,
        amount="-8.00",
        day=date(2026, 3, 6),
        counterparty="Synthetic Parent Spend",
        category_id=food.id,
    )
    child_transaction = _expense(
        database,
        evidence,
        amount="-9.00",
        day=date(2026, 3, 7),
        counterparty="Synthetic Child Spend",
    )
    review_transaction = _expense(
        database,
        evidence,
        amount="-6.00",
        day=date(2026, 3, 8),
        counterparty="Synthetic Review Spend",
    )
    history = FinancialHistory(database)
    assert history.get(parent_transaction).category_splits[0].category_id == food.id
    actor_id = OwnerActors(database).resolve(
        OwnerIdentity(login="owner@example.test", name="Synthetic Owner")
    )
    categorized = OwnerTransactionActions(database).categorize(
        OwnerCategorizationCommand(
            transaction_id=child_transaction,
            expected_version=1,
            category_id=dining.id,
            actor_id=actor_id,
        )
    )
    assert categorized.category_splits[0].category_id == dining.id
    assert categorized.category_splits[0].category_name == "Dining"

    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )
    with database.transaction() as session:
        review = session.scalar(_pending_review(review_transaction))
    assert review is not None
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        detail = client.get(f"/api/v1/reviews/{review.id}")
        decided = client.post(
            f"/api/v1/reviews/{review.id}/decisions",
            headers={**_CSRF, "If-Match": detail.headers["etag"]},
            json={"choice": "categorize", "category_id": str(dining.id)},
        )

    assert detail.status_code == 200
    assert decided.status_code == 200
    assert decided.json()["status"] == "cancelled"
    assert history.get(review_transaction).category_splits[0].category_id == dining.id
    with database.transaction() as session:
        pending = session.scalar(_pending_review(review_transaction))
    assert pending is None


def _pending_review(transaction_id: UUID) -> Select[tuple[PendingReview]]:
    return select(PendingReview).where(
        PendingReview.subject_type == "transaction",
        PendingReview.subject_id == transaction_id,
        PendingReview.condition_code == "categorization_needed",
        PendingReview.status == PendingReviewStatus.PENDING.value,
    )


@pytest.mark.integration
def test_jev_catalog_paths_fall_back_to_the_parent(database: Database) -> None:
    catalog = CategoryCatalog(database)
    food = catalog.create("Food")
    dining = catalog.create("Dining", parent_id=food.id)
    catalog.create("Groceries", parent_id=food.id)
    catalog.create("Transport")
    with database.transaction() as session:
        session.add(Category(id=uuid7(), name="Uncategorized", active=True, sort_order=0))
        categories = JevCategorizer._active_categories(session)

    criteria = choice_criteria(categories)
    assert criteria["Food > Dining"] == "Food > Dining"
    assert "Uncategorized" not in criteria
    child = parse_jev_proposal(
        "Food > Dining",
        "0.91",
        categories,
        Decimal("0.5"),
        model="jev-1.13.0",
    )
    fallback = parse_jev_proposal(
        "Food > Dining",
        "0.20",
        categories,
        Decimal("0.5"),
        model="jev-1.13.0",
        probabilities={
            "Food > Dining": "0.40",
            "Food > Groceries": "0.30",
            "Food": "0.05",
            "Transport": "0.25",
        },
    )
    skipped = parse_jev_proposal(
        "Food > Dining",
        "0.20",
        categories,
        Decimal("0.5"),
        model="jev-1.13.0",
    )

    assert child.action == "apply"
    assert child.category_id == dining.id
    assert fallback.action == "apply"
    assert fallback.category_id == food.id
    assert fallback.category_name == "Food"
    assert skipped.action == "skip"


@pytest.mark.integration
def test_generic_categorization_decision_still_requires_a_category(database: Database) -> None:
    review = ReviewInbox(database).synchronize(
        ReviewCondition(
            subject_type="transaction",
            subject_id=uuid7(),
            condition_code="categorization_needed",
            severity=ReviewSeverity.ATTENTION,
            allowed_decisions=("categorize",),
        ),
        active=True,
    )
    assert review is not None

    with pytest.raises(ReviewActionError, match="categorizing"):
        ReviewActions(database).decide(
            ReviewDecision(
                review_id=review.id,
                expected_version=review.version,
                choice="categorize",
            )
        )
