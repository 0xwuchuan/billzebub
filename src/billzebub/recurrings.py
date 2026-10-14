"""Detection-first system of record for repeating spend.

Settled Transactions are clustered into proposed Recurring Series. Nothing is
activated until the owner confirms it. A dismissed cluster key is not proposed
again. A newly settled Transaction links to an active series when the
counterparty, amount tolerance, and next expected date agree. Detection also
backfills unlinked history onto an existing active series, including one the
owner created manually, when the normalized counterparty, amount, and cadence
agree, then recomputes the latest match and next expected date.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.money import Money
from billzebub.persistence.models import (
    Category,
    CategorySplit,
    FinancialAccount,
    FinancialTransaction,
    RecurringOccurrence,
    RecurringSeries,
    TransactionVersion,
)

if TYPE_CHECKING:
    from billzebub.persistence.database import Database

logger = logging.getLogger(__name__)

MATCH_RECURRING_TRANSACTION_JOB = "match_recurring_transaction"
DETECT_RECURRING_SERIES_JOB = "detect_recurring_series"
REPORTING_CURRENCY = "SGD"
MIN_HITS = 3
ABSOLUTE_TOLERANCE = Decimal("1")
RELATIVE_TOLERANCE = Decimal("0.02")
_WEEKLY = (5, 9)
_MONTHLY = (25, 35)
_YEARLY = (350, 380)
_SPEND_KINDS = frozenset({"expense", "transfer", "cash_withdrawal"})
_CADENCES = frozenset({"weekly", "monthly", "yearly", "custom_days"})
_STATUSES = frozenset({"proposed", "active", "paused", "ended", "dismissed"})
_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"active"}),
    "active": frozenset({"paused", "ended"}),
    "paused": frozenset({"active", "ended"}),
    "ended": frozenset(),
    "dismissed": frozenset(),
}
_STATUS_RANK = {"active": 0, "paused": 1, "ended": 2, "dismissed": 3, "proposed": 4}
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
# Letter prefix, a digit, then a long tail: ``p45ae6bd59``, not ``7eleven``.
_OPAQUE_REF_PATTERN = re.compile(r"^[a-z]*\d[a-z0-9]{6,}$")
_MERCHANT_LETTER_RUN = re.compile(r"[a-z]{4,}")
_COUNTERPARTY_NOISE = frozenset(
    {
        "card",
        "co",
        "com",
        "credit",
        "debit",
        "inc",
        "ltd",
        "mastercard",
        "payment",
        "posted",
        "pte",
        "purchase",
        "sg",
        "sgd",
        "singapore",
        "transaction",
        "visa",
        "www",
    }
)


class RecurringJobQueue(Protocol):
    def enqueue(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        dedupe_key: str | None = None,
        max_attempts: int = 5,
        available_at: datetime | None = None,
    ) -> object: ...


class RecurringError(ValueError):
    """Recurring series policy rejected a requested change."""


class RecurringNotFoundError(RecurringError):
    """The series or Transaction does not exist."""


class RecurringConflictError(RecurringError):
    """The change collides with an existing series or an illegal transition."""


@dataclass(frozen=True, slots=True)
class SpendObservation:
    transaction_id: UUID
    counterparty: str
    normalized_counterparty: str
    amount: Decimal
    currency: str
    effective_date: date
    financial_account_id: UUID
    category_id: UUID | None


@dataclass(frozen=True, slots=True)
class RecurringCluster:
    normalized_counterparty: str
    counterparty: str
    currency: str
    amount: Decimal
    amount_min: Decimal | None
    amount_max: Decimal | None
    cadence: str
    interval_days: int | None
    next_expected_date: date
    confidence: Decimal
    cluster_key: str
    primary_account_id: UUID
    category_id: UUID | None
    observations: tuple[SpendObservation, ...]

    @property
    def transaction_ids(self) -> tuple[UUID, ...]:
        return tuple(observation.transaction_id for observation in self.observations)

    @property
    def last_transaction_id(self) -> UUID:
        return self.observations[-1].transaction_id


@dataclass(frozen=True, slots=True)
class RecurringSeriesRecord:
    id: UUID
    counterparty: str
    amount: Money
    amount_min: Money | None
    amount_max: Money | None
    cadence: str
    interval_days: int | None
    next_expected_date: date
    category_id: UUID | None
    primary_account_id: UUID | None
    status: str
    source: str
    confidence: Decimal | None
    last_matched_tx_id: UUID | None
    last_amount: Money
    linked_count: int
    missed: bool
    notes: str | None
    cluster_key: str


@dataclass(frozen=True, slots=True)
class RecurringSummary:
    month: str
    total: Money
    upcoming: tuple[RecurringSeriesRecord, ...]


@dataclass(frozen=True, slots=True)
class RecurringDetection:
    proposed: int
    updated: int
    matched: int


@dataclass(frozen=True, slots=True)
class RecurringCreate:
    counterparty: str
    amount: Decimal
    currency: str
    cadence: str
    next_expected_date: date
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    interval_days: int | None = None
    category_id: UUID | None = None
    primary_account_id: UUID | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class RecurringUpdate:
    set_fields: frozenset[str]
    counterparty: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    cadence: str | None = None
    interval_days: int | None = None
    next_expected_date: date | None = None
    category_id: UUID | None = None
    primary_account_id: UUID | None = None
    notes: str | None = None
    status: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None


def _is_opaque_charge_ref(token: str) -> bool:
    """True for a long mixed per-charge reference such as ``p45ae6bd59``.

    Merchant words that merely contain digits (``7eleven``, ``24hourfitness``)
    include a four-letter run and stay. A reference has several digits and none.
    """
    if _OPAQUE_REF_PATTERN.fullmatch(token) is None:
        return False
    if _MERCHANT_LETTER_RUN.search(token) is not None:
        return False
    digit_count = sum(1 for character in token if character.isdigit())
    return any(character.isalpha() for character in token) and digit_count >= 3


def normalize_counterparty(value: str) -> str:
    """Fold a merchant label into the cluster and match key.

    Digit-only tokens and long mixed per-charge references are dropped so
    repeated charges that embed a unique ref still share one key.
    """
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()
    tokens = [
        token
        for token in _TOKEN_PATTERN.findall(folded)
        if token not in _COUNTERPARTY_NOISE
        and not token.isdigit()
        and len(token) > 1
        and not _is_opaque_charge_ref(token)
    ]
    return " ".join(tokens)[:300]


def amounts_within_tolerance(left: Decimal, right: Decimal) -> bool:
    """True when two spend amounts are within ±2% or ±1 currency unit."""
    difference = abs(left - right)
    limit = max(ABSOLUTE_TOLERANCE, RELATIVE_TOLERANCE * max(left, right))
    return difference <= limit


def amount_bucket(amount: Decimal) -> str:
    snapped = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return format(snapped, "f")


def build_cluster_key(normalized: str, currency: str, amount: Decimal, cadence: str) -> str:
    return f"{normalized[:240]}|{currency}|{amount_bucket(amount)}|{cadence}"


def match_window_days(cadence: str, interval_days: int | None) -> int:
    if cadence == "weekly":
        return 3
    if cadence == "monthly":
        return 7
    if cadence == "yearly":
        return 21
    interval = interval_days or 0
    return max(3, interval // 5)


def occurs_on_cadence(
    anchor: date,
    when: date,
    cadence: str,
    interval_days: int | None,
) -> bool:
    """True when ``when`` sits in the match window of a cadence slot from ``anchor``.

    Monthly and yearly slots step by calendar months, so a charge on the same
    day of an earlier month still matches. Weekly and custom cadences use a
    fixed day count. A date that misses every slot is not the series cadence.
    """
    window = match_window_days(cadence, interval_days)
    if cadence in {"monthly", "yearly"}:
        step = 1 if cadence == "monthly" else 12
        months = (when.year - anchor.year) * 12 + (when.month - anchor.month)
        nearest = _nearest_step(months, step)
        return any(
            abs((when - _add_months(anchor, (nearest + offset) * step)).days) <= window
            for offset in (-1, 0, 1)
        )
    if cadence == "weekly":
        period = 7
    elif cadence == "custom_days" and interval_days is not None and interval_days > 0:
        period = interval_days
    else:
        return False
    # Adjacent slots cover the whole timeline when the window is half a period,
    # so only the anchor slot is a real filter. Wider periods still walk the lattice.
    if 2 * window >= period - 1:
        return abs((when - anchor).days) <= window
    remainder = abs((when - anchor).days) % period
    return min(remainder, period - remainder) <= window


def advance_expected(start: date, cadence: str, interval_days: int | None) -> date:
    if cadence == "weekly":
        return start + timedelta(days=7)
    if cadence == "monthly":
        return _add_months(start, 1)
    if cadence == "yearly":
        return _add_months(start, 12)
    if interval_days is None or interval_days <= 0:
        raise RecurringError("custom cadence requires a positive interval")
    return start + timedelta(days=interval_days)


def guess_cadence(dates: list[date]) -> tuple[str, int | None] | None:
    """Name a regular interval from occurrence dates, or reject an irregular one."""
    ordered = sorted(dates)
    if len(ordered) < MIN_HITS:
        return None
    gaps = [(ordered[index] - ordered[index - 1]).days for index in range(1, len(ordered))]
    if any(gap <= 0 for gap in gaps):
        return None
    if all(_WEEKLY[0] <= gap <= _WEEKLY[1] for gap in gaps):
        return "weekly", None
    if all(_MONTHLY[0] <= gap <= _MONTHLY[1] for gap in gaps):
        return "monthly", None
    if all(_YEARLY[0] <= gap <= _YEARLY[1] for gap in gaps):
        return "yearly", None
    median_gap = _median_int(gaps)
    if median_gap < 2 or median_gap > 400:
        return None
    limit = max(
        2,
        int((Decimal(median_gap) * Decimal("0.15")).to_integral_value(rounding=ROUND_HALF_UP)),
    )
    if any(abs(gap - median_gap) > limit for gap in gaps):
        return None
    return "custom_days", median_gap


def series_confidence(hit_count: int, gaps: list[int], amounts: list[Decimal]) -> Decimal:
    median_gap = Decimal(_median_int(gaps))
    gap_penalty = max(Decimal(abs(gap - int(median_gap))) for gap in gaps) / median_gap
    regularity = max(Decimal(0), Decimal(1) - gap_penalty)
    median_amount = _median_decimal(amounts)
    spread = max(abs(amount - median_amount) for amount in amounts)
    tolerance = max(ABSOLUTE_TOLERANCE, RELATIVE_TOLERANCE * median_amount)
    stability = max(Decimal(0), Decimal(1) - (spread / tolerance))
    depth = min(Decimal(1), Decimal(hit_count) / Decimal(6))
    score = (regularity + stability + depth) / Decimal(3)
    raw = Decimal("0.55") + (Decimal("0.40") * score)
    return min(Decimal("0.99"), raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def build_clusters(observations: list[SpendObservation]) -> tuple[RecurringCluster, ...]:
    grouped: dict[tuple[str, str], list[SpendObservation]] = defaultdict(list)
    for observation in observations:
        if not observation.normalized_counterparty:
            continue
        grouped[(observation.normalized_counterparty, observation.currency)].append(observation)
    clusters: list[RecurringCluster] = []
    for (normalized, currency), rows in grouped.items():
        for amount_group in _cluster_amounts(rows):
            cluster = _cluster_from_rows(amount_group, normalized, currency)
            if cluster is not None:
                clusters.append(cluster)
    return tuple(clusters)


class Recurrings:
    """Own recurring detection, matching, and the owner REST operations."""

    def __init__(self, database: Database, *, reporting_timezone: str = "Asia/Singapore") -> None:
        self._database = database
        self._timezone = ZoneInfo(reporting_timezone)

    def list_series(self, *, status: str | None = None) -> tuple[RecurringSeriesRecord, ...]:
        if status is not None and status not in _STATUSES:
            raise RecurringError("status filter is invalid")
        with self._database.transaction() as session:
            statement = select(RecurringSeries)
            if status is not None:
                statement = statement.where(RecurringSeries.status == status)
            if status == "proposed":
                statement = statement.order_by(
                    RecurringSeries.confidence.desc(),
                    RecurringSeries.next_expected_date,
                    RecurringSeries.id,
                )
            else:
                statement = statement.order_by(
                    RecurringSeries.next_expected_date,
                    RecurringSeries.counterparty,
                    RecurringSeries.id,
                )
            rows = list(session.scalars(statement).all())
            return self._records(session, rows)

    def create_series(self, command: RecurringCreate) -> RecurringSeriesRecord:
        label = _clean_counterparty(command.counterparty)
        normalized = normalize_counterparty(label)
        currency = _clean_currency(command.currency)
        amount = _positive_amount(command.amount)
        amount_min, amount_max = _bounds(amount, command.amount_min, command.amount_max)
        interval_days = _interval_for(command.cadence, command.interval_days)
        notes = _clean_notes(command.notes)
        cluster_key = build_cluster_key(normalized, currency, amount, command.cadence)
        now = datetime.now(UTC)
        try:
            with self._database.transaction() as session:
                self._require_category(session, command.category_id)
                self._require_account(session, command.primary_account_id)
                if self._series_for_key(session, cluster_key) is not None:
                    raise RecurringConflictError("a series already exists for this cluster")
                series = RecurringSeries(
                    id=uuid7(),
                    counterparty=label,
                    normalized_counterparty=normalized,
                    cluster_key=cluster_key,
                    amount=amount,
                    amount_min=amount_min,
                    amount_max=amount_max,
                    currency=currency,
                    cadence=command.cadence,
                    interval_days=interval_days,
                    next_expected_date=command.next_expected_date,
                    category_id=command.category_id,
                    primary_account_id=command.primary_account_id,
                    status="active",
                    source="manual",
                    confidence=None,
                    last_matched_tx_id=None,
                    notes=notes,
                    missed=False,
                    updated_at=now,
                )
                session.add(series)
                session.flush()
                return self._record(session, series)
        except IntegrityError as error:
            raise RecurringConflictError("a series already exists for this cluster") from error

    def update_series(self, series_id: UUID, command: RecurringUpdate) -> RecurringSeriesRecord:
        with self._database.transaction() as session:
            series = self._locked(session, series_id)
            self._apply_update(session, series, command)
            session.flush()
            return self._record(session, series)

    def dismiss_series(self, series_id: UUID) -> RecurringSeriesRecord:
        with self._database.transaction() as session:
            series = self._locked(session, series_id)
            if series.status != "proposed":
                raise RecurringConflictError("only a proposed series can be dismissed")
            series.status = "dismissed"
            series.missed = False
            series.updated_at = datetime.now(UTC)
            session.flush()
            return self._record(session, series)

    def match_series(self, series_id: UUID, transaction_id: UUID) -> RecurringSeriesRecord:
        with self._database.transaction() as session:
            series = self._locked(session, series_id)
            if series.status not in {"active", "paused", "proposed"}:
                raise RecurringConflictError("this series cannot accept a match")
            observation = self._load_observation(session, transaction_id)
            if observation is None:
                raise RecurringNotFoundError("Transaction was not found")
            if observation.currency != series.currency:
                raise RecurringError("Transaction currency does not match the series")
            existing = self._occurrence_for_transaction(session, transaction_id)
            if existing is not None:
                if existing.series_id == series.id:
                    return self._record(session, series)
                raise RecurringConflictError("Transaction is already linked to a series")
            window = match_window_days(series.cadence, series.interval_days)
            earliest = series.next_expected_date - timedelta(days=window)
            advance = observation.effective_date >= earliest
            self._link(session, series, observation, match_kind="manual", advance=advance)
            session.flush()
            return self._record(session, series)

    def summary(self, *, limit: int = 5, as_of: date | None = None) -> RecurringSummary:
        if limit < 1 or limit > 50:
            raise RecurringError("upcoming limit is invalid")
        today = as_of or self._today()
        month_start = today.replace(day=1)
        month_end = _add_months(month_start, 1)
        with self._database.transaction() as session:
            amount_rows = session.execute(
                select(TransactionVersion.posted_amount)
                .join(
                    FinancialTransaction,
                    (TransactionVersion.transaction_id == FinancialTransaction.id)
                    & (TransactionVersion.version == FinancialTransaction.current_version),
                )
                .join(
                    RecurringOccurrence,
                    RecurringOccurrence.transaction_id == FinancialTransaction.id,
                )
                .join(RecurringSeries, RecurringSeries.id == RecurringOccurrence.series_id)
                .where(
                    RecurringSeries.status == "active",
                    TransactionVersion.effective_date >= month_start,
                    TransactionVersion.effective_date < month_end,
                    TransactionVersion.posted_currency == REPORTING_CURRENCY,
                )
            ).scalars()
            total = sum((abs(amount) for amount in amount_rows), Decimal(0))
            upcoming_rows = list(
                session.scalars(
                    select(RecurringSeries)
                    .where(RecurringSeries.status == "active")
                    .order_by(RecurringSeries.next_expected_date, RecurringSeries.id)
                    .limit(limit)
                ).all()
            )
            upcoming = self._records(session, upcoming_rows)
        return RecurringSummary(
            month=f"{today:%Y-%m}",
            total=Money(total, REPORTING_CURRENCY),
            upcoming=upcoming,
        )

    def match_transaction(
        self,
        transaction_id: UUID,
        *,
        as_of: date | None = None,
    ) -> RecurringSeriesRecord | None:
        """Attach one newly settled Transaction to an active series, if it fits."""
        today = as_of or self._today()
        with self._database.transaction() as session:
            observation = self._load_observation(session, transaction_id)
            if observation is None or self._occurrence_for_transaction(session, transaction_id):
                self._refresh_missed(session, today)
                return None
            rows = list(
                session.scalars(
                    select(RecurringSeries).where(RecurringSeries.status == "active")
                ).all()
            )
            series = _best_active(rows, observation)
            if series is None:
                self._refresh_missed(session, today)
                return None
            self._link(session, series, observation, match_kind="auto", advance=True)
            self._refresh_missed(session, today)
            return self._record(session, series)

    def detect(self, *, as_of: date | None = None) -> RecurringDetection:
        """Propose new series from settled history and backfill existing ones.

        Backfill links unlinked Transactions onto active series, including
        manual ones, and is safe to repeat: a second pass changes nothing.
        """
        today = as_of or self._today()
        with self._database.transaction() as session:
            result = self._detect(session, today)
        if result.proposed or result.updated or result.matched:
            logger.info(
                "recurring detection proposed %s updated %s matched %s",
                result.proposed,
                result.updated,
                result.matched,
            )
        return result

    def _detect(self, session: Session, today: date) -> RecurringDetection:
        observations = self._load_observations(session)
        series_rows = list(session.scalars(select(RecurringSeries)).all())
        linked = self._linked_ids(session)
        matched = self._backfill_existing_series(
            session,
            observations,
            series_rows,
            linked,
            today,
        )
        proposed = 0
        updated = 0
        for cluster in build_clusters(observations):
            existing = _find_existing(series_rows, cluster)
            unlinked = [
                observation.transaction_id
                for observation in cluster.observations
                if observation.transaction_id not in linked
            ]
            if existing is None:
                if not unlinked:
                    continue
                created = self._insert_proposed(session, cluster, linked)
                series_rows.append(created)
                proposed += 1
                continue
            if existing.status != "proposed":
                continue
            self._refresh_proposed(session, existing, cluster, linked)
            updated += 1
        self._refresh_missed(session, today)
        return RecurringDetection(proposed=proposed, updated=updated, matched=matched)

    def _backfill_existing_series(
        self,
        session: Session,
        observations: list[SpendObservation],
        series_rows: list[RecurringSeries],
        linked: set[UUID],
        today: date,
    ) -> int:
        """Link unlinked Transactions onto existing active or manual series.

        A match requires the normalized counterparty, currency, amount
        tolerance, and cadence. Dismissed, paused, ended, and proposed series
        are left alone. A Transaction already linked to a series is not moved.
        Schedule fields are recomputed from the latest linked charge, including
        when this pass links nothing new. Running this again, once the schedule
        already matches that charge, changes nothing.
        """
        matched = 0
        for observation in sorted(
            observations,
            key=lambda item: (item.effective_date, str(item.transaction_id)),
        ):
            if observation.transaction_id in linked:
                continue
            series = _best_backfill_series(series_rows, observation)
            if series is None:
                continue
            self._link(session, series, observation, match_kind="auto", advance=False)
            linked.add(observation.transaction_id)
            matched += 1
        session.flush()
        for series in series_rows:
            if _accepts_history_backfill(series):
                self._recompute_schedule(session, series, today)
        return matched

    def _recompute_schedule(self, session: Session, series: RecurringSeries, today: date) -> None:
        latest = _latest_linked_charge(session, series.id)
        if latest is None:
            return
        transaction_id, effective_date = latest
        next_expected = advance_expected(effective_date, series.cadence, series.interval_days)
        window = match_window_days(series.cadence, series.interval_days)
        missed = today > next_expected + timedelta(days=window)
        if (
            series.last_matched_tx_id == transaction_id
            and series.next_expected_date == next_expected
            and series.missed is missed
        ):
            return
        series.last_matched_tx_id = transaction_id
        series.next_expected_date = next_expected
        series.missed = missed
        series.updated_at = datetime.now(UTC)

    def _insert_proposed(
        self,
        session: Session,
        cluster: RecurringCluster,
        linked: set[UUID],
    ) -> RecurringSeries:
        now = datetime.now(UTC)
        series = RecurringSeries(
            id=uuid7(),
            counterparty=cluster.counterparty,
            normalized_counterparty=cluster.normalized_counterparty,
            cluster_key=cluster.cluster_key,
            amount=cluster.amount,
            amount_min=cluster.amount_min,
            amount_max=cluster.amount_max,
            currency=cluster.currency,
            cadence=cluster.cadence,
            interval_days=cluster.interval_days,
            next_expected_date=cluster.next_expected_date,
            category_id=cluster.category_id,
            primary_account_id=cluster.primary_account_id,
            status="proposed",
            source="detected",
            confidence=cluster.confidence,
            last_matched_tx_id=cluster.last_transaction_id,
            notes=None,
            missed=False,
            updated_at=now,
        )
        session.add(series)
        session.flush()
        self._link_cluster(session, series, cluster, linked)
        return series

    def _refresh_proposed(
        self,
        session: Session,
        series: RecurringSeries,
        cluster: RecurringCluster,
        linked: set[UUID],
    ) -> None:
        series.counterparty = cluster.counterparty
        series.normalized_counterparty = cluster.normalized_counterparty
        series.amount = cluster.amount
        series.amount_min = cluster.amount_min
        series.amount_max = cluster.amount_max
        series.cadence = cluster.cadence
        series.interval_days = cluster.interval_days
        series.next_expected_date = cluster.next_expected_date
        series.confidence = cluster.confidence
        series.primary_account_id = cluster.primary_account_id
        series.category_id = cluster.category_id
        series.last_matched_tx_id = cluster.last_transaction_id
        series.updated_at = datetime.now(UTC)
        self._link_cluster(session, series, cluster, linked)

    def _link_cluster(
        self,
        session: Session,
        series: RecurringSeries,
        cluster: RecurringCluster,
        linked: set[UUID],
    ) -> None:
        now = datetime.now(UTC)
        for observation in cluster.observations:
            if observation.transaction_id in linked:
                continue
            session.add(
                RecurringOccurrence(
                    id=uuid7(),
                    series_id=series.id,
                    transaction_id=observation.transaction_id,
                    matched_at=now,
                    match_kind="auto",
                )
            )
            linked.add(observation.transaction_id)

    def _link(
        self,
        session: Session,
        series: RecurringSeries,
        observation: SpendObservation,
        *,
        match_kind: str,
        advance: bool,
    ) -> None:
        now = datetime.now(UTC)
        session.add(
            RecurringOccurrence(
                id=uuid7(),
                series_id=series.id,
                transaction_id=observation.transaction_id,
                matched_at=now,
                match_kind=match_kind,
            )
        )
        if advance:
            series.next_expected_date = advance_expected(
                observation.effective_date,
                series.cadence,
                series.interval_days,
            )
            series.missed = False
            series.last_matched_tx_id = observation.transaction_id
        elif series.last_matched_tx_id is None:
            series.last_matched_tx_id = observation.transaction_id
        series.updated_at = now

    def _apply_update(
        self,
        session: Session,
        series: RecurringSeries,
        command: RecurringUpdate,
    ) -> None:
        if series.status == "dismissed":
            raise RecurringConflictError("a dismissed series cannot be edited")
        fields = command.set_fields
        if "counterparty" in fields:
            if command.counterparty is None:
                raise RecurringError("a Counterparty is required")
            label = _clean_counterparty(command.counterparty)
            series.counterparty = label
            series.normalized_counterparty = normalize_counterparty(label)
        if "currency" in fields:
            if command.currency is None:
                raise RecurringError("currency is required")
            series.currency = _clean_currency(command.currency)
        if "amount" in fields or "amount_min" in fields or "amount_max" in fields:
            amount = series.amount
            amount_min = series.amount_min
            amount_max = series.amount_max
            if "amount" in fields:
                if command.amount is None:
                    raise RecurringError("amount must be positive")
                amount = _positive_amount(command.amount)
            if "amount_min" in fields or "amount_max" in fields:
                if "amount_min" not in fields or "amount_max" not in fields:
                    raise RecurringError("amount range requires both minimum and maximum")
                amount_min, amount_max = _bounds(amount, command.amount_min, command.amount_max)
            elif (
                amount_min is not None
                and amount_max is not None
                and (amount < amount_min or amount > amount_max)
            ):
                raise RecurringError("amount must sit inside the minimum and maximum")
            series.amount = amount
            series.amount_min = amount_min
            series.amount_max = amount_max
        if "cadence" in fields or "interval_days" in fields:
            cadence = command.cadence if "cadence" in fields else series.cadence
            if cadence is None:
                raise RecurringError("cadence is invalid")
            interval_days = series.interval_days
            if "interval_days" in fields:
                interval_days = command.interval_days
            if "cadence" in fields and cadence != "custom_days":
                interval_days = None
            series.cadence = cadence
            series.interval_days = _interval_for(cadence, interval_days)
        if "next_expected_date" in fields:
            if command.next_expected_date is None:
                raise RecurringError("next expected date is required")
            series.next_expected_date = command.next_expected_date
        if "category_id" in fields:
            self._require_category(session, command.category_id)
            series.category_id = command.category_id
        if "primary_account_id" in fields:
            self._require_account(session, command.primary_account_id)
            series.primary_account_id = command.primary_account_id
        if "notes" in fields:
            series.notes = _clean_notes(command.notes)
        if "status" in fields:
            if command.status is None or command.status not in _STATUS_TRANSITIONS[series.status]:
                raise RecurringConflictError("status transition is not allowed")
            series.status = command.status
            if series.status != "active":
                series.missed = False
        series.updated_at = datetime.now(UTC)

    def _refresh_missed(self, session: Session, today: date) -> None:
        now = datetime.now(UTC)
        for series in session.scalars(select(RecurringSeries)).all():
            if series.status != "active":
                missed = False
            else:
                window = match_window_days(series.cadence, series.interval_days)
                missed = today > series.next_expected_date + timedelta(days=window)
            if series.missed != missed:
                series.missed = missed
                series.updated_at = now

    def _records(
        self,
        session: Session,
        rows: list[RecurringSeries],
    ) -> tuple[RecurringSeriesRecord, ...]:
        if not rows:
            return ()
        identifiers = [row.id for row in rows]
        count_rows = session.execute(
            select(RecurringOccurrence.series_id, func.count())
            .where(RecurringOccurrence.series_id.in_(identifiers))
            .group_by(RecurringOccurrence.series_id)
        ).all()
        counts = {series_id: int(count) for series_id, count in count_rows}
        last_amounts = self._last_amounts(session, rows)
        return tuple(_to_record(row, counts.get(row.id, 0), last_amounts[row.id]) for row in rows)

    def _record(self, session: Session, series: RecurringSeries) -> RecurringSeriesRecord:
        return self._records(session, [series])[0]

    def _last_amounts(self, session: Session, rows: list[RecurringSeries]) -> dict[UUID, Money]:
        transaction_ids = [
            row.last_matched_tx_id for row in rows if row.last_matched_tx_id is not None
        ]
        posted: dict[UUID, tuple[Decimal, str]] = {}
        if transaction_ids:
            amount_rows = session.execute(
                select(
                    FinancialTransaction.id,
                    TransactionVersion.posted_amount,
                    TransactionVersion.posted_currency,
                )
                .join(
                    TransactionVersion,
                    (TransactionVersion.transaction_id == FinancialTransaction.id)
                    & (TransactionVersion.version == FinancialTransaction.current_version),
                )
                .where(FinancialTransaction.id.in_(transaction_ids))
            ).all()
            posted = {
                transaction_id: (abs(amount), currency)
                for transaction_id, amount, currency in amount_rows
            }
        result: dict[UUID, Money] = {}
        for row in rows:
            matched = posted.get(row.last_matched_tx_id) if row.last_matched_tx_id else None
            if matched is None:
                result[row.id] = Money(row.amount, row.currency)
            else:
                amount, currency = matched
                result[row.id] = Money(amount, currency)
        return result

    def _load_observations(
        self,
        session: Session,
        transaction_id: UUID | None = None,
    ) -> list[SpendObservation]:
        statement = (
            select(
                FinancialTransaction.id,
                FinancialTransaction.financial_account_id,
                TransactionVersion.id,
                TransactionVersion.counterparty,
                TransactionVersion.posted_amount,
                TransactionVersion.posted_currency,
                TransactionVersion.effective_date,
            )
            .join(
                TransactionVersion,
                (TransactionVersion.transaction_id == FinancialTransaction.id)
                & (TransactionVersion.version == FinancialTransaction.current_version),
            )
            .where(
                TransactionVersion.posted_amount < 0,
                TransactionVersion.kind.in_(tuple(_SPEND_KINDS)),
            )
        )
        if transaction_id is not None:
            statement = statement.where(FinancialTransaction.id == transaction_id)
        rows = session.execute(statement).all()
        categories = self._categories_by_version(session, [row[2] for row in rows])
        observations: list[SpendObservation] = []
        for (
            transaction_id,
            account_id,
            version_id,
            counterparty,
            posted_amount,
            currency,
            effective_date,
        ) in rows:
            normalized = normalize_counterparty(counterparty)
            if not normalized:
                continue
            observations.append(
                SpendObservation(
                    transaction_id=transaction_id,
                    counterparty=" ".join(counterparty.split())[:300],
                    normalized_counterparty=normalized,
                    amount=abs(posted_amount),
                    currency=currency,
                    effective_date=effective_date,
                    financial_account_id=account_id,
                    category_id=categories.get(version_id),
                )
            )
        return observations

    def _load_observation(self, session: Session, transaction_id: UUID) -> SpendObservation | None:
        observations = self._load_observations(session, transaction_id)
        if not observations:
            return None
        return observations[0]

    def _categories_by_version(
        self,
        session: Session,
        version_ids: list[UUID],
    ) -> dict[UUID, UUID]:
        if not version_ids:
            return {}
        splits = session.execute(
            select(
                CategorySplit.transaction_version_id,
                CategorySplit.category_id,
                Category.name,
                Category.parent_id,
            )
            .join(Category, Category.id == CategorySplit.category_id)
            .where(CategorySplit.transaction_version_id.in_(version_ids))
        ).all()
        grouped: dict[UUID, list[UUID]] = defaultdict(list)
        for version_id, category_id, name, parent_id in splits:
            if parent_id is None and name.casefold() == "uncategorized":
                continue
            grouped[version_id].append(category_id)
        return {
            version_id: category_ids[0]
            for version_id, category_ids in grouped.items()
            if len(category_ids) == 1
        }

    def _today(self) -> date:
        return datetime.now(UTC).astimezone(self._timezone).date()

    @staticmethod
    def _locked(session: Session, series_id: UUID) -> RecurringSeries:
        series = session.get(RecurringSeries, series_id, with_for_update=True)
        if series is None:
            raise RecurringNotFoundError("Recurring series was not found")
        return series

    @staticmethod
    def _series_for_key(session: Session, cluster_key: str) -> RecurringSeries | None:
        return session.scalar(
            select(RecurringSeries).where(RecurringSeries.cluster_key == cluster_key)
        )

    @staticmethod
    def _occurrence_for_transaction(
        session: Session,
        transaction_id: UUID,
    ) -> RecurringOccurrence | None:
        return session.scalar(
            select(RecurringOccurrence).where(RecurringOccurrence.transaction_id == transaction_id)
        )

    @staticmethod
    def _linked_ids(session: Session) -> set[UUID]:
        return set(session.scalars(select(RecurringOccurrence.transaction_id)).all())

    @staticmethod
    def _require_category(session: Session, category_id: UUID | None) -> None:
        if category_id is None:
            return
        category = session.get(Category, category_id)
        if category is None or not category.active:
            raise RecurringError("Category was not found or is inactive")

    @staticmethod
    def _require_account(session: Session, account_id: UUID | None) -> None:
        if account_id is None:
            return
        if session.get(FinancialAccount, account_id) is None:
            raise RecurringError("Financial Account was not found")


def enqueue_recurring_match(queue: RecurringJobQueue, transaction_id: UUID) -> None:
    queue.enqueue(
        MATCH_RECURRING_TRANSACTION_JOB,
        {"transaction_id": str(transaction_id)},
        dedupe_key=f"recurring-match:{transaction_id}",
    )


def enqueue_recurring_detection(queue: RecurringJobQueue, run_key: str) -> None:
    queue.enqueue(
        DETECT_RECURRING_SERIES_JOB,
        {"run_key": run_key},
        dedupe_key=f"recurring-detect:{run_key}",
    )


def _cluster_amounts(rows: list[SpendObservation]) -> list[list[SpendObservation]]:
    ordered = sorted(
        rows, key=lambda row: (row.amount, row.effective_date, str(row.transaction_id))
    )
    clusters: list[list[SpendObservation]] = []
    for row in ordered:
        placed = False
        for cluster in clusters:
            amounts = [item.amount for item in cluster]
            median_amount = _median_decimal(amounts)
            candidate = [*cluster, row]
            candidate_amounts = [item.amount for item in candidate]
            if amounts_within_tolerance(row.amount, median_amount) and amounts_within_tolerance(
                min(candidate_amounts),
                max(candidate_amounts),
            ):
                cluster.append(row)
                placed = True
                break
        if not placed:
            clusters.append([row])
    return clusters


def _cluster_from_rows(
    rows: list[SpendObservation],
    normalized: str,
    currency: str,
) -> RecurringCluster | None:
    if len(rows) < MIN_HITS:
        return None
    ordered = sorted(rows, key=lambda row: (row.effective_date, str(row.transaction_id)))
    cadence_guess = guess_cadence([row.effective_date for row in ordered])
    if cadence_guess is None:
        return None
    cadence, interval_days = cadence_guess
    amounts = [row.amount for row in ordered]
    low = min(amounts)
    high = max(amounts)
    representative = _median_decimal(amounts)
    if representative < low:
        representative = low
    elif representative > high:
        representative = high
    if low == high or high - low <= Decimal("0.01"):
        amount_min = None
        amount_max = None
    else:
        amount_min = low
        amount_max = high
    gaps = [
        (ordered[index].effective_date - ordered[index - 1].effective_date).days
        for index in range(1, len(ordered))
    ]
    latest = ordered[-1]
    return RecurringCluster(
        normalized_counterparty=normalized,
        counterparty=latest.counterparty,
        currency=currency,
        amount=representative,
        amount_min=amount_min,
        amount_max=amount_max,
        cadence=cadence,
        interval_days=interval_days,
        next_expected_date=advance_expected(latest.effective_date, cadence, interval_days),
        confidence=series_confidence(len(ordered), gaps, amounts),
        cluster_key=build_cluster_key(normalized, currency, representative, cadence),
        primary_account_id=_dominant_account(ordered),
        category_id=_dominant_category(ordered),
        observations=tuple(ordered),
    )


def _find_existing(
    rows: list[RecurringSeries], cluster: RecurringCluster
) -> RecurringSeries | None:
    exact = [row for row in rows if row.cluster_key == cluster.cluster_key]
    if exact:
        return min(exact, key=lambda row: (_STATUS_RANK.get(row.status, 9), str(row.id)))
    candidates = [
        row
        for row in rows
        if row.normalized_counterparty == cluster.normalized_counterparty
        and row.currency == cluster.currency
        and amounts_within_tolerance(row.amount, cluster.amount)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: (
            abs(row.amount - cluster.amount),
            _STATUS_RANK.get(row.status, 9),
            str(row.id),
        ),
    )


def _accepts_history_backfill(series: RecurringSeries) -> bool:
    """Active series only, including one the owner created manually.

    Manual series are stored as active. Dismissed, paused, ended, and proposed
    series are not rewritten by the backfill.
    """
    return series.status == "active"


def _best_backfill_series(
    rows: list[RecurringSeries],
    observation: SpendObservation,
) -> RecurringSeries | None:
    candidates: list[RecurringSeries] = []
    for series in rows:
        if not _accepts_history_backfill(series):
            continue
        if series.normalized_counterparty != observation.normalized_counterparty:
            continue
        if series.currency != observation.currency:
            continue
        if not _amount_near(series, observation.amount):
            continue
        if not occurs_on_cadence(
            series.next_expected_date,
            observation.effective_date,
            series.cadence,
            series.interval_days,
        ):
            continue
        candidates.append(series)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda series: (
            abs(series.amount - observation.amount),
            abs((observation.effective_date - series.next_expected_date).days),
            str(series.id),
        ),
    )


def _latest_linked_charge(session: Session, series_id: UUID) -> tuple[UUID, date] | None:
    rows = session.execute(
        select(FinancialTransaction.id, TransactionVersion.effective_date)
        .join(
            RecurringOccurrence,
            RecurringOccurrence.transaction_id == FinancialTransaction.id,
        )
        .join(
            TransactionVersion,
            (TransactionVersion.transaction_id == FinancialTransaction.id)
            & (TransactionVersion.version == FinancialTransaction.current_version),
        )
        .where(RecurringOccurrence.series_id == series_id)
    ).all()
    if not rows:
        return None
    transaction_id, effective_date = max(rows, key=lambda row: (row[1], str(row[0])))
    return transaction_id, effective_date


def _best_active(
    rows: list[RecurringSeries],
    observation: SpendObservation,
) -> RecurringSeries | None:
    candidates: list[RecurringSeries] = []
    for series in rows:
        if series.status != "active":
            continue
        if series.normalized_counterparty != observation.normalized_counterparty:
            continue
        if series.currency != observation.currency:
            continue
        if not _amount_near(series, observation.amount):
            continue
        if not _date_near(series, observation.effective_date):
            continue
        candidates.append(series)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda series: (
            abs((observation.effective_date - series.next_expected_date).days),
            abs(series.amount - observation.amount),
            str(series.id),
        ),
    )


def _amount_near(series: RecurringSeries, amount: Decimal) -> bool:
    if series.amount_min is not None and series.amount_max is not None:
        low = series.amount_min - _tolerance(series.amount_min)
        high = series.amount_max + _tolerance(series.amount_max)
        return low <= amount <= high
    return amounts_within_tolerance(amount, series.amount)


def _date_near(series: RecurringSeries, when: date) -> bool:
    window = match_window_days(series.cadence, series.interval_days)
    return abs((when - series.next_expected_date).days) <= window


def _tolerance(amount: Decimal) -> Decimal:
    return max(ABSOLUTE_TOLERANCE, RELATIVE_TOLERANCE * amount)


def _dominant_account(rows: list[SpendObservation]) -> UUID:
    counts: dict[UUID, int] = defaultdict(int)
    latest: dict[UUID, date] = {}
    for row in rows:
        counts[row.financial_account_id] += 1
        current = latest.get(row.financial_account_id)
        if current is None or row.effective_date >= current:
            latest[row.financial_account_id] = row.effective_date
    return max(
        counts,
        key=lambda account_id: (counts[account_id], latest[account_id], str(account_id)),
    )


def _dominant_category(rows: list[SpendObservation]) -> UUID | None:
    counts: dict[UUID, int] = defaultdict(int)
    for row in rows:
        if row.category_id is not None:
            counts[row.category_id] += 1
    if not counts:
        return None
    winner = max(counts, key=lambda category_id: (counts[category_id], str(category_id)))
    if counts[winner] * 2 < len(rows):
        return None
    if sum(1 for count in counts.values() if count == counts[winner]) > 1:
        return None
    return winner


def _to_record(
    series: RecurringSeries, linked_count: int, last_amount: Money
) -> RecurringSeriesRecord:
    return RecurringSeriesRecord(
        id=series.id,
        counterparty=series.counterparty,
        amount=Money(series.amount, series.currency),
        amount_min=(
            None if series.amount_min is None else Money(series.amount_min, series.currency)
        ),
        amount_max=(
            None if series.amount_max is None else Money(series.amount_max, series.currency)
        ),
        cadence=series.cadence,
        interval_days=series.interval_days,
        next_expected_date=series.next_expected_date,
        category_id=series.category_id,
        primary_account_id=series.primary_account_id,
        status=series.status,
        source=series.source,
        confidence=series.confidence,
        last_matched_tx_id=series.last_matched_tx_id,
        last_amount=last_amount,
        linked_count=linked_count,
        missed=series.missed,
        notes=series.notes,
        cluster_key=series.cluster_key,
    )


def _median_decimal(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    averaged = (ordered[middle - 1] + ordered[middle]) / 2
    return averaged.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _median_int(values: list[int]) -> int:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle] + 1) // 2


def _nearest_step(value: int, step: int) -> int:
    """Round ``value / step`` to the nearest integer, half away from zero."""
    if step <= 0:
        raise RecurringError("cadence step must be positive")
    half = step // 2
    if value >= 0:
        return (value + half) // step
    return -((-value + half) // step)


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    last_day = _month_length(year, month)
    return date(year, month, min(value.day, last_day))


def _month_length(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    if month in {4, 6, 9, 11}:
        return 30
    return 31


def _positive_amount(value: Decimal) -> Decimal:
    if not value.is_finite() or value <= 0:
        raise RecurringError("amount must be positive")
    return value


def _bounds(
    amount: Decimal,
    amount_min: Decimal | None,
    amount_max: Decimal | None,
) -> tuple[Decimal | None, Decimal | None]:
    if amount_min is None and amount_max is None:
        return None, None
    if amount_min is None or amount_max is None:
        raise RecurringError("amount range requires both minimum and maximum")
    low = _positive_amount(amount_min)
    high = _positive_amount(amount_max)
    if low > amount or amount > high:
        raise RecurringError("amount must sit inside the minimum and maximum")
    if low == high:
        return None, None
    return low, high


def _interval_for(cadence: str, interval_days: int | None) -> int | None:
    if cadence not in _CADENCES:
        raise RecurringError("cadence is invalid")
    if cadence == "custom_days":
        if interval_days is None or not 1 <= interval_days <= 400:
            raise RecurringError("custom cadence requires a positive interval")
        return interval_days
    if interval_days is not None:
        raise RecurringError("interval days apply only to a custom cadence")
    return None


def _clean_counterparty(value: str) -> str:
    label = " ".join(value.split())
    if not label or len(label) > 300 or not normalize_counterparty(label):
        raise RecurringError("a Counterparty is required")
    return label


def _clean_currency(value: str) -> str:
    currency = value.strip().upper()
    if _CURRENCY_PATTERN.fullmatch(currency) is None:
        raise RecurringError("currency must be a three-letter code")
    return currency


def _clean_notes(notes: str | None) -> str | None:
    if notes is None:
        return None
    cleaned = notes.strip()
    if not cleaned:
        return None
    if len(cleaned) > 2000:
        raise RecurringError("notes are too long")
    return cleaned
