from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from scripts.agent.agent_api import AgentApiError, Category, Transaction
from scripts.agent.jev_categorize import (
    DEFAULT_MODEL,
    SKIP_OPTION,
    TYPESAFE_ENDPOINT,
    JevError,
    JevProposer,
    Proposal,
    RunnerConfig,
    RunnerError,
    choice_criteria,
    idempotency_key,
    jev_questions,
    jev_state,
    main,
    parse_jev_proposal,
    run,
    should_ask_jev,
)
from typesafe_sdk import Choice, Noul, TypeSafeError

FOOD_ID = UUID("11111111-1111-1111-1111-111111111111")
TXN_ID = UUID("22222222-2222-2222-2222-222222222222")
AGENT_BEARER = "synthetic-agent-token"
TYPESAFE_KEY = "synthetic-typesafe-key"


def _config(**overrides: object) -> RunnerConfig:
    values: dict[str, object] = {
        "api_base": "http://127.0.0.1:8000",
        "token": AGENT_BEARER,
        "typesafe_api_key": TYPESAFE_KEY,
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
        "TYPESAFE_API_KEY": TYPESAFE_KEY,
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
            confidence=Decimal("0.91"),
            model=DEFAULT_MODEL,
        )
        self.error = error
        self.calls: list[UUID] = []

    def propose(self, transaction: Transaction, categories: Sequence[Category]) -> Proposal:
        del categories
        self.calls.append(transaction.id)
        if self.error:
            raise JevError("typesafe systemone failed")
        return self.proposal


class FakeChoiceAnswer:
    def __init__(self, choice: str, confidence: float) -> None:
        self.choice = choice
        self.confidence = confidence


class FakeNoulAnswer:
    def __init__(self, noul: float) -> None:
        self.noul = noul


class FakeSystemOneResponse:
    def __init__(
        self,
        *,
        choice: str = "Synthetic Food",
        confidence: float = 0.91,
        noul: float = 0.93,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.model = model
        self.choices = {"category": FakeChoiceAnswer(choice, confidence)}
        self.nouls = {"enough_evidence": FakeNoulAnswer(noul)}
        self.answers = {**self.choices, **self.nouls}


class FakeTypeSafeClient:
    last_init: ClassVar[dict[str, Any]] = {}
    last_call: ClassVar[dict[str, Any]] = {}
    response: ClassVar[FakeSystemOneResponse] = FakeSystemOneResponse()
    error: ClassVar[Exception | None] = None

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_init = kwargs

    def __enter__(self) -> FakeTypeSafeClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def system_one(self, **kwargs: Any) -> FakeSystemOneResponse:
        type(self).last_call = kwargs
        if self.error is not None:
            raise self.error
        return self.response


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
        (TXN_ID, 3, FOOD_ID, f"jev-cat:{TXN_ID}:v3:{FOOD_ID}"),
    ]
    assert "applied=1" in stdout.getvalue()
    assert AGENT_BEARER not in stdout.getvalue()
    assert TYPESAFE_KEY not in stdout.getvalue()


def test_skips_transfers_without_calling_jev() -> None:
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


def test_proposal_gating_is_fail_closed() -> None:
    categories = (_category(),)
    low_confidence = parse_jev_proposal(
        "Synthetic Food",
        0.4,
        0.99,
        categories,
        Decimal("0.85"),
        model=DEFAULT_MODEL,
    )
    low_noul = parse_jev_proposal(
        "Synthetic Food",
        0.99,
        0.4,
        categories,
        Decimal("0.85"),
        model=DEFAULT_MODEL,
    )
    skip_option = parse_jev_proposal(
        SKIP_OPTION,
        0.99,
        0.99,
        categories,
        Decimal("0.85"),
        model=DEFAULT_MODEL,
    )
    unknown = parse_jev_proposal(
        "Invented",
        0.99,
        0.99,
        categories,
        Decimal("0.85"),
        model=DEFAULT_MODEL,
    )
    mismatched = parse_jev_proposal(
        "Synthetic Transport",
        0.99,
        0.99,
        categories,
        Decimal("0.85"),
        model=DEFAULT_MODEL,
    )
    apply = parse_jev_proposal(
        "Synthetic Food",
        0.91,
        0.93,
        categories,
        Decimal("0.85"),
        model=DEFAULT_MODEL,
    )
    assert low_confidence.action == "skip"
    assert low_noul.action == "skip"
    assert skip_option.action == "skip"
    assert unknown.action == "skip"
    assert mismatched.action == "skip"
    assert apply.action == "apply"
    assert apply.category_id == FOOD_ID
    assert apply.category_name == "Synthetic Food"


def test_undetermined_jev_result_leaves_review() -> None:
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


def test_dry_run_calls_jev_but_does_not_post_categorize() -> None:
    api = FakeApi()
    stdout = StringIO()
    proposer = FakeProposer()

    assert run(_config(dry_run=True), api, proposer, stdout=stdout) == 0
    assert proposer.calls == [TXN_ID]
    assert api.categorize_calls == []
    assert "dry-run" in stdout.getvalue()


def test_already_categorized_expense_is_not_sent_to_jev() -> None:
    api = FakeApi(transaction=_transaction(categories=("Synthetic Food",)))
    proposer = FakeProposer()

    run(_config(), api, proposer, stdout=StringIO())
    assert proposer.calls == []


def test_should_ask_jev_requires_categorize_choice() -> None:
    assert should_ask_jev(_transaction(review_choices=("accept",))) is False
    assert should_ask_jev(_transaction()) is True
    assert should_ask_jev(_transaction(kind="cash_withdrawal")) is True


def test_main_empty_queue_does_not_print_secrets() -> None:
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
    assert TYPESAFE_KEY not in stdout.getvalue()


def test_secret_files_are_read_and_world_readable_files_are_rejected(
    tmp_path: Path,
) -> None:
    token_file = tmp_path / "agent-token"
    token_file.write_text(f"{AGENT_BEARER}\n", encoding="utf-8")
    token_file.chmod(0o600)
    key_file = tmp_path / "typesafe-key"
    key_file.write_text(f"{TYPESAFE_KEY}\n", encoding="utf-8")
    key_file.chmod(0o600)
    config = RunnerConfig.from_environment(
        {
            "BILLZEBUB_API_BASE": "https://billzebub.example.test",
            "TYPESAFE_API_KEY_FILE": str(key_file),
        },
        token_file=token_file,
    )
    assert config.token == AGENT_BEARER
    assert config.typesafe_api_key == TYPESAFE_KEY
    assert config.api_base == "https://billzebub.example.test"
    assert AGENT_BEARER not in repr(config)
    assert TYPESAFE_KEY not in repr(config)

    key_file.chmod(0o644)
    with pytest.raises(RunnerError, match="unsafe"):
        RunnerConfig.from_environment(
            _env(TYPESAFE_API_KEY_FILE=str(key_file), TYPESAFE_API_KEY=""),
            token_file=token_file,
        )


def test_https_is_required_outside_loopback() -> None:
    with pytest.raises(RunnerError, match="HTTPS"):
        RunnerConfig.from_environment(_env(BILLZEBUB_API_BASE="http://nas.example.test"))


def test_missing_tokens_fail_closed() -> None:
    with pytest.raises(RunnerError, match="TOKEN"):
        RunnerConfig.from_environment(
            {"BILLZEBUB_API_BASE": "http://127.0.0.1:8000", "TYPESAFE_API_KEY": TYPESAFE_KEY}
        )
    with pytest.raises(RunnerError, match="TYPESAFE"):
        RunnerConfig.from_environment(
            {"BILLZEBUB_API_BASE": "http://127.0.0.1:8000", "BILLZEBUB_AGENT_TOKEN": AGENT_BEARER}
        )


def test_state_is_agent_safe_and_questions_include_skip() -> None:
    state = jev_state(_transaction())
    criteria = choice_criteria((_category(),))
    questions = jev_questions((_category(),))
    assert state == {
        "counterparty": "Synthetic Coffee",
        "amount": "-12.34",
        "currency": "SGD",
        "effective_date": "2026-01-10",
        "kind": "expense",
    }
    assert "source_artifact_id" not in state
    assert str(TXN_ID) not in state.values()
    assert criteria["Synthetic Food"] == "Synthetic Food"
    assert SKIP_OPTION in criteria
    assert isinstance(questions["category"], Choice)
    assert isinstance(questions["enough_evidence"], Noul)
    assert AGENT_BEARER not in str(state)
    assert TYPESAFE_KEY not in str(state)


def test_jev_client_pins_model_and_does_not_post_on_sdk_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeTypeSafeClient.last_init = {}
    FakeTypeSafeClient.last_call = {}
    FakeTypeSafeClient.response = FakeSystemOneResponse()
    FakeTypeSafeClient.error = TypeSafeError("nope")
    monkeypatch.setattr("scripts.agent.jev_categorize.TypeSafeClient", FakeTypeSafeClient)
    proposer = JevProposer(_config())

    with pytest.raises(JevError, match="systemone failed") as error:
        proposer.propose(_transaction(), (_category(),))

    assert TYPESAFE_KEY not in str(error.value)
    assert FakeTypeSafeClient.last_init["model"] == DEFAULT_MODEL
    assert FakeTypeSafeClient.last_init["api_key"] == TYPESAFE_KEY
    assert FakeTypeSafeClient.last_init["base_url"] == "https://api.typesafe.ai"
    assert FakeTypeSafeClient.last_call["model"] == DEFAULT_MODEL


def test_jev_client_parses_choice_and_noul(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTypeSafeClient.last_init = {}
    FakeTypeSafeClient.last_call = {}
    FakeTypeSafeClient.error = None
    FakeTypeSafeClient.response = FakeSystemOneResponse(
        choice="Synthetic Food", confidence=0.91, noul=0.94
    )
    monkeypatch.setattr("scripts.agent.jev_categorize.TypeSafeClient", FakeTypeSafeClient)
    proposal = JevProposer(_config()).propose(_transaction(), (_category(),))
    assert proposal.action == "apply"
    assert proposal.category_id == FOOD_ID
    assert proposal.model == DEFAULT_MODEL
    state = FakeTypeSafeClient.last_call["state"]
    questions = FakeTypeSafeClient.last_call["questions"]
    assert state["counterparty"] == "Synthetic Coffee"
    assert SKIP_OPTION in questions["category"].criteria
    assert "enough_evidence" in questions


def test_apply_http_failure_exits_nonzero() -> None:
    stdout = StringIO()
    assert run(_config(), FakeApi(fail_categorize=True), FakeProposer(), stdout=stdout) == 1
    assert "failed=1" in stdout.getvalue()
    assert AGENT_BEARER not in stdout.getvalue()
    assert TYPESAFE_KEY not in stdout.getvalue()


def test_idempotency_key_is_stable() -> None:
    assert idempotency_key(_transaction(), FOOD_ID) == f"jev-cat:{TXN_ID}:v3:{FOOD_ID}"


def test_duplicate_catalog_names_fail_closed() -> None:
    categories = (
        Category(id=FOOD_ID, name="Synthetic Food", parent_id=None),
        Category(id=uuid4(), name="Synthetic Food", parent_id=uuid4()),
    )
    proposal = parse_jev_proposal(
        "Synthetic Food",
        0.99,
        0.99,
        categories,
        Decimal("0.85"),
        model=DEFAULT_MODEL,
    )
    assert proposal.action == "skip"


def test_parser_has_no_typesafe_key_flag() -> None:
    from scripts.agent import jev_categorize as jev

    help_text = jev._parser().format_help()
    assert TYPESAFE_ENDPOINT == "https://api.typesafe.ai/v1/systemone"
    assert "TYPESAFE" not in help_text
    assert "--api-key" not in help_text
