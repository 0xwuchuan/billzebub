#!/usr/bin/env python3
"""Apply high-confidence Codex Category proposals to pending Reviews.

This runner is the forge routine for unknowns the in-app pass left as Reviews.
It is not a Grok Bot and must not run inside Billzebub API or worker containers.
The agent token stays on rafiki as a mode-0600 secret.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID

from billzebub.agent_mcp import McpRequestError, assert_agent_safe

DEFAULT_MODEL = "gpt-5.6-luna"
FALLBACK_MODEL = "gpt-5.6-terra"
DEFAULT_MIN_CONFIDENCE = Decimal("0.95")
DEFAULT_TIMEOUT_SECONDS = 120.0
CATEGORIZABLE_KINDS = frozenset({"expense", "cash_withdrawal"})
SKIP_KINDS = frozenset({"transfer", "income", "refund", "reimbursement"})
SECRET_ENV_KEYS = frozenset({"BILLZEBUB_AGENT_TOKEN"})
OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "category_id", "category_name", "confidence"],
    "properties": {
        "action": {"type": "string", "enum": ["apply", "skip"]},
        "category_id": {"type": ["string", "null"]},
        "category_name": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "maxLength": 240},
    },
}


class RunnerError(ValueError):
    """Configuration or agent-API failure that should fail the process."""


class CodexError(ValueError):
    """Codex did not return a usable structured proposal."""


class AgentApiError(ValueError):
    """The agent HTTP resource rejected or did not answer a request."""


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    api_base: str
    token: str
    model: str = DEFAULT_MODEL
    fallback_model: str = FALLBACK_MODEL
    min_confidence: Decimal = DEFAULT_MIN_CONFIDENCE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    dry_run: bool = False
    verbose: bool = False
    limit: int | None = None
    codex_bin: str = "codex"

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        token_file: Path | None = None,
        dry_run: bool = False,
        verbose: bool = False,
        model: str | None = None,
        fallback_model: str | None = None,
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
            _read_token_file(resolved_token_file)
            if resolved_token_file is not None
            else values.get("BILLZEBUB_AGENT_TOKEN", "").strip()
        )
        if not token:
            raise RunnerError("BILLZEBUB_AGENT_TOKEN or BILLZEBUB_AGENT_TOKEN_FILE is required")

        min_confidence = _decimal_env(
            values, "BILLZEBUB_CODEX_MIN_CONFIDENCE", DEFAULT_MIN_CONFIDENCE
        )
        if not Decimal("0") <= min_confidence <= Decimal("1"):
            raise RunnerError("BILLZEBUB_CODEX_MIN_CONFIDENCE must be between 0 and 1")
        timeout = _float_env(values, "BILLZEBUB_CODEX_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        if timeout <= 0:
            raise RunnerError("BILLZEBUB_CODEX_TIMEOUT_SECONDS must be positive")
        env_limit = _optional_int_env(values, "BILLZEBUB_CODEX_LIMIT")
        resolved_limit = limit if limit is not None else env_limit
        if resolved_limit is not None and resolved_limit < 1:
            raise RunnerError("categorizer limit must be at least 1")

        return cls(
            api_base=api_base,
            token=token,
            model=(model or values.get("BILLZEBUB_CODEX_MODEL", "").strip() or DEFAULT_MODEL),
            fallback_model=(
                fallback_model
                or values.get("BILLZEBUB_CODEX_FALLBACK_MODEL", "").strip()
                or FALLBACK_MODEL
            ),
            min_confidence=min_confidence,
            timeout_seconds=timeout,
            dry_run=dry_run,
            verbose=verbose,
            limit=resolved_limit,
            codex_bin=values.get("BILLZEBUB_CODEX_BIN", "").strip() or "codex",
        )


@dataclass(frozen=True, slots=True)
class Category:
    id: UUID
    name: str
    parent_id: UUID | None

    @property
    def label(self) -> str:
        parent = str(self.parent_id) if self.parent_id is not None else "top-level"
        return f"{self.id} | {self.name} | {parent}"


@dataclass(frozen=True, slots=True)
class Transaction:
    id: UUID
    version: int
    counterparty: str
    amount: str
    currency: str
    effective_date: str
    kind: str
    categories: tuple[str, ...]
    review_choices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Proposal:
    action: str
    category_id: UUID | None
    category_name: str | None
    confidence: Decimal
    model: str


class AgentApi(Protocol):
    def list_reviews(self) -> tuple[UUID, ...]: ...

    def list_categories(self) -> tuple[Category, ...]: ...

    def get_transaction(self, transaction_id: UUID) -> Transaction: ...

    def categorize(
        self,
        *,
        transaction_id: UUID,
        version: int,
        category_id: UUID,
        idempotency_key: str,
    ) -> None: ...


class Proposer(Protocol):
    def propose(
        self,
        transaction: Transaction,
        categories: Sequence[Category],
    ) -> Proposal: ...


class UrlLibAgentApi:
    """HTTPS client for agent-safe review and categorize resources."""

    def __init__(self, config: RunnerConfig, *, timeout_seconds: float | None = None) -> None:
        self._config = config
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else config.timeout_seconds
        )

    def list_reviews(self) -> tuple[UUID, ...]:
        payload = self._request("GET", "/api/v1/agent/reviews")
        items = payload.get("items")
        if not isinstance(items, list):
            raise AgentApiError("agent reviews resource is invalid")
        reviews: list[UUID] = []
        for item in items:
            if not isinstance(item, dict):
                raise AgentApiError("agent reviews resource is invalid")
            try:
                transaction_id = UUID(str(item["transaction_id"]))
            except (KeyError, TypeError, ValueError) as error:
                raise AgentApiError("agent reviews resource is invalid") from error
            reviews.append(transaction_id)
        return tuple(reviews)

    def list_categories(self) -> tuple[Category, ...]:
        payload = self._request("GET", "/api/v1/agent/categories")
        items = payload.get("items")
        if not isinstance(items, list):
            raise AgentApiError("agent categories resource is invalid")
        categories: list[Category] = []
        for item in items:
            if not isinstance(item, dict):
                raise AgentApiError("agent categories resource is invalid")
            try:
                parent_raw = item.get("parent_id")
                categories.append(
                    Category(
                        id=UUID(str(item["id"])),
                        name=str(item["name"]),
                        parent_id=UUID(str(parent_raw)) if parent_raw is not None else None,
                    )
                )
            except (KeyError, TypeError, ValueError) as error:
                raise AgentApiError("agent categories resource is invalid") from error
        return tuple(categories)

    def get_transaction(self, transaction_id: UUID) -> Transaction:
        payload = self._request("GET", f"/api/v1/agent/transactions/{transaction_id}")
        try:
            amount = payload["amount"]
            if not isinstance(amount, dict):
                raise TypeError
            categories_raw = payload.get("categories", [])
            choices_raw = payload.get("review_choices", [])
            version_raw = payload["version"]
            if not isinstance(categories_raw, list) or not isinstance(choices_raw, list):
                raise TypeError
            if not isinstance(version_raw, int) or isinstance(version_raw, bool):
                raise TypeError
            names = tuple(
                str(entry["category"]["name"])
                for entry in categories_raw
                if isinstance(entry, dict) and isinstance(entry.get("category"), dict)
            )
            return Transaction(
                id=UUID(str(payload["id"])),
                version=version_raw,
                counterparty=str(payload["counterparty"]),
                amount=str(amount["amount"]),
                currency=str(amount["currency"]),
                effective_date=str(payload["effective_date"]),
                kind=str(payload["kind"]),
                categories=names,
                review_choices=tuple(str(choice) for choice in choices_raw),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AgentApiError("agent transaction resource is invalid") from error

    def categorize(
        self,
        *,
        transaction_id: UUID,
        version: int,
        category_id: UUID,
        idempotency_key: str,
    ) -> None:
        self._request(
            "POST",
            f"/api/v1/agent/transactions/{transaction_id}/category",
            body={"category_id": str(category_id)},
            headers={
                "Idempotency-Key": idempotency_key,
                "If-Match": f'"transaction:{transaction_id}:v{version}"',
            },
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        request_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._config.token}",
        }
        if headers is not None:
            request_headers.update(headers)
        encoded_body = None
        if body is not None:
            encoded_body = json.dumps(body, separators=(",", ":"), allow_nan=False).encode()
            request_headers["Content-Type"] = "application/json"
        request = Request(
            f"{self._config.api_base}{path}",
            data=encoded_body,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = response.read()
        except HTTPError as error:
            raise AgentApiError(f"agent API returned HTTP {error.code}") from error
        except URLError as error:
            raise AgentApiError("agent API is unavailable") from error
        try:
            decoded = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as error:
            raise AgentApiError("agent API returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise AgentApiError("agent API returned an invalid resource")
        try:
            assert_agent_safe(decoded)
        except McpRequestError as error:
            raise AgentApiError("agent resource contains a forbidden field") from error
        return decoded


class CodexProposer:
    """Call `codex exec` non-interactively and parse a structured proposal."""

    def __init__(self, config: RunnerConfig) -> None:
        self._config = config

    def propose(
        self,
        transaction: Transaction,
        categories: Sequence[Category],
    ) -> Proposal:
        prompt = build_prompt(transaction, categories)
        models = (self._config.model, self._config.fallback_model)
        last_error: Exception | None = None
        seen: set[str] = set()
        for model in models:
            if model in seen:
                continue
            seen.add(model)
            try:
                raw = self._exec(prompt, model=model)
                payload = parse_proposal_json(raw)
                return parse_proposal(payload, categories, self._config.min_confidence, model=model)
            except (CodexError, OSError, subprocess.TimeoutExpired) as error:
                last_error = error
                continue
        raise CodexError("codex exec failed for luna and terra") from last_error

    def _exec(self, prompt: str, *, model: str) -> str:
        with tempfile.TemporaryDirectory(prefix="billzebub-codex-") as directory:
            workdir = Path(directory)
            schema_path = workdir / "proposal.schema.json"
            schema_path.write_text(json.dumps(OUTPUT_SCHEMA), encoding="utf-8")
            last_message = workdir / "proposal.json"
            command = [
                self._config.codex_bin,
                "exec",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--cd",
                str(workdir),
                "-m",
                model,
                "--output-schema",
                str(schema_path),
                "-o",
                str(last_message),
                prompt,
            ]
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self._config.timeout_seconds,
                    env=_codex_env(os.environ),
                    cwd=workdir,
                )
            except FileNotFoundError as error:
                raise CodexError("codex executable was not found") from error
            if completed.returncode != 0:
                raise CodexError(f"codex exec exited with status {completed.returncode}")
            if last_message.is_file():
                written = last_message.read_text(encoding="utf-8").strip()
                if written:
                    return written
            stdout = completed.stdout.strip()
            if stdout:
                return stdout
            raise CodexError("codex exec returned no proposal")


def build_prompt(transaction: Transaction, categories: Sequence[Category]) -> str:
    catalog = "\n".join(f"- {category.label}" for category in categories) or "- (none)"
    return (
        "Categorize one Billzebub Expense. Reply only through the output schema.\n"
        "Rules:\n"
        "- Choose exactly one Category from the catalog, or skip.\n"
        "- Never invent a Category, never use Uncategorized, never create names.\n"
        "- Skip Transfers, Income, Refunds, Reimbursements, and anything uncertain.\n"
        "- If two catalog Categories could fit, skip. Fail closed on ambiguity.\n"
        "- action=apply only when one existing Category is clearly correct.\n"
        f"Catalog (id | name | parent_id):\n{catalog}\n"
        "Transaction:\n"
        f"- id: {transaction.id}\n"
        f"- version: {transaction.version}\n"
        f"- counterparty: {transaction.counterparty}\n"
        f"- amount: {transaction.amount} {transaction.currency}\n"
        f"- effective_date: {transaction.effective_date}\n"
        f"- kind: {transaction.kind}\n"
    )


def parse_proposal_json(text: str) -> dict[str, object]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as error:
        raise CodexError("codex proposal was not JSON") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise CodexError("codex proposal was not a JSON object")
    return payload


def parse_proposal(
    payload: Mapping[str, object],
    categories: Sequence[Category],
    min_confidence: Decimal,
    *,
    model: str,
) -> Proposal:
    action = payload.get("action")
    if action not in {"apply", "skip"}:
        return _skip(model)
    confidence = _confidence(payload.get("confidence"))
    if confidence is None:
        return _skip(model)
    if action == "skip" or confidence < min_confidence:
        return Proposal(
            action="skip",
            category_id=None,
            category_name=None,
            confidence=confidence,
            model=model,
        )
    category_id = _optional_uuid(payload.get("category_id"))
    category_name = payload.get("category_name")
    if category_id is None or not isinstance(category_name, str):
        return _skip(model)
    normalized_name = " ".join(category_name.split())
    catalog = {category.id: category for category in categories}
    chosen = catalog.get(category_id)
    if (
        chosen is None
        or chosen.name.casefold() != normalized_name.casefold()
        or chosen.name.casefold() == "uncategorized"
    ):
        return _skip(model)
    return Proposal(
        action="apply",
        category_id=chosen.id,
        category_name=chosen.name,
        confidence=confidence,
        model=model,
    )


def idempotency_key(transaction: Transaction, category_id: UUID) -> str:
    return f"codex-cat:{transaction.id}:v{transaction.version}:{category_id}"


def should_ask_codex(transaction: Transaction) -> bool:
    if transaction.kind in SKIP_KINDS or transaction.kind not in CATEGORIZABLE_KINDS:
        return False
    if "categorize" not in transaction.review_choices:
        return False
    assigned = any(name.casefold() != "uncategorized" for name in transaction.categories)
    return not assigned


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
        _print(f"codex categorizer failed: {error}", stdout)
        return 1
    if not reviews:
        return 0

    queued = reviews if config.limit is None else reviews[: config.limit]
    try:
        categories = api.list_categories()
    except AgentApiError as error:
        _print(f"codex categorizer failed: {error}", stdout)
        return 1
    if not categories:
        _print("codex categorizer skipped: no Categories available", stdout)
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
        if not should_ask_codex(transaction):
            skipped += 1
            continue
        try:
            proposal = proposer.propose(transaction, categories)
        except CodexError:
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

    summary = "codex categorizer dry-run" if config.dry_run else "codex categorizer"
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
            fallback_model=arguments.fallback_model,
            limit=arguments.limit,
        )
    except RunnerError as error:
        _print(f"codex categorizer configuration is invalid: {error}", stdout)
        return 2
    resolved_api = api or UrlLibAgentApi(config)
    resolved_proposer = proposer or CodexProposer(config)
    return run(config, resolved_api, resolved_proposer, stdout=stdout)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Categorize pending Billzebub Reviews with a forge-side Codex ChatGPT routine.",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        help="mode-0600 file containing the agent bearer token",
    )
    parser.add_argument("-m", "--model", help=f"primary Codex model (default {DEFAULT_MODEL})")
    parser.add_argument(
        "--fallback-model",
        help=f"fallback Codex model (default {FALLBACK_MODEL})",
    )
    parser.add_argument("--limit", type=int, help="maximum Reviews to process this run")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="call Codex but do not POST categorize",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser


def _read_token_file(path: Path) -> str:
    expanded = path.expanduser()
    try:
        metadata = expanded.lstat()
    except OSError as error:
        raise RunnerError("agent token file is unreadable") from error
    if not stat.S_ISREG(metadata.st_mode) or expanded.is_symlink() or metadata.st_mode & 0o077:
        raise RunnerError("agent token file is unsafe")
    try:
        value = expanded.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RunnerError("agent token file is unreadable") from error
    if not value:
        raise RunnerError("agent token file is empty")
    return value


def _codex_env(environ: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in environ.items() if key not in SECRET_ENV_KEYS}


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


def _confidence(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, int):
            confidence = Decimal(value)
        elif isinstance(value, float):
            confidence = Decimal(str(value))
        elif isinstance(value, str):
            confidence = Decimal(value.strip())
        else:
            return None
    except InvalidOperation:
        return None
    if confidence < Decimal("0") or confidence > Decimal("1"):
        return None
    return confidence


def _optional_uuid(value: object) -> UUID | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return UUID(value.strip())
    except ValueError:
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
