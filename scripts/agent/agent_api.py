"""HTTPS client for agent-safe review and categorize resources.

Shared by host-side runners that stay outside Billzebub API and worker
containers. Tokens stay on the host as mode-0600 secrets.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from billzebub.agent_mcp import McpRequestError, assert_agent_safe

CATEGORIZABLE_KINDS = frozenset({"expense", "cash_withdrawal"})
SKIP_KINDS = frozenset({"transfer", "income", "refund", "reimbursement"})


class AgentApiError(ValueError):
    """The agent HTTP resource rejected or did not answer a request."""


@dataclass(frozen=True, slots=True)
class AgentApiConfig:
    api_base: str
    token: str = field(repr=False)
    timeout_seconds: float = 30.0


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


class UrlLibAgentApi:
    """HTTPS client for agent-safe review and categorize resources."""

    def __init__(self, config: AgentApiConfig, *, timeout_seconds: float | None = None) -> None:
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


def should_categorize(transaction: Transaction) -> bool:
    if transaction.kind in SKIP_KINDS or transaction.kind not in CATEGORIZABLE_KINDS:
        return False
    if "categorize" not in transaction.review_choices:
        return False
    assigned = any(name.casefold() != "uncategorized" for name in transaction.categories)
    return not assigned


__all__ = [
    "CATEGORIZABLE_KINDS",
    "SKIP_KINDS",
    "AgentApi",
    "AgentApiConfig",
    "AgentApiError",
    "Category",
    "Transaction",
    "UrlLibAgentApi",
    "should_categorize",
]
