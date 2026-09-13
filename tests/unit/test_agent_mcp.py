import json
from io import StringIO
from uuid import UUID, uuid4

import pytest

from billzebub.agent_mcp import (
    FORBIDDEN_AGENT_FIELDS,
    AgentMcp,
    McpConfig,
    McpConfigurationError,
    assert_agent_safe,
    run_stdio,
)


class FakeClient:
    def __init__(self) -> None:
        self.transaction_id = uuid4()
        self.category_id = uuid4()
        self.calls: list[tuple[str, object]] = []

    def list_transactions(self, *, cursor: str | None, limit: int) -> dict[str, object]:
        self.calls.append(("list_transactions", (cursor, limit)))
        return {"items": [self._transaction()], "next_cursor": None}

    def _transaction(self) -> dict[str, object]:
        return {
            "id": str(self.transaction_id),
            "version": 3,
            "counterparty": "Synthetic Coffee",
            "amount": {"amount": "-12.34", "currency": "SGD"},
            "effective_date": "2026-01-10",
            "kind": "expense",
            "categories": [],
            "review_choices": ["categorize"],
        }

    def list_categories(self) -> dict[str, object]:
        self.calls.append(("list_categories", None))
        return {
            "items": [{"id": str(self.category_id), "name": "Synthetic Food", "parent_id": None}]
        }

    def list_reviews(self) -> dict[str, object]:
        self.calls.append(("list_reviews", None))
        return {"items": [{"transaction_id": str(self.transaction_id), "choices": ["categorize"]}]}

    def categorize(
        self,
        *,
        transaction_id: UUID,
        version: int,
        category_id: UUID,
        idempotency_key: str,
    ) -> dict[str, object]:
        self.calls.append(("categorize", (transaction_id, version, category_id, idempotency_key)))
        return self._transaction()

    def propose(
        self,
        *,
        transaction_id: UUID,
        version: int,
        proposal_type: str,
        summary: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        self.calls.append(
            (
                "propose",
                (transaction_id, version, proposal_type, summary, idempotency_key),
            )
        )
        return {
            "transaction_id": str(transaction_id),
            "proposal_type": proposal_type,
            "status": "pending",
        }


class UnsafeClient(FakeClient):
    def list_reviews(self) -> dict[str, object]:
        return {"items": [{"source_artifact_id": "not-safe"}]}


def test_mcp_exposes_exactly_eight_explicit_safe_tools() -> None:
    server = AgentMcp(FakeClient())

    definitions = server.tool_definitions()

    assert [definition["name"] for definition in definitions] == [
        "list_transactions",
        "list_categories",
        "list_reviews",
        "categorize_transaction",
        "propose_correction",
        "propose_reconciliation",
        "propose_counterparty_change",
        "propose_category_split",
    ]
    assert len(definitions) == 8
    assert_agent_safe({"tools": definitions})


def test_mcp_dispatches_approved_calls_and_recursive_responses_are_safe() -> None:
    client = FakeClient()
    server = AgentMcp(client)
    basic_calls = [
        ("list_transactions", {"limit": 1}),
        ("list_categories", {}),
        ("list_reviews", {}),
        (
            "categorize_transaction",
            {
                "transaction_id": str(client.transaction_id),
                "version": 3,
                "category_id": str(client.category_id),
                "idempotency_key": "synthetic-categorize",
            },
        ),
    ]
    proposal_calls = [
        (
            name,
            {
                "transaction_id": str(client.transaction_id),
                "version": 3,
                "summary": "Synthetic review",
                "idempotency_key": f"synthetic-{name}",
            },
        )
        for name in (
            "propose_correction",
            "propose_reconciliation",
            "propose_counterparty_change",
            "propose_category_split",
        )
    ]

    for index, (name, arguments) in enumerate([*basic_calls, *proposal_calls], start=1):
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": index,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )
        assert response is not None
        result = response["result"]
        assert "isError" not in result
        assert_agent_safe(result["structuredContent"])
        assert FORBIDDEN_AGENT_FIELDS.isdisjoint(_keys(result))

    assert [call[0] for call in client.calls] == [
        "list_transactions",
        "list_categories",
        "list_reviews",
        "categorize",
        "propose",
        "propose",
        "propose",
        "propose",
    ]


def test_mcp_rejects_unknown_tools_extra_arguments_and_leaked_http_fields() -> None:
    client = FakeClient()
    server = AgentMcp(client)

    unknown = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_claim", "arguments": {}},
        }
    )
    extra = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "list_reviews", "arguments": {"account_id": str(uuid4())}},
        }
    )
    leaked = AgentMcp(UnsafeClient()).handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "list_reviews", "arguments": {}},
        }
    )

    assert unknown is not None
    assert extra is not None
    assert leaked is not None
    assert unknown["result"]["isError"] is True
    assert extra["result"]["isError"] is True
    assert leaked["result"]["isError"] is True
    assert "source_artifact_id" not in json.dumps(leaked)


def test_mcp_stdio_handles_initialize_and_suppresses_notifications() -> None:
    client = FakeClient()
    output = StringIO()
    exit_code = run_stdio(
        server=AgentMcp(client),
        input_stream=StringIO(
            "\n".join(
                (
                    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                )
            )
            + "\n"
        ),
        output_stream=output,
    )

    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert exit_code == 0
    assert messages == [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "billzebub-agent", "version": "1.0.0"},
            },
        }
    ]


def test_mcp_configuration_requires_https_except_loopback() -> None:
    with pytest.raises(McpConfigurationError):
        McpConfig.from_environment(
            {"BILLZEBUB_API_URL": "http://nas.example.test", "BILLZEBUB_AGENT_TOKEN": "secret"}
        )

    config = McpConfig.from_environment(
        {"BILLZEBUB_API_URL": "http://127.0.0.1:8080/", "BILLZEBUB_AGENT_TOKEN": "secret"}
    )
    assert config.api_url == "http://127.0.0.1:8080"


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(nested) for nested in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(nested) for nested in value)) if value else set()
    return set()
