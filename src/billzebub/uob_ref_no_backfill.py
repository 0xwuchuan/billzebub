"""One-shot audited rewrite of UOB statement Counterparties with a trailing Ref No."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from uuid6 import uuid7

from billzebub.financial_history import Correction, FinancialHistory
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    AuditActor,
    AuditActorKind,
    Claim,
    Extraction,
    FinancialTransaction,
    TransactionClaim,
    TransactionVersion,
)
from billzebub.statement_adapters.uob_ref_no import rewrite_uob_statement_ref_no

UOB_CREDIT_ADAPTER_KEY = "uob-credit-card"
_SYSTEM_ACTOR_KEY = "uob-statement-ref-no"
_CORRECTION_REASON = "Strip trailing UOB statement Ref No. from Counterparty"


@dataclass(frozen=True, slots=True)
class UobRefNoBackfillReport:
    rewritten_transaction_ids: tuple[UUID, ...]
    skipped_empty_transaction_ids: tuple[UUID, ...]
    dry_run: bool


class UobRefNoBackfill:
    """Apply Corrections for current UOB statement Counterparties that still have Ref No."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._history = FinancialHistory(database)

    def run(self, *, dry_run: bool = True) -> UobRefNoBackfillReport:
        rewritten: list[UUID] = []
        skipped_empty: list[UUID] = []
        actor_id = None if dry_run else self._system_actor_id()
        for transaction_id, counterparty in self._current_uob_counterparties():
            target = rewrite_uob_statement_ref_no(counterparty)
            if target is None:
                skipped_empty.append(transaction_id)
                continue
            if target == counterparty:
                continue
            if not dry_run:
                if actor_id is None:
                    raise RuntimeError("UOB Ref No. backfill is missing a system actor")
                self._rewrite(transaction_id, actor_id)
            rewritten.append(transaction_id)
        return UobRefNoBackfillReport(
            rewritten_transaction_ids=tuple(rewritten),
            skipped_empty_transaction_ids=tuple(skipped_empty),
            dry_run=dry_run,
        )

    def _current_uob_counterparties(self) -> tuple[tuple[UUID, str], ...]:
        with self._database.transaction() as session:
            uob_statement_transactions = (
                select(TransactionClaim.transaction_id)
                .join(Claim, Claim.id == TransactionClaim.claim_id)
                .join(Extraction, Extraction.id == Claim.extraction_id)
                .where(
                    Claim.claim_type == "statement",
                    Extraction.adapter_key == UOB_CREDIT_ADAPTER_KEY,
                )
            )
            rows = session.execute(
                select(FinancialTransaction.id, TransactionVersion.counterparty)
                .join(
                    TransactionVersion,
                    (TransactionVersion.transaction_id == FinancialTransaction.id)
                    & (TransactionVersion.version == FinancialTransaction.current_version),
                )
                .where(FinancialTransaction.id.in_(uob_statement_transactions))
                .order_by(FinancialTransaction.id)
            ).all()
            return tuple((transaction_id, counterparty) for transaction_id, counterparty in rows)

    def _rewrite(self, transaction_id: UUID, actor_id: UUID) -> None:
        with self._database.transaction() as session:
            transaction = session.scalar(
                select(FinancialTransaction)
                .where(FinancialTransaction.id == transaction_id)
                .with_for_update()
            )
            if transaction is None:
                return
            version = session.scalar(
                select(TransactionVersion).where(
                    TransactionVersion.transaction_id == transaction.id,
                    TransactionVersion.version == transaction.current_version,
                )
            )
            if version is None:
                return
            target = rewrite_uob_statement_ref_no(version.counterparty)
            if target is None or target == version.counterparty:
                return
            self._history.correct_in_session(
                session,
                Correction(
                    transaction_id=transaction.id,
                    reason=_CORRECTION_REASON,
                    counterparty=target,
                    actor_id=actor_id,
                ),
            )

    def _system_actor_id(self) -> UUID:
        with self._database.transaction() as session:
            inserted = session.execute(
                insert(AuditActor)
                .values(
                    id=uuid7(),
                    kind=AuditActorKind.SYSTEM.value,
                    label="UOB statement Ref No. backfill",
                    external_key=_SYSTEM_ACTOR_KEY,
                )
                .on_conflict_do_nothing(
                    index_elements=(AuditActor.kind, AuditActor.external_key),
                )
                .returning(AuditActor.id)
            ).scalar_one_or_none()
            if inserted is not None:
                return inserted
            actor_id = session.scalar(
                select(AuditActor.id).where(
                    AuditActor.kind == AuditActorKind.SYSTEM.value,
                    AuditActor.external_key == _SYSTEM_ACTOR_KEY,
                )
            )
            if actor_id is None:
                raise RuntimeError("UOB Ref No. backfill audit actor disappeared")
            return actor_id
