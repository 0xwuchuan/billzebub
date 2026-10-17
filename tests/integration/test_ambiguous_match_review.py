from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from uuid6 import uuid7

from billzebub.api import create_app
from billzebub.claims import ClaimBook, ClaimDraft, ClaimType
from billzebub.config import Settings
from billzebub.money import Money
from billzebub.owner_workspace import OwnerWorkspace
from billzebub.persistence.database import Database
from billzebub.persistence.models import Extraction, FinancialAccount, PendingReview, SourceArtifact
from billzebub.reconciliation import Reconciliation

_SINGAPORE = ZoneInfo("Asia/Singapore")
_WALLET_DESCRIPTION = "Café Synthetic — Iced Latte"
_EXACT_DESCRIPTION = "CAFE SYNTHETIC ICED LATTE"
_GROCER_DESCRIPTION = "SYNTHETIC GROCER MARKET"


@pytest.mark.integration
def test_ambiguous_match_review_payload_renders_both_sides(
    database: Database,
    tmp_path: Path,
) -> None:
    account_id = uuid7()
    artifact_id = uuid7()
    wallet_extraction_id = uuid7()
    statement_extraction_id = uuid7()
    grocer_extraction_id = uuid7()
    with database.transaction() as session:
        session.add(
            FinancialAccount(
                id=account_id,
                slug="synthetic-ambiguous-match-card",
                institution="synthetic-bank",
                kind="credit_card",
                display_name="Synthetic DBS Card",
                default_currency="SGD",
                statement_account_identifier="XXXX-XXXX-XXXX-4242",
            )
        )
        session.add(
            SourceArtifact(
                id=artifact_id,
                sha256="a" * 64,
                size=64,
                media_type="application/json",
                content_path="sha256/aa/" + "a" * 64,
                captured_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        session.flush()
        session.add_all(
            [
                Extraction(
                    id=wallet_extraction_id,
                    artifact_id=artifact_id,
                    financial_account_id=account_id,
                    adapter_key="apple_wallet_shortcut",
                    parser_version="wallet-v1",
                    status="accepted",
                    validation_report={"source": "apple_wallet"},
                    accepted_at=datetime(2026, 1, 10, tzinfo=UTC),
                ),
                Extraction(
                    id=statement_extraction_id,
                    artifact_id=artifact_id,
                    financial_account_id=account_id,
                    adapter_key="dbs-credit-card",
                    parser_version="statement-v1",
                    status="accepted",
                    statement_identity="dbs:2026-01-31:synthetic",
                    period_start=date(2026, 1, 1),
                    period_end=date(2026, 1, 31),
                    accepted_at=datetime(2026, 1, 31, tzinfo=UTC),
                ),
                Extraction(
                    id=grocer_extraction_id,
                    artifact_id=artifact_id,
                    financial_account_id=account_id,
                    adapter_key="synthetic-statement",
                    parser_version="statement-v2",
                    status="accepted",
                    accepted_at=datetime(2026, 1, 31, 1, tzinfo=UTC),
                ),
            ]
        )

    book = ClaimBook(database)
    wallet_id = book.record(
        ClaimDraft(
            claim_type=ClaimType.REAL_TIME,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=wallet_extraction_id,
            raw_description=_WALLET_DESCRIPTION,
            authorized_amount=Money.parse("-8.00", "SGD"),
            occurrence_at=datetime(2026, 1, 10, 13, 5, tzinfo=_SINGAPORE),
        )
    ).id
    exact_id = _statement(
        book,
        account_id=account_id,
        artifact_id=artifact_id,
        extraction_id=statement_extraction_id,
        description=_EXACT_DESCRIPTION,
        provider_date=date(2026, 1, 10),
        posting_date=date(2026, 1, 12),
    )
    earlier_id = _statement(
        book,
        account_id=account_id,
        artifact_id=artifact_id,
        extraction_id=statement_extraction_id,
        description=_EXACT_DESCRIPTION,
        provider_date=date(2026, 1, 9),
        posting_date=date(2026, 1, 11),
    )
    grocer_id = _statement(
        book,
        account_id=account_id,
        artifact_id=artifact_id,
        extraction_id=grocer_extraction_id,
        description=_GROCER_DESCRIPTION,
        provider_date=date(2026, 1, 10),
        posting_date=date(2026, 1, 13),
    )
    fx_id = book.record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=statement_extraction_id,
            raw_description=_EXACT_DESCRIPTION,
            posted_amount=Money.parse("-10.80", "USD"),
            original_amount=Money.parse("-8.00", "SGD"),
            provider_transaction_date=date(2026, 1, 10),
            posting_date=date(2026, 1, 12),
            transaction_kind_hint="expense",
        )
    ).id

    reconciliation = Reconciliation(database)
    ambiguous = reconciliation.reconcile_account(account_id)
    repeated = reconciliation.reconcile_account(account_id)

    assert ambiguous.confirmations == ()
    assert len(ambiguous.ambiguous_review_ids) == 1
    review_id = ambiguous.ambiguous_review_ids[0]
    assert repeated.ambiguous_review_ids == (review_id,)
    with database.transaction() as session:
        stored = session.get(PendingReview, review_id)
        assert stored is not None
        assert stored.version == 1
        assert "provisional" not in stored.context
        assert stored.context["candidate_count"] == 4
        stored_candidates = [dict(entry) for entry in stored.context["candidates"]]
        assert {entry["statement_claim_id"] for entry in stored_candidates} == {
            str(exact_id),
            str(earlier_id),
            str(grocer_id),
            str(fx_id),
        }
        stored_candidates[0]["legacy_note"] = "keep-me"
        stored.context = {
            "candidate_count": stored.context["candidate_count"],
            "candidates": stored_candidates,
        }

    workspace = OwnerWorkspace(database)
    projected = workspace.get_review(review_id)
    by_id = {item["claim_id"]: item for item in projected.context["candidates"]}
    exact = by_id[str(exact_id)]
    earlier = by_id[str(earlier_id)]
    grocer = by_id[str(grocer_id)]
    fx = by_id[str(fx_id)]

    assert projected.context["provisional"] == {
        "claim_id": str(wallet_id),
        "counterparty": {
            "raw": _WALLET_DESCRIPTION,
            "normalized": "cafe synthetic iced latte",
        },
        "amount": "-8.00",
        "currency": "SGD",
        "occurred_at": {
            "date": "2026-01-10",
            "time": "13:05:00",
            "timezone": "Asia/Singapore",
        },
        "last4": "4242",
        "source": "wallet",
    }
    assert exact["statement_claim_id"] == str(exact_id)
    assert exact["raw_description"] == _EXACT_DESCRIPTION
    assert exact["normalized_counterparty"] == "cafe synthetic iced latte"
    assert exact["amount"] == "-8.00"
    assert exact["currency"] == "SGD"
    assert exact["posted_date"] == "2026-01-12"
    assert exact["transaction_date"] == "2026-01-10"
    assert exact["last4"] == "4242"
    assert exact["statement_id"] == str(statement_extraction_id)
    assert exact["statement_identity"] == "dbs:2026-01-31:synthetic"
    assert exact["statement_label"] == "Synthetic DBS Card"
    assert exact["issuer"] == "dbs"
    assert exact["period_start"] == "2026-01-01"
    assert exact["period_end"] == "2026-01-31"
    assert exact["amount_delta"] == "0.00"
    assert exact["day_delta"] == 0
    assert exact["score"] == 100
    assert "amount_exact_posted" in exact["reasons"]
    assert exact["match_reasons"] == [
        {"criterion": "financial_account", "passed": True, "code": "same_financial_account"},
        {"criterion": "amount", "passed": True, "code": "amount_exact_posted"},
        {"criterion": "date", "passed": True, "code": "activity_date_exact"},
        {"criterion": "counterparty", "passed": True, "code": "counterparty_exact"},
    ]
    assert earlier["day_delta"] == -1
    assert earlier["posted_date"] == "2026-01-11"
    assert earlier["transaction_date"] == "2026-01-09"
    assert earlier["amount_delta"] == "0.00"
    assert grocer["period_start"] is None
    assert grocer["period_end"] is None
    assert grocer["statement_identity"] is None
    assert grocer["issuer"] == "synthetic-bank"
    assert grocer["statement_label"] == "Synthetic DBS Card"
    assert grocer["match_reasons"][-1] == {
        "criterion": "counterparty",
        "passed": False,
        "code": "counterparty_no_overlap",
    }
    assert fx["amount"] == "-10.80"
    assert fx["currency"] == "USD"
    assert fx["amount_delta"] is None
    assert any(item.get("legacy_note") == "keep-me" for item in projected.context["candidates"])
    assert any(
        review.context.get("provisional", {}).get("claim_id") == str(wallet_id)
        for review in workspace.list_reviews(limit=10).items
    )

    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="owner@example.test"),
        database,
    )
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        detail = client.get(f"/api/v1/reviews/{review_id}")
        listed = client.get("/api/v1/reviews")
        decided = client.post(
            f"/api/v1/reviews/{review_id}/decisions",
            headers={
                "Origin": "http://testserver",
                "X-Billzebub-CSRF": "bzb-spa",
                "If-Match": detail.headers["etag"],
            },
            json={"choice": f"match:{exact_id}"},
        )

    assert detail.status_code == 200
    body = detail.json()
    assert body["condition_code"] == "reconciliation_ambiguous"
    assert body["subject_id"] == str(wallet_id)
    assert body["context"]["provisional"]["source"] == "wallet"
    assert body["context"]["provisional"]["occurred_at"]["time"] == "13:05:00"
    assert {item["claim_id"] for item in body["context"]["candidates"]} == {
        str(exact_id),
        str(earlier_id),
        str(grocer_id),
        str(fx_id),
    }
    listed_review = next(item for item in listed.json()["items"] if item["id"] == str(review_id))
    assert listed_review["context"]["provisional"]["last4"] == "4242"
    assert decided.status_code == 200
    assert decided.json()["status"] == "resolved"
    assert decided.json()["context"]["provisional"]["claim_id"] == str(wallet_id)
    assert decided.json()["context"]["candidates"][0]["statement_claim_id"]
    with database.transaction() as session:
        stored = session.get(PendingReview, review_id)
        assert stored is not None
        assert stored.status == "resolved"
        assert "provisional" not in stored.context


def _statement(
    book: ClaimBook,
    *,
    account_id: UUID,
    artifact_id: UUID,
    extraction_id: UUID,
    description: str,
    provider_date: date,
    posting_date: date,
) -> UUID:
    return book.record(
        ClaimDraft(
            claim_type=ClaimType.STATEMENT,
            financial_account_id=account_id,
            source_artifact_id=artifact_id,
            extraction_id=extraction_id,
            raw_description=description,
            posted_amount=Money.parse("-8.00", "SGD"),
            provider_transaction_date=provider_date,
            posting_date=posting_date,
            transaction_kind_hint="expense",
        )
    ).id
