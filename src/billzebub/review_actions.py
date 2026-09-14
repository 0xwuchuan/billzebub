"""Route Pending Review decisions to the workflow that owns their side effects."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from billzebub.jobs import JobQueue
from billzebub.persistence.models import Extraction, PendingReview
from billzebub.reconciliation import Reconciliation
from billzebub.reviews import (
    PendingReviewRecord,
    PendingReviewStatus,
    ReviewDecision,
    ReviewError,
    ReviewInbox,
)
from billzebub.statement_extraction import ExtractionStatus, StatementExtraction

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class ReviewActionError(ValueError):
    """A Pending Review cannot be resolved by the generic browser action."""


class ReviewConfigurationRequiredError(ReviewActionError):
    """A permitted decision needs owner configuration outside this decide API."""

    def __init__(
        self,
        review: PendingReviewRecord,
        *,
        next_step: str,
        command: str,
        problem_code: str,
    ) -> None:
        super().__init__("owner configuration is required before this Review can close")
        self.review = review
        self.next_step = next_step
        self.command = command
        self.problem_code = problem_code


class ReviewActions:
    """Prevent a generic resolve button from bypassing specialized workflow policy."""

    _RECONCILIATION_CONDITIONS = frozenset({"reconciliation_ambiguous", "real_time_unconfirmed"})
    _EXTRACTION_DECISIONS = frozenset({"retry_after_adapter_update", "exclude_source_artifact"})
    _REPROCESS_DECISIONS = frozenset({"approve_exact_diff", "keep_previous_extraction"})
    _UNMAPPED_CARD_CONDITION = "apple_wallet_unmapped_card"
    _MISSING_PAYLAH_CONDITION = "paylah_account_missing"
    _AMBIGUOUS_PAYLAH_CONDITION = "paylah_account_ambiguous"
    _CONFIGURE_CARD_ALIAS = "configure_card_alias"
    _CONFIGURE_PAYLAH_ACCOUNT = "configure_paylah_account"
    _CARD_ALIAS_COMMAND = "billzebub account apple-wallet-alias"
    _PAYLAH_COMMAND = "billzebub account create-paylah"

    def __init__(
        self,
        database: Database,
        *,
        extraction: StatementExtraction | None = None,
        queue: JobQueue | None = None,
    ) -> None:
        self._database = database
        self._inbox = ReviewInbox(database)
        self._reconciliation = Reconciliation(database)
        self._extraction = extraction
        self._queue = queue if queue is not None else JobQueue(database)

    def decide(self, command: ReviewDecision) -> PendingReviewRecord:
        condition_code = self._condition_code(command.review_id)
        if condition_code in self._RECONCILIATION_CONDITIONS:
            return self._reconciliation.decide(command).review
        if condition_code.startswith("agent_proposal:"):
            return self._inbox.decide(command)
        if condition_code == "categorization_needed":
            raise ReviewActionError(
                "categorization reviews are resolved by categorizing the Transaction"
            )
        if condition_code.startswith("statement_extraction:"):
            return self._decide_extraction_failure(command)
        if condition_code.startswith("statement_reprocess:"):
            return self._decide_reprocess(command)
        if condition_code == self._UNMAPPED_CARD_CONDITION:
            raise self._configuration_required(
                command,
                permitted=frozenset({self._CONFIGURE_CARD_ALIAS}),
                expected_choice=self._CONFIGURE_CARD_ALIAS,
                next_step="configure_via_setup",
                cli_command=self._CARD_ALIAS_COMMAND,
                problem_code="card_alias_configuration_required",
            )
        if condition_code in {self._MISSING_PAYLAH_CONDITION, self._AMBIGUOUS_PAYLAH_CONDITION}:
            raise self._configuration_required(
                command,
                permitted=frozenset({self._CONFIGURE_PAYLAH_ACCOUNT}),
                expected_choice=self._CONFIGURE_PAYLAH_ACCOUNT,
                next_step="configure_via_setup",
                cli_command=self._PAYLAH_COMMAND,
                problem_code="paylah_account_configuration_required",
            )
        raise ReviewActionError("Pending Review requires a specialized workflow")

    def _decide_extraction_failure(self, command: ReviewDecision) -> PendingReviewRecord:
        review = self._require_open_decision(command, self._EXTRACTION_DECISIONS)
        if review.subject_type != "extraction":
            raise ReviewError("Pending Review is not a statement Extraction decision")
        if command.choice == "exclude_source_artifact":
            return self._inbox.decide(command)
        if command.choice != "retry_after_adapter_update":
            raise ReviewError("decision is not permitted for this Pending Review")

        failed_id, artifact_id, account_id = self._failed_extraction_refs(review.subject_id)
        outcome = self._require_extraction().extract(
            artifact_id=artifact_id,
            financial_account_id=account_id,
        )
        if outcome.duplicate and outcome.extraction_id == failed_id:
            raise ReviewActionError("retry_after_adapter_update requires an adapter version change")
        resolved = self._inbox.decide(command)
        if outcome.status is ExtractionStatus.ACCEPTED:
            self._enqueue_reconciliation(account_id)
        return resolved

    def _decide_reprocess(self, command: ReviewDecision) -> PendingReviewRecord:
        review = self._require_open_decision(command, self._REPROCESS_DECISIONS)
        if review.subject_type != "source_artifact":
            raise ReviewError("Pending Review is not a statement reprocess decision")
        if command.choice == "keep_previous_extraction":
            return self._inbox.decide(command)
        if command.choice != "approve_exact_diff":
            raise ReviewError("decision is not permitted for this Pending Review")

        account_id = self._reprocess_account_id(review.condition_code)
        candidate_hash = review.context.get("candidate_hash")
        if not isinstance(candidate_hash, str) or not candidate_hash.strip():
            raise ReviewError("Pending Review is missing a reprocess candidate")
        outcome = self._require_extraction().extract(
            artifact_id=review.subject_id,
            financial_account_id=account_id,
            approved_reprocess_hash=candidate_hash,
        )
        if outcome.status is not ExtractionStatus.ACCEPTED:
            raise ReviewActionError("reprocess approval did not accept an Extraction")
        self._enqueue_reconciliation(account_id)
        return self._resolved_or_current(command)

    def _configuration_required(
        self,
        decision: ReviewDecision,
        *,
        permitted: frozenset[str],
        expected_choice: str,
        next_step: str,
        cli_command: str,
        problem_code: str,
    ) -> ReviewConfigurationRequiredError:
        review = self._require_open_decision(decision, permitted)
        if decision.choice != expected_choice:
            raise ReviewError("decision is not permitted for this Pending Review")
        return ReviewConfigurationRequiredError(
            review,
            next_step=next_step,
            command=cli_command,
            problem_code=problem_code,
        )

    def _require_open_decision(
        self,
        command: ReviewDecision,
        permitted: frozenset[str],
    ) -> PendingReviewRecord:
        review = self._record(command.review_id)
        if review.status is not PendingReviewStatus.PENDING:
            raise ReviewError("Pending Review is no longer Pending")
        if command.expected_version != review.version:
            raise ReviewError("Pending Review version is stale")
        if command.choice not in review.allowed_decisions or command.choice not in permitted:
            raise ReviewError("decision is not permitted for this Pending Review")
        return review

    def _failed_extraction_refs(self, extraction_id: UUID) -> tuple[UUID, UUID, UUID]:
        with self._database.transaction() as session:
            extraction = session.get(Extraction, extraction_id)
            if extraction is None:
                raise ReviewError("statement Extraction was not found")
            if (
                extraction.status != ExtractionStatus.FAILED.value
                or extraction.financial_account_id is None
            ):
                raise ReviewError("Pending Review is not a failed statement Extraction")
            return extraction.id, extraction.artifact_id, extraction.financial_account_id

    def _resolved_or_current(self, command: ReviewDecision) -> PendingReviewRecord:
        review = self._record(command.review_id)
        if review.status is PendingReviewStatus.PENDING:
            return self._inbox.decide(command)
        return review

    def _record(self, review_id: UUID) -> PendingReviewRecord:
        with self._database.transaction() as session:
            review = session.get(PendingReview, review_id)
            if review is None:
                raise ReviewError("Pending Review was not found")
            return ReviewInbox._record(review)

    def _require_extraction(self) -> StatementExtraction:
        if self._extraction is None:
            raise ReviewActionError("Pending Review requires a specialized workflow")
        return self._extraction

    def _enqueue_reconciliation(self, account_id: UUID) -> None:
        self._queue.enqueue(
            "reconcile_financial_account",
            {"financial_account_id": str(account_id)},
            dedupe_key=str(account_id),
        )

    def _condition_code(self, review_id: UUID) -> str:
        with self._database.transaction() as session:
            condition_code = session.scalar(
                select(PendingReview.condition_code).where(PendingReview.id == review_id)
            )
        if condition_code is None:
            raise ReviewError("Pending Review was not found")
        return condition_code

    @staticmethod
    def _reprocess_account_id(condition_code: str) -> UUID:
        prefix, separator, account = condition_code.partition(":")
        if prefix != "statement_reprocess" or separator != ":" or not account:
            raise ReviewError("Pending Review is not a statement reprocess decision")
        try:
            return UUID(account)
        except ValueError as error:
            raise ReviewError("Pending Review is not a statement reprocess decision") from error
