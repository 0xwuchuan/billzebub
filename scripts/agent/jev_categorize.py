#!/usr/bin/env python3
"""Optional host-side Jev CLI. Production categorization runs in the NAS worker.

This runner is an ops tool for dry-runs and catch-up against the agent API. It
is not a Grok Bot, not a forge production path, and is not required when the
worker has TYPESAFE_API_KEY. Tokens stay on the host as mode-0600 secrets.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Protocol, TextIO
from urllib.parse import urlparse
from uuid import UUID

from billzebub.jev import (
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_SECONDS,
    JevCategory,
    JevClientConfig,
    JevConfigurationError,
    JevError,
    JevProposer,
    JevSubject,
    Proposal,
    Proposer,
    read_private_secret_file,
)
from scripts.agent.agent_api import (
    AgentApi,
    AgentApiConfig,
    AgentApiError,
    Category,
    Transaction,
    UrlLibAgentApi,
    should_categorize,
)


class RunnerError(ValueError):
    """Configuration failure that should fail the process."""


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
        try:
            token = (
                read_private_secret_file(resolved_token_file, label="agent token")
                if resolved_token_file is not None
                else values.get("BILLZEBUB_AGENT_TOKEN", "").strip()
            )
        except JevConfigurationError as error:
            raise RunnerError(str(error)) from error
        if not token:
            raise RunnerError("BILLZEBUB_AGENT_TOKEN or BILLZEBUB_AGENT_TOKEN_FILE is required")

        try:
            client = JevClientConfig.from_environment(values, require_key=True)
        except JevConfigurationError as error:
            raise RunnerError(str(error)) from error
        if client is None:
            raise RunnerError("TYPESAFE_API_KEY or TYPESAFE_API_KEY_FILE is required")

        env_limit = _optional_int_env(values, "BILLZEBUB_JEV_LIMIT")
        resolved_limit = limit if limit is not None else env_limit
        if resolved_limit is not None and resolved_limit < 1:
            raise RunnerError("categorizer limit must be at least 1")

        return cls(
            api_base=api_base,
            token=token,
            typesafe_api_key=client.typesafe_api_key,
            model=(model or client.model),
            min_confidence=client.min_confidence,
            timeout_seconds=client.timeout_seconds,
            dry_run=dry_run,
            verbose=verbose,
            limit=resolved_limit,
        )

    def client_config(self) -> JevClientConfig:
        return JevClientConfig(
            typesafe_api_key=self.typesafe_api_key,
            model=self.model,
            min_confidence=self.min_confidence,
            timeout_seconds=self.timeout_seconds,
        )


class AgentTransactionProposer(Protocol):
    def propose(self, transaction: Transaction, categories: Sequence[Category]) -> Proposal: ...


class TransactionProposer:
    """Adapt the shared Jev proposer to agent-API Transaction objects."""

    def __init__(self, proposer: Proposer) -> None:
        self._proposer = proposer

    def propose(self, transaction: Transaction, categories: Sequence[Category]) -> Proposal:
        return self._proposer.propose(
            subject_from_transaction(transaction),
            _jev_categories(categories),
        )


def _jev_categories(categories: Sequence[Category]) -> tuple[JevCategory, ...]:
    by_id = {category.id: category for category in categories}
    converted: list[JevCategory] = []
    for category in categories:
        parent = by_id.get(category.parent_id) if category.parent_id is not None else None
        converted.append(
            JevCategory(
                id=category.id,
                name=category.name,
                parent_id=category.parent_id,
                parent_name=parent.name if parent is not None else None,
            )
        )
    return tuple(converted)


def subject_from_transaction(transaction: Transaction) -> JevSubject:
    return JevSubject(
        counterparty=transaction.counterparty,
        amount=transaction.amount,
        currency=transaction.currency,
        effective_date=transaction.effective_date,
        kind=transaction.kind,
    )


def idempotency_key(transaction: Transaction, category_id: UUID) -> str:
    return f"jev-cat:{transaction.id}:v{transaction.version}:{category_id}"


def should_ask_jev(transaction: Transaction) -> bool:
    return should_categorize(transaction)


def run(
    config: RunnerConfig,
    api: AgentApi,
    proposer: AgentTransactionProposer,
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
    proposer: AgentTransactionProposer | None = None,
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
        AgentApiConfig(
            api_base=config.api_base,
            token=config.token,
            timeout_seconds=config.timeout_seconds,
        )
    )
    resolved_proposer = proposer or TransactionProposer(JevProposer(config.client_config()))
    return run(config, resolved_api, resolved_proposer, stdout=stdout)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Optional ops tool: categorize pending Billzebub Reviews via the agent API. "
            "Production Jev runs in the NAS worker."
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


def _optional_int_env(values: Mapping[str, str], name: str) -> int | None:
    raw = values.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise RunnerError(f"{name} is invalid") from error


def _print(message: str, stdout: TextIO) -> None:
    stdout.write(message + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
