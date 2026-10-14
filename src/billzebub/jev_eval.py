"""Read-only precision and coverage of historical Jev choices.

Choice confidence is already ``(p_max - 1/n) / (1 - 1/n)``. This report does
not change the 0.5 apply floor. It only compares stored choices with the
Category that eventually stuck on the Transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from billzebub.jev import normalize_category_label
from billzebub.persistence.models import (
    Category,
    CategorySplit,
    FinancialTransaction,
    JevCategorizationAttempt,
    TransactionVersion,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from billzebub.persistence.database import Database

DEFAULT_EVAL_THRESHOLDS = (
    Decimal("0.5"),
    Decimal("0.6"),
    Decimal("0.7"),
    Decimal("0.8"),
    Decimal("0.9"),
    Decimal("0.95"),
)


@dataclass(frozen=True, slots=True)
class ThresholdObservation:
    confidence: Decimal | None
    choice: str | None
    final_category: str | None


@dataclass(frozen=True, slots=True)
class ThresholdStat:
    threshold: Decimal
    covered: int
    total: int
    matches: int

    @property
    def coverage(self) -> Decimal | None:
        if self.total == 0:
            return None
        return Decimal(self.covered) / Decimal(self.total)

    @property
    def precision(self) -> Decimal | None:
        if self.covered == 0:
            return None
        return Decimal(self.matches) / Decimal(self.covered)


def choice_matches_category(choice: str, final_category: str) -> bool:
    """True when the raw Choice is the final Category name or a path to it."""
    folded_choice = normalize_category_label(choice)
    folded_final = normalize_category_label(final_category)
    if not folded_choice or not folded_final:
        return False
    if folded_choice == folded_final:
        return True
    leaf = folded_choice.split(">")[-1].split("/")[-1].strip()
    return leaf == folded_final


def evaluate_thresholds(
    rows: tuple[ThresholdObservation, ...] | list[ThresholdObservation],
    thresholds: tuple[Decimal, ...] = DEFAULT_EVAL_THRESHOLDS,
) -> tuple[ThresholdStat, ...]:
    """Coverage is the share of decided attempts at or above the threshold.

    An attempt counts when it has a confidence and the Transaction now has one
    Category. It is covered at a threshold when that confidence is at least the
    threshold and Jev returned a Choice. Precision is the share of those covered
    Choices that name the Category on the Transaction today.
    """
    considered = tuple(row for row in rows if row.confidence is not None and row.final_category)
    stats: list[ThresholdStat] = []
    for threshold in thresholds:
        covered = tuple(
            row
            for row in considered
            if row.confidence is not None
            and row.confidence >= threshold
            and row.choice
            and row.choice.strip()
        )
        matches = sum(
            1
            for row in covered
            if row.choice is not None
            and row.final_category is not None
            and choice_matches_category(row.choice, row.final_category)
        )
        stats.append(
            ThresholdStat(
                threshold=threshold,
                covered=len(covered),
                total=len(considered),
                matches=matches,
            )
        )
    return tuple(stats)


def format_threshold_stats(stats: tuple[ThresholdStat, ...] | list[ThresholdStat]) -> str:
    if not stats:
        return "threshold evaluations=0"
    lines = []
    for stat in stats:
        coverage = _ratio(stat.coverage)
        precision = _ratio(stat.precision)
        lines.append(
            f"threshold={stat.threshold:.2f} coverage={coverage} precision={precision} "
            f"covered={stat.covered} total={stat.total}"
        )
    return "\n".join(lines)


def load_threshold_observations(session: Session) -> tuple[ThresholdObservation, ...]:
    """Read attempts and current Categories. Does not insert or update."""
    rows = session.execute(
        select(
            JevCategorizationAttempt.id,
            JevCategorizationAttempt.choice_confidence,
            JevCategorizationAttempt.choice,
            Category.name,
            Category.parent_id,
        )
        .join(
            FinancialTransaction,
            FinancialTransaction.id == JevCategorizationAttempt.transaction_id,
        )
        .join(
            TransactionVersion,
            (TransactionVersion.transaction_id == FinancialTransaction.id)
            & (TransactionVersion.version == FinancialTransaction.current_version),
        )
        .join(CategorySplit, CategorySplit.transaction_version_id == TransactionVersion.id)
        .join(Category, Category.id == CategorySplit.category_id)
        .where(JevCategorizationAttempt.transaction_id.is_not(None))
    ).all()
    grouped: dict[object, tuple[Decimal | None, str | None, set[str]]] = {}
    for attempt_id, confidence, choice, name, parent_id in rows:
        confidence_value, choice_value, names = grouped.get(attempt_id, (confidence, choice, set()))
        if not (parent_id is None and name == "Uncategorized"):
            names.add(name)
        elif not names:
            names.add("Uncategorized")
        grouped[attempt_id] = (confidence_value, choice_value, names)
    observations: list[ThresholdObservation] = []
    for confidence, choice, names in grouped.values():
        real = {name for name in names if name != "Uncategorized"}
        if len(real) == 1:
            final_name = next(iter(real))
        elif len(real) == 0 and names == {"Uncategorized"}:
            final_name = "Uncategorized"
        else:
            continue
        observations.append(
            ThresholdObservation(
                confidence=confidence,
                choice=choice,
                final_category=final_name,
            )
        )
    return tuple(observations)


def eval_threshold_report(database: Database) -> str:
    with database.transaction() as session:
        observations = load_threshold_observations(session)
    return format_threshold_stats(evaluate_thresholds(observations))


def _ratio(value: Decimal | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"
