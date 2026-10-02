import importlib
from datetime import datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from billzebub.entrypoints.worker import (
    JobEnqueuer,
    enqueue_scheduled_catch_up,
    worker_handlers,
)
from billzebub.jev import JevError
from billzebub.jev_categorizer import (
    CATEGORIZE_CLAIM_JOB,
    CATEGORIZE_TRANSACTION_JOB,
    JEV_CATCH_UP_JOB,
    CategorizerError,
    JevCatchupScheduler,
    enqueue_claim_categorization,
    enqueue_jev_catch_up,
    enqueue_transaction_categorization,
)
from billzebub.jobs import EnqueuedJob
from billzebub.reconciliation import ReconciliationConfirmation, ReconciliationRun
from billzebub.recurrings import (
    DETECT_RECURRING_SERIES_JOB,
    MATCH_RECURRING_TRANSACTION_JOB,
)
from billzebub.statement_extraction import ExtractionOutcome, ExtractionStatus
from billzebub.worker import JobHandler, RetryableJobError, TerminalJobError


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
        self.run: ReconciliationRun | None = None

    def reconcile_account(self, financial_account_id: UUID) -> ReconciliationRun:
        self.received.append(financial_account_id)
        if self.run is not None:
            return self.run
        return ReconciliationRun(
            financial_account_id=financial_account_id,
            candidates=(),
            confirmations=(),
            ambiguous_review_ids=(),
            unconfirmed_claim_ids=(),
            no_match_real_time_claim_ids=(),
        )


class FakeCategorizer:
    def __init__(self) -> None:
        self.received: list[UUID] = []
        self.received_claims: list[UUID] = []
        self.pending: tuple[UUID, ...] = ()
        self.pending_claims: tuple[UUID, ...] = ()
        self.error: Exception | None = None

    def categorize_transaction(self, transaction_id: UUID) -> None:
        if self.error is not None:
            raise self.error
        self.received.append(transaction_id)

    def categorize_claim(self, claim_id: UUID) -> None:
        if self.error is not None:
            raise self.error
        self.received_claims.append(claim_id)

    def enqueue_pending(self, queue: JobEnqueuer) -> int:
        for transaction_id in self.pending:
            enqueue_transaction_categorization(queue, transaction_id)
        for claim_id in self.pending_claims:
            enqueue_claim_categorization(queue, claim_id)
        return len(self.pending) + len(self.pending_claims)


class FakeRecurrings:
    def __init__(self) -> None:
        self.matched: list[UUID] = []
        self.detected = 0

    def match_transaction(self, transaction_id: UUID) -> None:
        self.matched.append(transaction_id)

    def detect(self) -> None:
        self.detected += 1


def _handlers(
    queue: FakeQueue,
    extraction: FakeExtraction | None = None,
    reconciliation: FakeReconciliation | None = None,
    categorizer: FakeCategorizer | None = None,
    recurrings: FakeRecurrings | None = None,
) -> dict[str, JobHandler]:
    return worker_handlers(
        queue,
        extraction or FakeExtraction(ExtractionStatus.ACCEPTED),
        reconciliation or FakeReconciliation(),
        categorizer or FakeCategorizer(),
        recurrings or FakeRecurrings(),
    )


def _confirmation_run(account_id: UUID, transaction_id: UUID) -> ReconciliationRun:
    return ReconciliationRun(
        financial_account_id=account_id,
        candidates=(),
        confirmations=(
            ReconciliationConfirmation(
                transaction_id=transaction_id,
                statement_claim_id=uuid4(),
                real_time_claim_id=None,
                source="statement_only",
            ),
        ),
        ambiguous_review_ids=(),
        unconfirmed_claim_ids=(),
        no_match_real_time_claim_ids=(),
    )


def test_accepted_extraction_enqueues_account_deduplicated_reconciliation() -> None:
    queue = FakeQueue()
    extraction = FakeExtraction(ExtractionStatus.ACCEPTED)
    reconciliation = FakeReconciliation()
    handlers = _handlers(queue, extraction, reconciliation)
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
    handlers = _handlers(queue, extraction, FakeReconciliation())

    handlers["extract_statement"](
        {"artifact_id": str(uuid4()), "financial_account_id": str(uuid4())}
    )

    assert queue.enqueued == []


def test_reconciliation_handler_and_invalid_payloads_are_bounded() -> None:
    queue = FakeQueue()
    reconciliation = FakeReconciliation()
    handlers = _handlers(queue, reconciliation=reconciliation)
    account_id = uuid4()

    handlers["reconcile_financial_account"]({"financial_account_id": str(account_id)})

    assert reconciliation.received == [account_id]
    with pytest.raises(TerminalJobError, match="invalid_statement_job"):
        handlers["extract_statement"]({})
    with pytest.raises(TerminalJobError, match="invalid_reconciliation_job"):
        handlers["reconcile_financial_account"]({})
    with pytest.raises(TerminalJobError, match="invalid_categorize_job"):
        handlers[CATEGORIZE_TRANSACTION_JOB]({})


def test_reconciliation_enqueues_categorize_jobs_for_confirmations() -> None:
    queue = FakeQueue()
    transaction_id = uuid4()
    account_id = uuid4()
    reconciliation = FakeReconciliation()
    reconciliation.run = _confirmation_run(account_id, transaction_id)
    handlers = _handlers(queue, reconciliation=reconciliation)

    handlers["reconcile_financial_account"]({"financial_account_id": str(account_id)})

    assert queue.enqueued == [
        (
            CATEGORIZE_TRANSACTION_JOB,
            {"transaction_id": str(transaction_id)},
            str(transaction_id),
        ),
        (
            MATCH_RECURRING_TRANSACTION_JOB,
            {"transaction_id": str(transaction_id)},
            f"recurring-match:{transaction_id}",
        ),
        (
            DETECT_RECURRING_SERIES_JOB,
            {"run_key": f"reconcile:{account_id}"},
            f"recurring-detect:reconcile:{account_id}",
        ),
    ]


def test_matched_real_time_confirmation_uses_the_same_categorize_hook() -> None:
    queue = FakeQueue()
    transaction_id = uuid4()
    account_id = uuid4()
    real_time_id = uuid4()
    reconciliation = FakeReconciliation()
    reconciliation.run = ReconciliationRun(
        financial_account_id=account_id,
        candidates=(),
        confirmations=(
            ReconciliationConfirmation(
                transaction_id=transaction_id,
                statement_claim_id=uuid4(),
                real_time_claim_id=real_time_id,
                source="matched",
            ),
        ),
        ambiguous_review_ids=(),
        unconfirmed_claim_ids=(),
        no_match_real_time_claim_ids=(),
    )
    handlers = _handlers(queue, reconciliation=reconciliation)

    handlers["reconcile_financial_account"]({"financial_account_id": str(account_id)})

    assert queue.enqueued == [
        (
            CATEGORIZE_TRANSACTION_JOB,
            {"transaction_id": str(transaction_id)},
            str(transaction_id),
        ),
        (
            MATCH_RECURRING_TRANSACTION_JOB,
            {"transaction_id": str(transaction_id)},
            f"recurring-match:{transaction_id}",
        ),
        (
            DETECT_RECURRING_SERIES_JOB,
            {"run_key": f"reconcile:{account_id}"},
            f"recurring-detect:reconcile:{account_id}",
        ),
    ]


def test_categorize_handler_runs_the_transaction_pass() -> None:
    queue = FakeQueue()
    categorizer = FakeCategorizer()
    transaction_id = uuid4()
    handlers = _handlers(queue, categorizer=categorizer)

    handlers[CATEGORIZE_TRANSACTION_JOB]({"transaction_id": str(transaction_id)})

    assert categorizer.received == [transaction_id]


def test_categorize_handler_retries_typesafe_failures() -> None:
    categorizer = FakeCategorizer()
    categorizer.error = JevError("typesafe systemone failed")
    handlers = _handlers(FakeQueue(), categorizer=categorizer)

    with pytest.raises(RetryableJobError, match="jev_unavailable"):
        handlers[CATEGORIZE_TRANSACTION_JOB]({"transaction_id": str(uuid4())})


def test_categorize_handler_terminates_policy_failures() -> None:
    categorizer = FakeCategorizer()
    categorizer.error = CategorizerError("Transaction was not found")
    handlers = _handlers(FakeQueue(), categorizer=categorizer)

    with pytest.raises(TerminalJobError, match="invalid_categorize_job"):
        handlers[CATEGORIZE_TRANSACTION_JOB]({"transaction_id": str(uuid4())})


def test_categorize_claim_handler_runs_the_same_jev_path() -> None:
    queue = FakeQueue()
    categorizer = FakeCategorizer()
    claim_id = uuid4()
    handlers = _handlers(queue, categorizer=categorizer)

    handlers[CATEGORIZE_CLAIM_JOB]({"claim_id": str(claim_id)})

    assert categorizer.received_claims == [claim_id]
    with pytest.raises(TerminalJobError, match="invalid_categorize_job"):
        handlers[CATEGORIZE_CLAIM_JOB]({})


def test_categorize_claim_handler_retries_typesafe_failures() -> None:
    categorizer = FakeCategorizer()
    categorizer.error = JevError("typesafe systemone failed")
    handlers = _handlers(FakeQueue(), categorizer=categorizer)

    with pytest.raises(RetryableJobError, match="jev_unavailable"):
        handlers[CATEGORIZE_CLAIM_JOB]({"claim_id": str(uuid4())})


def test_catch_up_enqueues_pending_reviews_and_claim_only_provisionals() -> None:
    queue = FakeQueue()
    categorizer = FakeCategorizer()
    handlers = _handlers(queue, categorizer=categorizer)
    handlers[JEV_CATCH_UP_JOB]({"run_date": "2026-09-18"})
    assert queue.enqueued == []

    pending_id = uuid4()
    claim_id = uuid4()
    categorizer.pending = (pending_id,)
    categorizer.pending_claims = (claim_id,)
    handlers[JEV_CATCH_UP_JOB]({"run_date": "2026-09-18"})
    assert queue.enqueued == [
        (CATEGORIZE_TRANSACTION_JOB, {"transaction_id": str(pending_id)}, str(pending_id)),
        (CATEGORIZE_CLAIM_JOB, {"claim_id": str(claim_id)}, str(claim_id)),
    ]


def test_catchup_scheduler_is_due_at_or_after_local_hour() -> None:
    scheduler = JevCatchupScheduler(hour=21, timezone=ZoneInfo("Asia/Singapore"))
    before = datetime(2026, 9, 18, 12, 59, tzinfo=ZoneInfo("Asia/Singapore"))
    at_hour = datetime(2026, 9, 18, 21, 0, tzinfo=ZoneInfo("Asia/Singapore"))
    later = datetime(2026, 9, 18, 22, 15, tzinfo=ZoneInfo("Asia/Singapore"))
    next_day = datetime(2026, 9, 19, 21, 0, tzinfo=ZoneInfo("Asia/Singapore"))

    assert scheduler.catchup_date(before) is None
    assert scheduler.catchup_date(at_hour) == "2026-09-18"
    assert scheduler.catchup_date(later) is None
    assert scheduler.catchup_date(next_day) == "2026-09-19"


def test_enqueue_catch_up_uses_run_date_dedupe() -> None:
    queue = FakeQueue()
    enqueue_jev_catch_up(queue, "2026-09-18")
    assert queue.enqueued == [(JEV_CATCH_UP_JOB, {"run_date": "2026-09-18"}, "2026-09-18")]


def test_nightly_catch_up_also_enqueues_recurring_detection() -> None:
    queue = FakeQueue()
    enqueue_scheduled_catch_up(queue, None)
    assert queue.enqueued == []

    enqueue_scheduled_catch_up(queue, "2026-09-18")
    assert queue.enqueued == [
        (JEV_CATCH_UP_JOB, {"run_date": "2026-09-18"}, "2026-09-18"),
        (
            DETECT_RECURRING_SERIES_JOB,
            {"run_key": "2026-09-18"},
            "recurring-detect:2026-09-18",
        ),
    ]


def test_recurring_handlers_match_and_detect() -> None:
    queue = FakeQueue()
    recurrings = FakeRecurrings()
    handlers = _handlers(queue, recurrings=recurrings)
    transaction_id = uuid4()

    handlers[MATCH_RECURRING_TRANSACTION_JOB]({"transaction_id": str(transaction_id)})
    handlers[DETECT_RECURRING_SERIES_JOB]({"run_key": "2026-09-18"})

    assert recurrings.matched == [transaction_id]
    assert recurrings.detected == 1
    with pytest.raises(TerminalJobError, match="invalid_recurring_job"):
        handlers[MATCH_RECURRING_TRANSACTION_JOB]({})


def test_webhook_notifier_is_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("billzebub.jev_webhook")
