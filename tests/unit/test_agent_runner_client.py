from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import UUID

import pytest
from scripts.agent.agent_api import (
    AgentApiConfig,
    AgentApiError,
    Transaction,
    UrlLibAgentApi,
    should_categorize,
)

FOOD_ID = UUID("11111111-1111-1111-1111-111111111111")
TXN_ID = UUID("22222222-2222-2222-2222-222222222222")
AGENT_BEARER = "synthetic-agent-token"


def _config() -> AgentApiConfig:
    return AgentApiConfig(api_base="http://127.0.0.1:8000", token=AGENT_BEARER)


def _transaction(**overrides: object) -> Transaction:
    values: dict[str, object] = {
        "id": TXN_ID,
        "version": 3,
        "counterparty": "Synthetic Coffee",
        "amount": "-12.34",
        "currency": "SGD",
        "effective_date": "2026-01-10",
        "kind": "expense",
        "categories": ("Uncategorized",),
        "review_choices": ("categorize",),
    }
    values.update(overrides)
    return Transaction(**values)  # type: ignore[arg-type]


def test_should_categorize_skips_non_expenses_and_assigned_rows() -> None:
    assert should_categorize(_transaction()) is True
    assert should_categorize(_transaction(kind="cash_withdrawal")) is True
    assert should_categorize(_transaction(kind="transfer")) is False
    assert should_categorize(_transaction(review_choices=("accept",))) is False
    assert should_categorize(_transaction(categories=("Synthetic Food",))) is False


def test_http_client_uses_idempotency_and_if_match(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    class FakeResponse:
        def __init__(self, body: dict[str, object]) -> None:
            self._body = json.dumps(body).encode()

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        del timeout
        requests.append(request)
        path = request.full_url
        if path.endswith("/api/v1/agent/reviews"):
            return FakeResponse(
                {"items": [{"transaction_id": str(TXN_ID), "choices": ["categorize"]}]}
            )
        if path.endswith("/api/v1/agent/categories"):
            return FakeResponse(
                {"items": [{"id": str(FOOD_ID), "name": "Synthetic Food", "parent_id": None}]}
            )
        if path.endswith(f"/api/v1/agent/transactions/{TXN_ID}"):
            return FakeResponse(
                {
                    "id": str(TXN_ID),
                    "version": 3,
                    "counterparty": "Synthetic Coffee",
                    "amount": {"amount": "-12.34", "currency": "SGD"},
                    "effective_date": "2026-01-10",
                    "kind": "expense",
                    "categories": [],
                    "review_choices": ["categorize"],
                }
            )
        if path.endswith(f"/api/v1/agent/transactions/{TXN_ID}/category"):
            return FakeResponse({"id": str(TXN_ID), "version": 4})
        raise AssertionError(path)

    monkeypatch.setattr("scripts.agent.agent_api.urlopen", fake_urlopen)
    client = UrlLibAgentApi(_config())
    assert client.list_reviews() == (TXN_ID,)
    assert client.list_categories()[0].name == "Synthetic Food"
    transaction = client.get_transaction(TXN_ID)
    client.categorize(
        transaction_id=transaction.id,
        version=transaction.version,
        category_id=FOOD_ID,
        idempotency_key="synthetic-key",
    )
    categorize = requests[-1]
    headers = {key.lower(): value for key, value in categorize.header_items()}
    assert headers["idempotency-key"] == "synthetic-key"
    assert headers["if-match"] == f'"transaction:{TXN_ID}:v3"'
    assert AGENT_BEARER not in repr(categorize.full_url)
    assert AGENT_BEARER not in repr(_config())


def test_http_errors_do_not_include_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> None:
        del timeout
        raise HTTPError(request.full_url, 401, "nope", hdrs=None, fp=None)  # type: ignore[arg-type]

    monkeypatch.setattr("scripts.agent.agent_api.urlopen", fake_urlopen)
    with pytest.raises(AgentApiError, match="HTTP 401") as error:
        UrlLibAgentApi(_config()).list_reviews()
    assert AGENT_BEARER not in str(error.value)


def test_unavailable_api_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> None:
        del request, timeout
        raise URLError("down")

    monkeypatch.setattr("scripts.agent.agent_api.urlopen", fake_urlopen)
    with pytest.raises(AgentApiError, match="unavailable"):
        UrlLibAgentApi(_config()).list_reviews()
