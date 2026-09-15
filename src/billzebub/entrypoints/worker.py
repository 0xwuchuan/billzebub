"""Run the Billzebub worker process."""

from __future__ import annotations

import logging
import signal
import socket
from datetime import UTC, datetime, timedelta
from threading import Event
from typing import Any, Protocol
from uuid import UUID

from billzebub.artifact_capture import ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.categorizer import (
    AutoCategorizer,
    CategorizerError,
    enqueue_transaction_categorization,
)
from billzebub.config import Settings
from billzebub.jobs import EnqueuedJob, JobQueue
from billzebub.persistence.database import Database
from billzebub.reconciliation import Reconciliation, ReconciliationRun
from billzebub.statement_adapters import configured_statement_adapters
from billzebub.statement_extraction import (
    ExtractionOutcome,
    ExtractionStatus,
    StatementAdapterRegistry,
    StatementExtraction,
)
from billzebub.statement_inbox import StatementInbox
from billzebub.worker import JobHandler, TerminalJobError, Worker


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


def worker_handlers(
    queue: JobEnqueuer,
    extraction: StatementExtractionRuntime,
    reconciliation: ReconciliationRuntime,
    categorizer: TransactionCategorizerRuntime,
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

    def categorize_transaction(payload: dict[str, Any]) -> None:
        try:
            transaction_id = UUID(str(payload["transaction_id"]))
        except (KeyError, ValueError) as error:
            raise TerminalJobError("invalid_categorize_job") from error
        try:
            categorizer.categorize_transaction(transaction_id)
        except CategorizerError as error:
            raise TerminalJobError("invalid_categorize_job") from error

    return {
        "extract_statement": extract_statement,
        "reconcile_financial_account": reconcile_financial_account,
        "categorize_transaction": categorize_transaction,
    }


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
    categorizer = AutoCategorizer(
        database,
        min_confidence=settings.categorizer_min_confidence,
        enabled=settings.categorizer_enabled,
    )
    inbox = StatementInbox(
        database,
        ArtifactCapture(artifact_store, database),
        queue,
        inbox_root=settings.statement_inbox_root,
        stable_for=timedelta(seconds=settings.statement_stable_seconds),
    )

    worker = Worker(
        queue,
        handlers=worker_handlers(queue, extraction, reconciliation, categorizer),
        worker_id=f"{socket.gethostname()}:{id(stop)}",
        poll_seconds=settings.worker_poll_seconds,
    )
    try:
        while not stop.is_set():
            try:
                inbox.poll(datetime.now(UTC))
            except Exception:
                logging.error("statement inbox poll failed")
            if not worker.run_once():
                stop.wait(settings.worker_poll_seconds)
    finally:
        database.close()


if __name__ == "__main__":
    main()
