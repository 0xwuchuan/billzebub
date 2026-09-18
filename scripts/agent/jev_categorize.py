#!/usr/bin/env python3
"""Apply high-confidence Jev Category proposals to pending Reviews.

This runner is the primary host-side pass for unknowns the in-app map left as
Reviews. It is not a Grok Bot and must not run inside Billzebub API or worker
containers. The Codex runner remains an optional fallback. Tokens stay on the
host as mode-0600 secrets.
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, TextIO
from urllib.parse import urlparse
from uuid import UUID

from typesafe_sdk import Choice, Noul, TypeSafeClient, TypeSafeError

from billzebub.agent_mcp import McpRequestError, assert_agent_safe
from scripts.agent.codex_categorize import (
    AgentApi,
    AgentApiError,
    Category,
    Transaction,
    UrlLibAgentApi,
    should_ask_codex,
)
from scripts.agent.codex_categorize import RunnerConfig as CodexRunnerConfig

DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_MIN_CONFIDENCE = Decimal("0.85")
DEFAULT_TIMEOUT_SECONDS = 30.0
SKIP_OPTION = "uncategorized"
SKIP_OPTION_ALIASES = frozenset({"uncategorized", "skip"})
CHOICE_QUESTION = "category"
NOUL_QUESTION = "enough_evidence"
MAX_CHOICE_OPTIONS = 255
TYPESAFE_BASE_URL = "https://api.typesafe.ai"
TYPESAFE_ENDPOINT = f"{TYPESAFE_BASE_URL}/v1/systemone"


class RunnerError(ValueError):
    """Configuration failure that should fail the process."""


class JevError(ValueError):
    """Jev did not return a usable structured proposal."""


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    api_base: str
    token: str = field(repr=False)
    typesafe_api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL
    min_confidence: Decimal = DEFAULT_MIN_CONFIDENCE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    dry_run: bool = False
    verbose: bool = False
    limit: int | None = None

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        token_file: Path | None = None,
        dry_run: bool = False,
        verbose: bool = False,
        model: str | None = None,
        limit: int | None = None,
    ) -> RunnerConfig:
        values = os.environ if environ is None else environ
        api_base = (
            values.get("BILLZEBUB_API_BASE", "").strip()
            or values.get("BILLZEBUB_API_URL", "").strip()
        ).rstrip("/")
        parsed = urlparse(api_base)
        loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if not api_base or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RunnerError("BILLZEBUB_API_BASE is required")
        if parsed.scheme != "https" and not loopback:
            raise RunnerError("BILLZEBUB_API_BASE must use HTTPS outside loopback")

        resolved_token_file = token_file
        if resolved_token_file is None and values.get("BILLZEBUB_AGENT_TOKEN_FILE", "").strip():
            resolved_token_file = Path(values["BILLZEBUB_AGENT_TOKEN_FILE"].strip())
        token = (
            _read_secret_file(resolved_token_file, label="agent token")
            if resolved_token_file is not None
            else values.get("BILLZEBUB_AGENT_TOKEN", "").strip()
        )
        if not token:
            raise RunnerError("BILLZEBUB_AGENT_TOKEN or BILLZEBUB_AGENT_TOKEN_FILE is required")

        typesafe_key_file = values.get("TYPESAFE_API_KEY_FILE", "").strip()
        typesafe_api_key = (
            _read_secret_file(Path(typesafe_key_file), label="TypeSafe API key")
            if typesafe_key_file
            else values.get("TYPESAFE_API_KEY", "").strip()
        )
        if not typesafe_api_key:
            raise RunnerError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")

        min_confidence = _decimal_env(
            values, "BILLZEBUB_JEV_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE
        )
        if not Decimal("0") <= min_confidence <= Decimal("1"):
            raise RunnerError("BILLZEBUB_JEV_MIN_CONFIDENCE must be between 0 and 1")
        timeout = _float_env(values, "BILLZEBUB_JEV_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        if timeout <= 0:
            raise RunnerError("BILLZEBUB_JEV_TIMEOUT_SECONDS must be positive")
        env_limit = _optional_int_env(values, "BILLZEBUB_JEV_LIMIT")
        resolved_limit = limit if limit is not None else env_limit
        if resolved_limit is not None and resolved_limit < 1:
            raise RunnerError("categorizer limit must be at least 1")

        return cls(
            api_base=api_base,
            token=token,
            typesafe_api_key=typesafe_api_key,
            model=(model or values.get("BILLZEBUB_JEV_MODEL", "").strip() or DEFAULT_MODEL),
            min_confidence=min_confidence,
            timeout_seconds=timeout,
            dry_run=dry_run,
            verbose=verbose,
            limit=resolved_limit,
        )


@dataclass(frozen=True, slots=True)
class Proposal:
    action: str
    category_id: UUID | None
    category_name: str | None
    confidence: Decimal
    model: str


class Proposer(Protocol):
    def propose(
        self,
        transaction: Transaction,
        categories: Sequence[Category],
    ) -> Proposal: ...


class JevProposer:
    """Call TypeSafe System One and parse a fail-closed Category proposal."""

    def __init__(self, config: RunnerConfig) -> None:
        self._config = config

    def propose(
        self,
        transaction: Transaction,
        categories: Sequence[Category],
    ) -> Proposal:
        state = jev_state(transaction)
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
            raise JevError("typesafe systemone failed") from error
        return parse_jev_response(
            response, categories, self._config.min_confidence, model=self._config.model
        )


def jev_state(transaction: Transaction) -> dict[str, str]:
    """Agent-safe fields only; never include ids, artifacts, or raw descriptions."""
    return {
        "counterparty": transaction.counterparty,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "effective_date": transaction.effective_date,
        "kind": transaction.kind,
    }


def choice_criteria(categories: Sequence[Category]) -> dict[str, str]:
    criteria: dict[str, str] = {}
    for category in categories:
        if category.name.casefold() in SKIP_OPTION_ALIASES:
            continue
        criteria[category.name] = category.name
    criteria[SKIP_OPTION] = (
        "Skip and leave Uncategorized; use when no existing catalog Category is clearly correct"
    )
    if len(criteria) > MAX_CHOICE_OPTIONS:
        raise JevError("category catalog exceeds Jev Choice limit")
    return criteria


def jev_questions(categories: Sequence[Category]) -> dict[str, Choice | Noul]:
    return {
        CHOICE_QUESTION: Choice(
            instructions=(
                "Choose exactly one existing catalog Category for this Expense or "
                "Cash Withdrawal. Choose uncategorized when uncertain, when two "
                "Categories could fit, or when the activity is not an Expense Category."
            ),
            criteria=choice_criteria(categories),
        ),
        NOUL_QUESTION: Noul(
            instructions=(
                "There is enough evidence to assign one existing catalog Category confidently"
            ),
            criteria={
                "true": "One existing Category is clearly correct for this Expense",
                "false": "Ambiguous, skip, Uncategorized, or not an Expense Category",
            },
        ),
    }


def parse_jev_response(
    response: object,
    categories: Sequence[Category],
    min_confidence: Decimal,
    *,
    model: str,
) -> Proposal:
    choice_answer = _named_answer(response, "choices", CHOICE_QUESTION)
    noul_answer = _named_answer(response, "nouls", NOUL_QUESTION)
    if choice_answer is None:
        answers = getattr(response, "answers", None)
        if isinstance(answers, Mapping):
            choice_answer = answers.get(CHOICE_QUESTION)
            noul_answer = noul_answer or answers.get(NOUL_QUESTION)
    response_model = getattr(response, "model", None)
    resolved_model = response_model if isinstance(response_model, str) and response_model else model
    return parse_jev_proposal(
        getattr(choice_answer, "choice", None) if choice_answer is not None else None,
        getattr(choice_answer, "confidence", None) if choice_answer is not None else None,
        getattr(noul_answer, "noul", None) if noul_answer is not None else None,
        categories,
        min_confidence,
        model=resolved_model,
    )


def parse_jev_proposal(
    choice: object,
    confidence_raw: object,
    noul_raw: object,
    categories: Sequence[Category],
    min_confidence: Decimal,
    *,
    model: str,
) -> Proposal:
    confidence = _unit_interval(confidence_raw)
    noul = _unit_interval(noul_raw)
    if confidence is None or noul is None:
        return _skip(model)
    if not isinstance(choice, str) or not choice.strip():
        return _skip(model)
    if noul < min_confidence or confidence < min_confidence:
        return Proposal(
            action="skip",
            category_id=None,
            category_name=None,
            confidence=confidence,
            model=model,
        )
    normalized = " ".join(choice.split())
    if normalized.casefold() in SKIP_OPTION_ALIASES:
        return Proposal(
            action="skip",
            category_id=None,
            category_name=None,
            confidence=confidence,
            model=model,
        )
    catalog = _unique_categories_by_name(categories)
    chosen = catalog.get(normalized.casefold())
    if chosen is None or chosen.name.casefold() != normalized.casefold():
        return _skip(model)
    return Proposal(
        action="apply",
        category_id=chosen.id,
        category_name=chosen.name,
        confidence=confidence,
        model=model,
    )


def idempotency_key(transaction: Transaction, category_id: UUID) -> str:
    return f"jev-cat:{transaction.id}:v{transaction.version}:{category_id}"


def should_ask_jev(transaction: Transaction) -> bool:
    return should_ask_codex(transaction)


def run(
    config: RunnerConfig,
    api: AgentApi,
    proposer: Proposer,
    *,
    stdout: TextIO = sys.stdout,
) -> int:
    try:
        reviews = api.list_reviews()
    except AgentApiError as error:
        _print(f"jev categorizer failed: {error}", stdout)
        return 1
    if not reviews:
        return 0

    queued = reviews if config.limit is None else reviews[: config.limit]
    try:
        categories = api.list_categories()
    except AgentApiError as error:
        _print(f"jev categorizer failed: {error}", stdout)
        return 1
    if not categories:
        _print("jev categorizer skipped: no Categories available", stdout)
        return 0

    applied = 0
    skipped = 0
    failed = 0
    for transaction_id in queued:
        try:
            transaction = api.get_transaction(transaction_id)
        except AgentApiError:
            skipped += 1
            continue
        if not should_ask_jev(transaction):
            skipped += 1
            continue
        try:
            proposal = proposer.propose(transaction, categories)
        except JevError:
            skipped += 1
            continue
        if proposal.action != "apply" or proposal.category_id is None or config.dry_run:
            skipped += 1
            continue
        try:
            api.categorize(
                transaction_id=transaction.id,
                version=transaction.version,
                category_id=proposal.category_id,
                idempotency_key=idempotency_key(transaction, proposal.category_id),
            )
        except AgentApiError:
            failed += 1
            continue
        applied += 1
        if config.verbose:
            _print(f"applied {transaction.id}", stdout)

    summary = "jev categorizer dry-run" if config.dry_run else "jev categorizer"
    _print(f"{summary} applied={applied} skipped={skipped} failed={failed}", stdout)
    return 1 if failed else 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    api: AgentApi | None = None,
    proposer: Proposer | None = None,
    stdout: TextIO = sys.stdout,
) -> int:
    arguments = _parser().parse_args(argv)
    try:
        config = RunnerConfig.from_environment(
            environ,
            token_file=arguments.token_file,
            dry_run=arguments.dry_run,
            verbose=arguments.verbose,
            model=arguments.model,
            limit=arguments.limit,
        )
    except RunnerError as error:
        _print(f"jev categorizer configuration is invalid: {error}", stdout)
        return 2
    resolved_api = api or UrlLibAgentApi(
        CodexRunnerConfig(
            api_base=config.api_base,
            token=config.token,
            timeout_seconds=config.timeout_seconds,
        )
    )
    resolved_proposer = proposer or JevProposer(config)
    return run(config, resolved_api, resolved_proposer, stdout=stdout)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Categorize pending Billzebub Reviews with a forge-side Jev (TypeSafe) routine."
        ),
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        help="mode-0600 file containing the agent bearer token",
    )
    parser.add_argument("-m", "--model", help=f"Jev model (default {DEFAULT_MODEL})")
    parser.add_argument("--limit", type=int, help="maximum Reviews to process this run")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="call Jev but do not POST categorize",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def _read_secret_file(path: Path, *, label: str) -> str:
    expanded = path.expanduser()
    try:
        metadata = expanded.lstat()
    except OSError as error:
        raise RunnerError(f"{label} file is unreadable") from error
    if not stat.S_ISREG(metadata.st_mode) or expanded.is_symlink() or metadata.st_mode & 0o077:
        raise RunnerError(f"{label} file is unsafe")
    try:
        value = expanded.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RunnerError(f"{label} file is unreadable") from error
    if not value:
        raise RunnerError(f"{label} file is empty")
    return value


def _decimal_env(values: Mapping[str, str], name: str, default: Decimal) -> Decimal:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        return Decimal(raw)
    except InvalidOperation as error:
        raise RunnerError(f"{name} is invalid") from error


def _float_env(values: Mapping[str, str], name: str, default: float) -> float:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise RunnerError(f"{name} is invalid") from error


def _optional_int_env(values: Mapping[str, str], name: str) -> int | None:
    raw = values.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise RunnerError(f"{name} is invalid") from error


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


def _unique_categories_by_name(categories: Sequence[Category]) -> dict[str, Category]:
    mapping: dict[str, Category] = {}
    duplicates: set[str] = set()
    for category in categories:
        key = category.name.casefold()
        if key in SKIP_OPTION_ALIASES:
            continue
        if key in mapping:
            duplicates.add(key)
            continue
        mapping[key] = category
    for key in duplicates:
        mapping.pop(key, None)
    return mapping


def _named_answer(response: object, group: str, name: str) -> object | None:
    answers = getattr(response, group, None)
    if isinstance(answers, Mapping):
        return answers.get(name)
    return None


def _skip(model: str) -> Proposal:
    return Proposal(
        action="skip",
        category_id=None,
        category_name=None,
        confidence=Decimal("0"),
        model=model,
    )


def _print(message: str, stdout: TextIO) -> None:
    stdout.write(message + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
