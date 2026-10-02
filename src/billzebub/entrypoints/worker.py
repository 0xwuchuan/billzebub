"""Run the Billzebub worker process."""

from __future__ import annotations

import logging
import os
import signal
import socket
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from billzebub.artifact_capture import ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.config import Settings
from billzebub.jev import (
    JevClientConfig,
    JevConfigurationError,
    JevError,
    JevProposer,
    resolve_typesafe_api_key,
)
from billzebub.jev_categorizer import (
    CATEGORIZE_CLAIM_JOB,
    CATEGORIZE_TRANSACTION_JOB,
    JEV_CATCH_UP_JOB,
    CategorizerError,
    JevCatchupScheduler,
    JevCategorizer,
    enqueue_jev_catch_up,
    enqueue_transaction_categorization,
)
from billzebub.jobs import EnqueuedJob, JobQueue
from billzebub.persistence.database import Database
from billzebub.reconciliation import Reconciliation, ReconciliationRun
from billzebub.recurrings import (
    DETECT_RECURRING_SERIES_JOB,
    MATCH_RECURRING_TRANSACTION_JOB,
    Recurrings,
    enqueue_recurring_detection,
    enqueue_recurring_match,
)
from billzebub.statement_adapters import configured_statement_adapters
from billzebub.statement_extraction import (
    ExtractionOutcome,
    ExtractionStatus,
    StatementAdapterRegistry,
    StatementExtraction,
)
from billzebub.statement_inbox import StatementInbox
from billzebub.worker import JobHandler, RetryableJobError, TerminalJobError, Worker

logger = logging.getLogger(__name__)


class JobEnqueuer(Protocol):
    def enqueue(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        dedupe_key: str | None = None,
        max_attempts: int = 5,
        available_at: datetime | None = None,
    ) -> EnqueuedJob: ...


class StatementExtractionRuntime(Protocol):
    def extract(
        self,
        *,
        artifact_id: UUID,
        financial_account_id: UUID,
    ) -> ExtractionOutcome: ...


class ReconciliationRuntime(Protocol):
    def reconcile_account(self, financial_account_id: UUID) -> ReconciliationRun: ...


class TransactionCategorizerRuntime(Protocol):
    def categorize_transaction(self, transaction_id: UUID) -> object: ...

    def categorize_claim(self, claim_id: UUID) -> object: ...

    def enqueue_pending(self, queue: JobEnqueuer) -> int: ...


class RecurringRuntime(Protocol):
    def match_transaction(self, transaction_id: UUID) -> object: ...

    def detect(self) -> object: ...


def enqueue_scheduled_catch_up(queue: JobEnqueuer, run_date: str | None) -> None:
    """Queue the nightly Jev catch-up and the recurring detector together."""
    if run_date is None:
        return
    enqueue_jev_catch_up(queue, run_date)
    enqueue_recurring_detection(queue, run_date)


def worker_handlers(
    queue: JobEnqueuer,
    extraction: StatementExtractionRuntime,
    reconciliation: ReconciliationRuntime,
    categorizer: TransactionCategorizerRuntime,
    recurrings: RecurringRuntime,
) -> dict[str, JobHandler]:
    """Build durable pipeline handlers without exposing worker mechanics."""

    def extract_statement(payload: dict[str, Any]) -> None:
        try:
            artifact_id = UUID(str(payload["artifact_id"]))
            account_id = UUID(str(payload["financial_account_id"]))
        except (KeyError, ValueError) as error:
            raise TerminalJobError("invalid_statement_job") from error
        outcome = extraction.extract(
            artifact_id=artifact_id,
            financial_account_id=account_id,
        )
        if outcome.status is ExtractionStatus.ACCEPTED:
            queue.enqueue(
                "reconcile_financial_account",
                {"financial_account_id": str(account_id)},
                dedupe_key=str(account_id),
            )

    def reconcile_financial_account(payload: dict[str, Any]) -> None:
        try:
            account_id = UUID(str(payload["financial_account_id"]))
        except (KeyError, ValueError) as error:
            raise TerminalJobError("invalid_reconciliation_job") from error
        run = reconciliation.reconcile_account(account_id)
        for confirmation in run.confirmations:
            enqueue_transaction_categorization(queue, confirmation.transaction_id)
            enqueue_recurring_match(queue, confirmation.transaction_id)
        if run.confirmations:
            enqueue_recurring_detection(queue, f"reconcile:{account_id}")

    def categorize_transaction(payload: dict[str, Any]) -> None:
        try:
            transaction_id = UUID(str(payload["transaction_id"]))
        except (KeyError, ValueError) as error:
            raise TerminalJobError("invalid_categorize_job") from error
        try:
            categorizer.categorize_transaction(transaction_id)
        except JevError as error:
            raise RetryableJobError("jev_unavailable", timedelta(seconds=30)) from error
        except CategorizerError as error:
            raise TerminalJobError("invalid_categorize_job") from error

    def categorize_claim(payload: dict[str, Any]) -> None:
        try:
            claim_id = UUID(str(payload["claim_id"]))
        except (KeyError, ValueError) as error:
            raise TerminalJobError("invalid_categorize_job") from error
        try:
            categorizer.categorize_claim(claim_id)
        except JevError as error:
            raise RetryableJobError("jev_unavailable", timedelta(seconds=30)) from error
        except CategorizerError as error:
            raise TerminalJobError("invalid_categorize_job") from error

    def jev_catch_up(payload: dict[str, Any]) -> None:
        del payload
        queued = categorizer.enqueue_pending(queue)
        if queued:
            logger.info("jev catch-up queued %s categorizations", queued)

    def match_recurring_transaction(payload: dict[str, Any]) -> None:
        try:
            transaction_id = UUID(str(payload["transaction_id"]))
        except (KeyError, ValueError) as error:
            raise TerminalJobError("invalid_recurring_job") from error
        recurrings.match_transaction(transaction_id)

    def detect_recurring_series(payload: dict[str, Any]) -> None:
        del payload
        recurrings.detect()

    return {
        "extract_statement": extract_statement,
        "reconcile_financial_account": reconcile_financial_account,
        CATEGORIZE_TRANSACTION_JOB: categorize_transaction,
        CATEGORIZE_CLAIM_JOB: categorize_claim,
        JEV_CATCH_UP_JOB: jev_catch_up,
        MATCH_RECURRING_TRANSACTION_JOB: match_recurring_transaction,
        DETECT_RECURRING_SERIES_JOB: detect_recurring_series,
    }


def jev_proposer_from_settings(settings: Settings) -> JevProposer | None:
    try:
        key = resolve_typesafe_api_key(os.environ)
    except JevConfigurationError as error:
        raise SystemExit(f"jev configuration is invalid: {error}") from error
    if not key:
        logger.warning("jev categorizer disabled: TypeSafe API key is not configured")
        return None
    return JevProposer(
        JevClientConfig(
            typesafe_api_key=key,
            model=settings.jev_model,
            min_confidence=settings.jev_min_confidence,
            timeout_seconds=settings.jev_timeout_seconds,
        )
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    database = Database(settings)
    stop = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    queue = JobQueue(database)
    artifact_store = ContentAddressedStore(
        settings.artifact_root,
        max_bytes=settings.artifact_max_bytes,
    )
    extraction = StatementExtraction(
        database,
        artifact_store,
        StatementAdapterRegistry(configured_statement_adapters()),
        password_root=settings.statement_password_root,
    )
    reconciliation = Reconciliation(database)
    categorizer = JevCategorizer(database, jev_proposer_from_settings(settings))
    recurrings = Recurrings(database)
    inbox = StatementInbox(
        database,
        ArtifactCapture(artifact_store, database),
        queue,
        inbox_root=settings.statement_inbox_root,
        stable_for=timedelta(seconds=settings.statement_stable_seconds),
    )
    catchup = JevCatchupScheduler(
        hour=settings.jev_catchup_hour,
        timezone=ZoneInfo(settings.jev_catchup_timezone),
    )

    worker = Worker(
        queue,
        handlers=worker_handlers(queue, extraction, reconciliation, categorizer, recurrings),
        worker_id=f"{socket.gethostname()}:{id(stop)}",
        poll_seconds=settings.worker_poll_seconds,
    )
    try:
        while not stop.is_set():
            try:
                inbox.poll(datetime.now(UTC))
            except Exception:
                logging.error("statement inbox poll failed")
            run_date = catchup.catchup_date(datetime.now(UTC))
            enqueue_scheduled_catch_up(queue, run_date)
            if not worker.run_once():
                stop.wait(settings.worker_poll_seconds)
    finally:
        database.close()


if __name__ == "__main__":
    main()
