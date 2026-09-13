"""Stateless stdio MCP adapter for the agent-safe HTTPS resource surface."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID


class McpConfigurationError(ValueError):
    """The local MCP adapter has not been given a safe API configuration."""


class McpRequestError(ValueError):
    """An MCP tool request is invalid or the HTTP resource was unavailable."""


FORBIDDEN_AGENT_FIELDS = frozenset(
    {
        "financial_account_id",
        "account_id",
        "source_artifact_id",
        "artifact_id",
        "claim_id",
        "claims",
        "raw_description",
        "description_raw",
        "locator",
        "audit",
        "audit_log",
        "provenance",
        "extraction_id",
        "statement_path",
        "credential",
        "password",
        "token",
    }
)


class AgentHttpClient(Protocol):
    def list_transactions(self, *, cursor: str | None, limit: int) -> dict[str, Any]: ...

    def list_categories(self) -> dict[str, Any]: ...

    def list_reviews(self) -> dict[str, Any]: ...

    def categorize(
        self,
        *,
        transaction_id: UUID,
        version: int,
        category_id: UUID,
        idempotency_key: str,
    ) -> dict[str, Any]: ...

    def propose(
        self,
        *,
        transaction_id: UUID,
        version: int,
        proposal_type: str,
        summary: str,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class McpConfig:
    api_url: str
    token: str

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> McpConfig:
        values = os.environ if environ is None else environ
        api_url = values.get("BILLZEBUB_API_URL", "").strip().rstrip("/")
        token = values.get("BILLZEBUB_AGENT_TOKEN", "").strip()
        parsed = urlparse(api_url)
        loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        if not api_url or not token or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise McpConfigurationError("BILLZEBUB_API_URL and BILLZEBUB_AGENT_TOKEN are required")
        if parsed.scheme != "https" and not loopback:
            raise McpConfigurationError("BILLZEBUB_API_URL must use HTTPS outside loopback")
        return cls(api_url=api_url, token=token)


class HttpsAgentClient:
    """Small HTTP client that never logs a bearer token or response body."""

    def __init__(self, config: McpConfig, *, timeout_seconds: float = 15.0) -> None:
        self._config = config
        self._timeout_seconds = timeout_seconds

    def list_transactions(self, *, cursor: str | None, limit: int) -> dict[str, Any]:
        query = f"?limit={limit}"
        if cursor is not None:
            from urllib.parse import quote

            query += f"&cursor={quote(cursor, safe='')}"
        return self._request("GET", f"/api/v1/agent/transactions{query}")

    def list_categories(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/agent/categories")

    def list_reviews(self) -> dict[str, Any]:
        return self._request("GET", "/api/v1/agent/reviews")

    def categorize(
        self,
        *,
        transaction_id: UUID,
        version: int,
        category_id: UUID,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/agent/transactions/{transaction_id}/category",
            body={"category_id": str(category_id)},
            headers={
                "Idempotency-Key": idempotency_key,
                "If-Match": _etag(transaction_id, version),
            },
        )

    def propose(
        self,
        *,
        transaction_id: UUID,
        version: int,
        proposal_type: str,
        summary: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/v1/agent/transactions/{transaction_id}/proposals",
            body={"proposal_type": proposal_type, "summary": summary},
            headers={
                "Idempotency-Key": idempotency_key,
                "If-Match": _etag(transaction_id, version),
            },
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
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
            f"{self._config.api_url}{path}",
            data=encoded_body,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = response.read()
        except HTTPError as error:
            raise McpRequestError(f"agent API returned HTTP {error.code}") from error
        except URLError as error:
            raise McpRequestError("agent API is unavailable") from error
        try:
            decoded = json.loads(payload)
        except (TypeError, json.JSONDecodeError) as error:
            raise McpRequestError("agent API returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise McpRequestError("agent API returned an invalid resource")
        assert_agent_safe(decoded)
        return decoded


class AgentMcp:
    """MCP method dispatcher restricted to the eight approved agent operations."""

    protocol_version = "2024-11-05"

    def __init__(self, client: AgentHttpClient) -> None:
        self._client = client
        self._tools: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "list_transactions": self._list_transactions,
            "list_categories": self._list_categories,
            "list_reviews": self._list_reviews,
            "categorize_transaction": self._categorize_transaction,
            "propose_correction": self._proposal("correction"),
            "propose_reconciliation": self._proposal("reconciliation"),
            "propose_counterparty_change": self._proposal("counterparty_change"),
            "propose_category_split": self._proposal("category_split"),
        }

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "list_transactions",
                "description": "List agent-safe transactions in descending effective-date order.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "cursor": {"type": "string", "maxLength": 512},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "list_categories",
                "description": "List Categories available for explicit categorization.",
                "inputSchema": _empty_schema(),
            },
            {
                "name": "list_reviews",
                "description": "List agent-safe pending review choices.",
                "inputSchema": _empty_schema(),
            },
            {
                "name": "categorize_transaction",
                "description": (
                    "Categorize one current Expense using its observed resource version."
                ),
                "inputSchema": _categorize_schema(),
            },
            *[
                {
                    "name": name,
                    "description": description,
                    "inputSchema": _proposal_schema(),
                }
                for name, description in (
                    ("propose_correction", "Create an owner-reviewed Correction proposal."),
                    ("propose_reconciliation", "Create an owner-reviewed Reconciliation proposal."),
                    (
                        "propose_counterparty_change",
                        "Create an owner-reviewed Counterparty change proposal.",
                    ),
                    ("propose_category_split", "Create an owner-reviewed Category Split proposal."),
                )
            ],
        ]

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        method = request.get("method")
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return _error(request_id, -32600, "Invalid Request")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return _result(
                request_id,
                {
                    "protocolVersion": self.protocol_version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "billzebub-agent", "version": "1.0.0"},
                },
            )
        if method == "tools/list":
            return _result(request_id, {"tools": self.tool_definitions()})
        if method != "tools/call":
            return _error(request_id, -32601, "Method not found")
        try:
            params = _object(request.get("params"))
            name = _string(params, "name", maximum=100)
            arguments = _object(params.get("arguments", {}))
            tool = self._tools.get(name)
            if tool is None:
                raise McpRequestError("unknown tool")
            resource = tool(arguments)
            assert_agent_safe(resource)
        except McpRequestError:
            return _tool_error(request_id, "Tool request failed")
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(resource, separators=(",", ":"))}],
                "structuredContent": resource,
            },
        )

    def _list_transactions(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _only(arguments, {"cursor", "limit"})
        cursor = arguments.get("cursor")
        if cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 512):
            raise McpRequestError("invalid cursor")
        limit = arguments.get("limit", 50)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise McpRequestError("invalid limit")
        return self._client.list_transactions(cursor=cursor, limit=limit)

    def _list_categories(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _only(arguments, set())
        return self._client.list_categories()

    def _list_reviews(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _only(arguments, set())
        return self._client.list_reviews()

    def _categorize_transaction(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _only(arguments, {"transaction_id", "version", "category_id", "idempotency_key"})
        return self._client.categorize(
            transaction_id=_uuid(arguments, "transaction_id"),
            version=_version(arguments),
            category_id=_uuid(arguments, "category_id"),
            idempotency_key=_idempotency_key(arguments),
        )

    def _proposal(self, proposal_type: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def submit(arguments: dict[str, Any]) -> dict[str, Any]:
            _only(arguments, {"transaction_id", "version", "summary", "idempotency_key"})
            summary = _string(arguments, "summary", maximum=500)
            return self._client.propose(
                transaction_id=_uuid(arguments, "transaction_id"),
                version=_version(arguments),
                proposal_type=proposal_type,
                summary=summary,
                idempotency_key=_idempotency_key(arguments),
            )

        return submit


def run_stdio(
    *,
    server: AgentMcp | None = None,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    """Run one newline-delimited JSON-RPC message at a time, without stdout logging."""
    resolved_server = server or AgentMcp(HttpsAgentClient(McpConfig.from_environment()))
    stdin = input_stream or sys.stdin
    stdout = output_stream or sys.stdout
    for line in stdin:
        try:
            request = json.loads(line)
            response = resolved_server.handle(_object(request))
        except (TypeError, json.JSONDecodeError, McpRequestError):
            response = _error(None, -32700, "Parse error")
        if response is not None:
            stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            stdout.flush()
    return 0


def assert_agent_safe(value: object) -> None:
    """Reject an accidental internal-field leak before it reaches an MCP client."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str) or key.casefold() in FORBIDDEN_AGENT_FIELDS:
                raise McpRequestError("agent resource contains a forbidden field")
            assert_agent_safe(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_agent_safe(nested)


def _empty_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False}


def _categorize_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "transaction_id": {"type": "string", "format": "uuid"},
            "version": {"type": "integer", "minimum": 1},
            "category_id": {"type": "string", "format": "uuid"},
            "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 255},
        },
        "required": ["transaction_id", "version", "category_id", "idempotency_key"],
        "additionalProperties": False,
    }


def _proposal_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "transaction_id": {"type": "string", "format": "uuid"},
            "version": {"type": "integer", "minimum": 1},
            "summary": {"type": "string", "minLength": 1, "maxLength": 500},
            "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 255},
        },
        "required": ["transaction_id", "version", "summary", "idempotency_key"],
        "additionalProperties": False,
    }


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise McpRequestError("object required")
    return value


def _string(values: dict[str, Any], name: str, *, maximum: int) -> str:
    value = values.get(name)
    if not isinstance(value, str):
        raise McpRequestError(f"{name} is required")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise McpRequestError(f"{name} is invalid")
    return normalized


def _uuid(values: dict[str, Any], name: str) -> UUID:
    try:
        return UUID(_string(values, name, maximum=36))
    except ValueError as error:
        raise McpRequestError(f"{name} is invalid") from error


def _version(values: dict[str, Any]) -> int:
    version = values.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise McpRequestError("version is invalid")
    return version


def _idempotency_key(values: dict[str, Any]) -> str:
    return _string(values, "idempotency_key", maximum=255)


def _only(values: dict[str, Any], allowed: set[str]) -> None:
    if set(values) - allowed:
        raise McpRequestError("unexpected tool arguments")


def _etag(transaction_id: UUID, version: int) -> str:
    return f'"transaction:{transaction_id}:v{version}"'


def _result(request_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_error(request_id: object, message: str) -> dict[str, Any]:
    return _result(
        request_id,
        {"content": [{"type": "text", "text": message}], "isError": True},
    )
