from datetime import datetime
from uuid import UUID, uuid4

import pytest

from billzebub.entrypoints.worker import worker_handlers
from billzebub.jobs import EnqueuedJob
from billzebub.reconciliation import ReconciliationRun
from billzebub.statement_extraction import ExtractionOutcome, ExtractionStatus
from billzebub.worker import TerminalJobError


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
        available_at: datetime | None = None,
    ) -> EnqueuedJob:
        del max_attempts, available_at
        self.enqueued.append((kind, payload, dedupe_key))
        return EnqueuedJob(id=uuid4(), duplicate=False)


class FakeExtraction:
    def __init__(self, status: ExtractionStatus) -> None:
        self._status = status
        self.received: list[tuple[UUID, UUID]] = []

    def extract(
        self,
        *,
        artifact_id: UUID,
        financial_account_id: UUID,
    ) -> ExtractionOutcome:
        self.received.append((artifact_id, financial_account_id))
        return ExtractionOutcome(
            extraction_id=uuid4(),
            status=self._status,
            claim_count=0,
            duplicate=False,
            failure=None,
            review_id=None,
        )


class FakeReconciliation:
    def __init__(self) -> None:
        self.received: list[UUID] = []

    def reconcile_account(self, financial_account_id: UUID) -> ReconciliationRun:
        self.received.append(financial_account_id)
        return ReconciliationRun(
            financial_account_id=financial_account_id,
            candidates=(),
            confirmations=(),
            ambiguous_review_ids=(),
            unconfirmed_claim_ids=(),
            no_match_real_time_claim_ids=(),
        )


def test_accepted_extraction_enqueues_account_deduplicated_reconciliation() -> None:
    queue = FakeQueue()
    extraction = FakeExtraction(ExtractionStatus.ACCEPTED)
    reconciliation = FakeReconciliation()
    handlers = worker_handlers(queue, extraction, reconciliation)
    artifact_id = uuid4()
    account_id = uuid4()

    handlers["extract_statement"](
        {"artifact_id": str(artifact_id), "financial_account_id": str(account_id)}
    )

    assert extraction.received == [(artifact_id, account_id)]
    assert queue.enqueued == [
        (
            "reconcile_financial_account",
            {"financial_account_id": str(account_id)},
            str(account_id),
        )
    ]


def test_non_accepted_extraction_does_not_enqueue_reconciliation() -> None:
    queue = FakeQueue()
    extraction = FakeExtraction(ExtractionStatus.FAILED)
    handlers = worker_handlers(queue, extraction, FakeReconciliation())

    handlers["extract_statement"](
        {"artifact_id": str(uuid4()), "financial_account_id": str(uuid4())}
    )

    assert queue.enqueued == []


def test_reconciliation_handler_and_invalid_payloads_are_bounded() -> None:
    queue = FakeQueue()
    reconciliation = FakeReconciliation()
    handlers = worker_handlers(queue, FakeExtraction(ExtractionStatus.ACCEPTED), reconciliation)
    account_id = uuid4()

    handlers["reconcile_financial_account"]({"financial_account_id": str(account_id)})

    assert reconciliation.received == [account_id]
    with pytest.raises(TerminalJobError, match="invalid_statement_job"):
        handlers["extract_statement"]({})
    with pytest.raises(TerminalJobError, match="invalid_reconciliation_job"):
        handlers["reconcile_financial_account"]({})
