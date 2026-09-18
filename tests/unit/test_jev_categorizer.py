import logging
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from billzebub.financial_history import CategorySplitRecord, TransactionKind, TransactionSnapshot
from billzebub.jev import JevCategory, JevSubject, Proposal
from billzebub.jev_categorizer import (
    JevCatchupScheduler,
    _log_attempt,
    enqueue_transaction_categorization,
    subject_from_snapshot,
)
from billzebub.money import Money

FOOD_ID = UUID("11111111-1111-1111-1111-111111111111")
TXN_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict[str, object], str | None]] = []

    def enqueue(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        dedupe_key: str | None = None,
        max_attempts: int = 5,
        available_at: object = None,
    ) -> object:
        del max_attempts, available_at
        self.enqueued.append((kind, payload, dedupe_key))
        return object()


def _snapshot(**overrides: object) -> TransactionSnapshot:
    values: dict[str, object] = {
        "id": TXN_ID,
        "version_id": uuid4(),
        "version": 1,
        "financial_account_id": uuid4(),
        "kind": TransactionKind.EXPENSE,
        "posted_amount": Money.parse("-12.34", "SGD"),
        "authorized_amount": None,
        "effective_date": date(2026, 1, 10),
        "counterparty": "Synthetic Coffee",
        "category_splits": (
            CategorySplitRecord(
                category_id=uuid4(),
                category_name="Uncategorized",
                amount=Money.parse("12.34", "SGD"),
            ),
        ),
    }
    values.update(overrides)
    return TransactionSnapshot(**values)  # type: ignore[arg-type]


def test_subject_from_snapshot_is_agent_safe() -> None:
    subject = subject_from_snapshot(_snapshot())
    assert subject == JevSubject(
        counterparty="Synthetic Coffee",
        amount="-12.34",
        currency="SGD",
        effective_date="2026-01-10",
        kind="expense",
    )
    assert str(TXN_ID) not in (subject.counterparty, subject.amount, subject.kind)


def test_enqueue_transaction_categorization_dedupes_on_id() -> None:
    queue = FakeQueue()
    enqueue_transaction_categorization(queue, TXN_ID)
    assert queue.enqueued == [
        ("categorize_transaction", {"transaction_id": str(TXN_ID)}, str(TXN_ID))
    ]


def test_catchup_cron_defaults_match_singapore_evening() -> None:
    from billzebub.jev_categorizer import DEFAULT_CATCHUP_CRON, DEFAULT_CATCHUP_HOUR

    assert DEFAULT_CATCHUP_HOUR == 21
    assert DEFAULT_CATCHUP_CRON == "0 21 * * *"
    scheduler = JevCatchupScheduler(hour=21, timezone=ZoneInfo("Asia/Singapore"))
    assert scheduler.hour == 21


def test_proposal_type_is_reused() -> None:
    proposal = Proposal(
        action="apply",
        category_id=FOOD_ID,
        category_name="Synthetic Food",
        confidence=Decimal("0.5"),
        model="jev-1.13.0",
    )
    category = JevCategory(id=FOOD_ID, name="Synthetic Food")
    assert proposal.category_id == category.id


def test_attempt_info_log_includes_decision_without_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    proposal = Proposal(
        action="skip",
        category_id=None,
        category_name=None,
        confidence=Decimal("0.49"),
        model="jev-1.13.0",
        choice="Synthetic Food",
        noul=Decimal("0.40"),
    )
    with caplog.at_level(logging.INFO, logger="billzebub.jev_categorizer"):
        _log_attempt(TXN_ID, proposal)
    assert "action=skip" in caplog.text
    assert "confidence=0.49" in caplog.text
    assert "noul=0.40" in caplog.text
    assert "category=skip" in caplog.text
    assert str(TXN_ID) in caplog.text
    assert "synthetic-typesafe-key" not in caplog.text
