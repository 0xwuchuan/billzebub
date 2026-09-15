from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from uuid import UUID, uuid4

import pytest
from scripts.agent.codex_categorize import (
    DEFAULT_MODEL,
    FALLBACK_MODEL,
    OUTPUT_SCHEMA,
    AgentApiError,
    Category,
    CodexError,
    CodexProposer,
    Proposal,
    RunnerConfig,
    RunnerError,
    Transaction,
    UrlLibAgentApi,
    build_prompt,
    idempotency_key,
    main,
    parse_proposal,
    parse_proposal_json,
    run,
    should_ask_codex,
)

FOOD_ID = UUID("11111111-1111-1111-1111-111111111111")
TXN_ID = UUID("22222222-2222-2222-2222-222222222222")
AGENT_BEARER = "synthetic-agent-token"


def _config(**overrides: object) -> RunnerConfig:
    values: dict[str, object] = {
        "api_base": "http://127.0.0.1:8000",
        "token": AGENT_BEARER,
    }
    values.update(overrides)
    return RunnerConfig(**values)  # type: ignore[arg-type]


def _category() -> Category:
    return Category(id=FOOD_ID, name="Synthetic Food", parent_id=None)


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


def _env(**overrides: str) -> dict[str, str]:
    values = {
        "BILLZEBUB_API_BASE": "http://127.0.0.1:8000",
        "BILLZEBUB_AGENT_TOKEN": AGENT_BEARER,
    }
    values.update(overrides)
    return values


class FakeApi:
    def __init__(
        self,
        *,
        reviews: tuple[UUID, ...] = (TXN_ID,),
        transaction: Transaction | None = None,
        categories: tuple[Category, ...] | None = None,
        fail_categorize: bool = False,
    ) -> None:
        self.reviews = reviews
        self.transaction = transaction or _transaction()
        self.categories = categories if categories is not None else (_category(),)
        self.fail_categorize = fail_categorize
        self.categorize_calls: list[tuple[UUID, int, UUID, str]] = []

    def list_reviews(self) -> tuple[UUID, ...]:
        return self.reviews

    def list_categories(self) -> tuple[Category, ...]:
        return self.categories

    def get_transaction(self, transaction_id: UUID) -> Transaction:
        assert transaction_id == self.transaction.id
        return self.transaction

    def categorize(
        self,
        *,
        transaction_id: UUID,
        version: int,
        category_id: UUID,
        idempotency_key: str,
    ) -> None:
        if self.fail_categorize:
            raise AgentApiError("agent API returned HTTP 412")
        self.categorize_calls.append((transaction_id, version, category_id, idempotency_key))


class FakeProposer:
    def __init__(self, proposal: Proposal | None = None, *, error: bool = False) -> None:
        self.proposal = proposal or Proposal(
            action="apply",
            category_id=FOOD_ID,
            category_name="Synthetic Food",
            confidence=Decimal("0.99"),
            model=DEFAULT_MODEL,
        )
        self.error = error
        self.calls: list[UUID] = []

    def propose(self, transaction: Transaction, categories: Sequence[Category]) -> Proposal:
        del categories
        self.calls.append(transaction.id)
        if self.error:
            raise CodexError("codex exec failed")
        return self.proposal


def test_empty_review_queue_is_quiet_success() -> None:
    stdout = StringIO()
    api = FakeApi(reviews=())
    proposer = FakeProposer()

    assert run(_config(), api, proposer, stdout=stdout) == 0
    assert stdout.getvalue() == ""
    assert proposer.calls == []
    assert api.categorize_calls == []


def test_applies_high_confidence_proposal_with_idempotency_key() -> None:
    stdout = StringIO()
    api = FakeApi()
    proposer = FakeProposer()

    assert run(_config(), api, proposer, stdout=stdout) == 0
    assert api.categorize_calls == [
        (TXN_ID, 3, FOOD_ID, f"codex-cat:{TXN_ID}:v3:{FOOD_ID}"),
    ]
    assert "applied=1" in stdout.getvalue()
    assert AGENT_BEARER not in stdout.getvalue()


def test_skips_transfers_without_calling_codex() -> None:
    api = FakeApi(transaction=_transaction(kind="transfer"))
    proposer = FakeProposer()

    assert run(_config(), api, proposer, stdout=StringIO()) == 0
    assert proposer.calls == []
    assert api.categorize_calls == []


@pytest.mark.parametrize("kind", ["income", "refund", "reimbursement"])
def test_skips_income_refund_and_reimbursement(kind: str) -> None:
    api = FakeApi(transaction=_transaction(kind=kind))
    proposer = FakeProposer()
    run(_config(), api, proposer, stdout=StringIO())
    assert proposer.calls == []


def test_low_confidence_and_unknown_category_fail_closed() -> None:
    categories = (_category(),)
    low = parse_proposal(
        {
            "action": "apply",
            "category_id": str(FOOD_ID),
            "category_name": "Synthetic Food",
            "confidence": 0.4,
        },
        categories,
        Decimal("0.95"),
        model=DEFAULT_MODEL,
    )
    unknown = parse_proposal(
        {
            "action": "apply",
            "category_id": str(uuid4()),
            "category_name": "Invented",
            "confidence": 0.99,
        },
        categories,
        Decimal("0.95"),
        model=DEFAULT_MODEL,
    )
    mismatched = parse_proposal(
        {
            "action": "apply",
            "category_id": str(FOOD_ID),
            "category_name": "Synthetic Transport",
            "confidence": 0.99,
        },
        categories,
        Decimal("0.95"),
        model=DEFAULT_MODEL,
    )
    assert low.action == "skip"
    assert unknown.action == "skip"
    assert mismatched.action == "skip"


def test_undetermined_codex_result_leaves_review() -> None:
    api = FakeApi()
    proposer = FakeProposer(
        Proposal(
            action="skip",
            category_id=None,
            category_name=None,
            confidence=Decimal("0"),
            model=DEFAULT_MODEL,
        )
    )

    assert run(_config(), api, proposer, stdout=StringIO()) == 0
    assert api.categorize_calls == []
    assert proposer.calls == [TXN_ID]


def test_dry_run_does_not_post_categorize() -> None:
    api = FakeApi()
    stdout = StringIO()

    assert run(_config(dry_run=True), api, FakeProposer(), stdout=stdout) == 0
    assert api.categorize_calls == []
    assert "dry-run" in stdout.getvalue()


def test_already_categorized_expense_is_not_sent_to_codex() -> None:
    api = FakeApi(transaction=_transaction(categories=("Synthetic Food",)))
    proposer = FakeProposer()

    run(_config(), api, proposer, stdout=StringIO())
    assert proposer.calls == []


def test_should_ask_codex_requires_categorize_choice() -> None:
    assert should_ask_codex(_transaction(review_choices=("accept",))) is False
    assert should_ask_codex(_transaction()) is True


def test_main_empty_queue_does_not_print_the_token() -> None:
    stdout = StringIO()
    exit_code = main(
        [],
        environ=_env(),
        api=FakeApi(reviews=()),
        proposer=FakeProposer(),
        stdout=stdout,
    )
    assert exit_code == 0
    assert stdout.getvalue() == ""
    assert AGENT_BEARER not in stdout.getvalue()


def test_token_file_is_read_and_world_readable_files_are_rejected(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "agent-token"
    token_file.write_text(f"{AGENT_BEARER}\n", encoding="utf-8")
    token_file.chmod(0o600)
    config = RunnerConfig.from_environment(
        {"BILLZEBUB_API_BASE": "https://billzebub.example.test"},
        token_file=token_file,
    )
    assert config.token == AGENT_BEARER
    assert config.api_base == "https://billzebub.example.test"

    token_file.chmod(0o644)
    with pytest.raises(RunnerError, match="unsafe"):
        RunnerConfig.from_environment(
            {"BILLZEBUB_API_BASE": "http://127.0.0.1:8000"},
            token_file=token_file,
        )


def test_https_is_required_outside_loopback() -> None:
    with pytest.raises(RunnerError, match="HTTPS"):
        RunnerConfig.from_environment(_env(BILLZEBUB_API_BASE="http://nas.example.test"))


def test_missing_token_fails_closed() -> None:
    with pytest.raises(RunnerError, match="TOKEN"):
        RunnerConfig.from_environment({"BILLZEBUB_API_BASE": "http://127.0.0.1:8000"})


def test_prompt_lists_only_catalog_categories_and_agent_safe_fields() -> None:
    prompt = build_prompt(_transaction(), (_category(),))
    assert str(FOOD_ID) in prompt
    assert "Synthetic Coffee" in prompt
    assert "Synthetic Food" in prompt
    assert "source_artifact_id" not in prompt
    assert AGENT_BEARER not in prompt


def test_parse_proposal_json_rejects_non_objects() -> None:
    payload = parse_proposal_json(
        '{"action":"skip","category_id":null,"category_name":null,"confidence":0}'
    )
    assert payload["action"] == "skip"
    with pytest.raises(CodexError):
        parse_proposal_json("not json")


def test_codex_exec_uses_luna_then_terra_and_strips_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    envs: list[dict[str, str]] = []

    class Result:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_run(command: list[str], **kwargs: Any) -> Result:
        calls.append(command)
        envs.append(kwargs["env"])
        return Result()

    monkeypatch.setattr("scripts.agent.codex_categorize.subprocess.run", fake_run)
    monkeypatch.setenv("BILLZEBUB_AGENT_TOKEN", AGENT_BEARER)
    proposer = CodexProposer(_config())

    with pytest.raises(CodexError, match="luna and terra"):
        proposer.propose(_transaction(), (_category(),))

    assert [call[call.index("-m") + 1] for call in calls] == [DEFAULT_MODEL, FALLBACK_MODEL]
    assert all("--output-schema" in call for call in calls)
    assert all("exec" in call for call in calls)
    assert all(AGENT_BEARER not in command for command in calls)
    assert all("BILLZEBUB_AGENT_TOKEN" not in env for env in envs)


def test_codex_exec_parses_schema_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command: list[str], **kwargs: Any) -> Result:
        del kwargs
        output = Path(command[command.index("-o") + 1])
        output.write_text(
            json.dumps(
                {
                    "action": "apply",
                    "category_id": str(FOOD_ID),
                    "category_name": "Synthetic Food",
                    "confidence": 0.98,
                }
            ),
            encoding="utf-8",
        )
        return Result()

    monkeypatch.setattr("scripts.agent.codex_categorize.subprocess.run", fake_run)
    proposal = CodexProposer(_config()).propose(_transaction(), (_category(),))
    assert proposal.action == "apply"
    assert proposal.category_id == FOOD_ID
    assert proposal.model == DEFAULT_MODEL


def test_urlopen_client_lists_reviews_and_categorizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr("scripts.agent.codex_categorize.urlopen", fake_urlopen)
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


def test_http_errors_do_not_include_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> None:
        del timeout
        raise HTTPError(request.full_url, 401, "nope", hdrs=None, fp=None)  # type: ignore[arg-type]

    monkeypatch.setattr("scripts.agent.codex_categorize.urlopen", fake_urlopen)
    with pytest.raises(AgentApiError, match="HTTP 401") as error:
        UrlLibAgentApi(_config()).list_reviews()
    assert AGENT_BEARER not in str(error.value)


def test_unavailable_api_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: float) -> None:
        del request, timeout
        raise URLError("down")

    monkeypatch.setattr("scripts.agent.codex_categorize.urlopen", fake_urlopen)
    with pytest.raises(AgentApiError, match="unavailable"):
        UrlLibAgentApi(_config()).list_reviews()


def test_apply_http_failure_exits_nonzero() -> None:
    stdout = StringIO()
    assert run(_config(), FakeApi(fail_categorize=True), FakeProposer(), stdout=stdout) == 1
    assert "failed=1" in stdout.getvalue()
    assert AGENT_BEARER not in stdout.getvalue()


def test_output_schema_forbids_unknown_fields() -> None:
    properties = OUTPUT_SCHEMA["properties"]
    assert OUTPUT_SCHEMA["additionalProperties"] is False
    assert isinstance(properties, dict)
    assert "action" in properties


def test_idempotency_key_is_stable() -> None:
    assert idempotency_key(_transaction(), FOOD_ID) == f"codex-cat:{TXN_ID}:v3:{FOOD_ID}"
