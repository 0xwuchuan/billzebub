"""TypeSafe Jev Category proposals with fail-closed confidence gating.

Shared by the NAS worker (primary) and the optional host-side CLI. State is
limited to agent-safe fields: Counterparty, amount, currency, date, and kind.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol
from uuid import UUID

from typesafe_sdk import Choice, TypeSafeClient, TypeSafeError

from billzebub.agent_mcp import McpRequestError, assert_agent_safe
from billzebub.jev_hierarchy import catalog_choice_criteria, resolve_catalog_choice

DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_MIN_CONFIDENCE = Decimal("0.5")
DEFAULT_TIMEOUT_SECONDS = 30.0
CHOICE_QUESTION = "category"
UNCATEGORIZED_NAME = "uncategorized"
MAX_CHOICE_OPTIONS = 255
TYPESAFE_BASE_URL = "https://api.typesafe.ai"
TYPESAFE_ENDPOINT = f"{TYPESAFE_BASE_URL}/v1/systemone"
_SECRETISH = re.compile(r"(?i)(?:api[_-]?key|bearer|token|secret)\s*[:=]\s*\S+")


class JevError(ValueError):
    """Jev did not return a usable structured proposal."""


class JevConfigurationError(ValueError):
    """TypeSafe or Jev configuration is missing or unsafe."""


@dataclass(frozen=True, slots=True)
class JevSubject:
    """Agent-safe Transaction fields sent to Jev. Never include ids or artifacts."""

    counterparty: str
    amount: str
    currency: str
    effective_date: str
    kind: str


@dataclass(frozen=True, slots=True)
class JevCategory:
    id: UUID
    name: str
    parent_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class JevClientConfig:
    typesafe_api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL
    min_confidence: Decimal = DEFAULT_MIN_CONFIDENCE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        require_key: bool = True,
    ) -> JevClientConfig | None:
        values = os.environ if environ is None else environ
        typesafe_api_key = resolve_typesafe_api_key(values)
        if not typesafe_api_key:
            if require_key:
                raise JevConfigurationError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")
            return None
        min_confidence = _decimal_env(
            values, "BILLZEBUB_JEV_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE
        )
        if not Decimal("0") <= min_confidence <= Decimal("1"):
            raise JevConfigurationError("BILLZEBUB_JEV_MIN_CONFIDENCE must be between 0 and 1")
        timeout = _float_env(values, "BILLZEBUB_JEV_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        if timeout <= 0:
            raise JevConfigurationError("BILLZEBUB_JEV_TIMEOUT_SECONDS must be positive")
        model = values.get("BILLZEBUB_JEV_MODEL", "").strip() or DEFAULT_MODEL
        return cls(
            typesafe_api_key=typesafe_api_key,
            model=model,
            min_confidence=min_confidence,
            timeout_seconds=timeout,
        )


@dataclass(frozen=True, slots=True)
class Proposal:
    action: str
    category_id: UUID | None
    category_name: str | None
    confidence: Decimal
    model: str
    choice: str | None = None
    noul: Decimal | None = None
    error_class: str | None = None
    error_message: str | None = None
    fell_back_to_parent: bool = False


class Proposer(Protocol):
    def propose(self, subject: JevSubject, categories: Sequence[JevCategory]) -> Proposal: ...


class JevProposer:
    """Call TypeSafe System One and parse a fail-closed Category proposal."""

    def __init__(self, config: JevClientConfig) -> None:
        self._config = config

    @property
    def model(self) -> str:
        return self._config.model

    def propose(self, subject: JevSubject, categories: Sequence[JevCategory]) -> Proposal:
        state = jev_state(subject)
        questions = jev_questions(categories)
        try:
            assert_agent_safe(state)
        except McpRequestError as error:
            raise JevError("jev state contains a forbidden field") from error
        try:
            with TypeSafeClient(
                api_key=self._config.typesafe_api_key,
                model=self._config.model,
                timeout=self._config.timeout_seconds,
                base_url=TYPESAFE_BASE_URL,
            ) as client:
                response = client.system_one(
                    state=state,
                    questions=questions,
                    model=self._config.model,
                    timeout=self._config.timeout_seconds,
                )
        except TypeSafeError as error:
            scrubbed = TypeSafeError(
                safe_error_message(error, secret=self._config.typesafe_api_key)
            )
            raise JevError("typesafe systemone failed") from scrubbed
        return parse_jev_response(
            response, categories, self._config.min_confidence, model=self._config.model
        )


def jev_state(subject: JevSubject) -> dict[str, str]:
    """Agent-safe fields only; never include ids, artifacts, or raw descriptions."""
    return {
        "counterparty": subject.counterparty,
        "amount": subject.amount,
        "currency": subject.currency,
        "effective_date": subject.effective_date,
        "kind": subject.kind,
    }


def choice_criteria(categories: Sequence[JevCategory]) -> dict[str, str]:
    # Path labels live in jev_hierarchy so Jev v1 can rebase name matching locally.
    criteria = catalog_choice_criteria(categories)
    if len(criteria) > MAX_CHOICE_OPTIONS:
        raise JevError("category catalog exceeds Jev Choice limit")
    return criteria


def jev_questions(categories: Sequence[JevCategory]) -> dict[str, Choice]:
    return {
        CHOICE_QUESTION: Choice(
            instructions=(
                "Choose exactly one existing catalog Category for this Expense or Cash Withdrawal."
            ),
            criteria=choice_criteria(categories),
        ),
    }


def parse_jev_response(
    response: object,
    categories: Sequence[JevCategory],
    min_confidence: Decimal,
    *,
    model: str,
) -> Proposal:
    choice_answer = _named_answer(response, "choices", CHOICE_QUESTION)
    if choice_answer is None:
        answers = getattr(response, "answers", None)
        if isinstance(answers, Mapping):
            choice_answer = answers.get(CHOICE_QUESTION)
    response_model = getattr(response, "model", None)
    resolved_model = response_model if isinstance(response_model, str) and response_model else model
    probabilities = (
        getattr(choice_answer, "probabilities", None) if choice_answer is not None else None
    )
    if not isinstance(probabilities, Mapping):
        probabilities = None
    return parse_jev_proposal(
        getattr(choice_answer, "choice", None) if choice_answer is not None else None,
        getattr(choice_answer, "confidence", None) if choice_answer is not None else None,
        categories,
        min_confidence,
        model=resolved_model,
        probabilities=probabilities,
    )


def parse_jev_proposal(
    choice: object,
    confidence_raw: object,
    categories: Sequence[JevCategory],
    min_confidence: Decimal,
    *,
    model: str,
    probabilities: Mapping[str, object] | None = None,
) -> Proposal:
    confidence = _unit_interval(confidence_raw)
    choice_text = " ".join(choice.split()) if isinstance(choice, str) and choice.strip() else None
    if confidence is None:
        return _skip(model, choice=choice_text, confidence=confidence)
    if choice_text is None:
        return _skip(model, confidence=confidence)
    resolved = resolve_catalog_choice(
        choice_text,
        confidence,
        categories,
        min_confidence,
        probabilities=probabilities,
    )
    if resolved is None:
        return _skip(model, choice=choice_text, confidence=confidence)
    return Proposal(
        action="apply",
        category_id=resolved.category_id,
        category_name=resolved.category_name,
        confidence=resolved.confidence,
        model=model,
        choice=choice_text,
        fell_back_to_parent=resolved.fell_back_to_parent,
    )


def resolve_typesafe_api_key(values: Mapping[str, str]) -> str | None:
    key_file = (
        values.get("TYPESAFE_API_KEY_FILE", "").strip()
        or values.get("BILLZEBUB_TYPESAFE_API_KEY_FILE", "").strip()
    )
    if key_file:
        return read_private_secret_file(Path(key_file), label="TypeSafe API key")
    key = (
        values.get("TYPESAFE_API_KEY", "").strip()
        or values.get("BILLZEBUB_TYPESAFE_API_KEY", "").strip()
    )
    return key or None


def read_private_secret_file(path: Path, *, label: str) -> str:
    expanded = path.expanduser()
    try:
        metadata = expanded.lstat()
    except OSError as error:
        raise JevConfigurationError(f"{label} file is unreadable") from error
    if not stat.S_ISREG(metadata.st_mode) or expanded.is_symlink() or metadata.st_mode & 0o077:
        raise JevConfigurationError(f"{label} file is unsafe")
    try:
        value = expanded.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise JevConfigurationError(f"{label} file is unreadable") from error
    if not value:
        raise JevConfigurationError(f"{label} file is empty")
    return value


def _decimal_env(values: Mapping[str, str], name: str, default: Decimal) -> Decimal:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        return Decimal(raw)
    except InvalidOperation as error:
        raise JevConfigurationError(f"{name} is invalid") from error


def _float_env(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise JevConfigurationError(f"{name} is invalid") from error


def _unit_interval(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, int):
            parsed = Decimal(value)
        elif isinstance(value, float):
            parsed = Decimal(str(value))
        elif isinstance(value, str):
            parsed = Decimal(value.strip())
        elif isinstance(value, Decimal):
            parsed = value
        else:
            return None
    except InvalidOperation:
        return None
    if parsed < Decimal("0") or parsed > Decimal("1"):
        return None
    return parsed


def _named_answer(response: object, group: str, name: str) -> object | None:
    answers = getattr(response, group, None)
    if isinstance(answers, Mapping):
        return answers.get(name)
    return None


def _skip(
    model: str,
    *,
    choice: str | None = None,
    confidence: Decimal | None = None,
) -> Proposal:
    return Proposal(
        action="skip",
        category_id=None,
        category_name=None,
        confidence=confidence if confidence is not None else Decimal("0"),
        model=model,
        choice=choice,
    )


def safe_error_message(error: BaseException, *, secret: str | None = None) -> str:
    """Keep TypeSafe failures reviewable without logging an API key."""
    message = str(error)
    if secret:
        message = message.replace(secret, "[redacted]")
    message = _SECRETISH.sub("[redacted]", message)
    return " ".join(message.split())[:500]
