from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from typesafe_sdk import Choice, Noul, TypeSafeError

from billzebub.jev import (
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MODEL,
    SKIP_OPTION,
    TYPESAFE_ENDPOINT,
    JevCategory,
    JevClientConfig,
    JevConfigurationError,
    JevError,
    JevProposer,
    JevSubject,
    choice_criteria,
    jev_questions,
    jev_state,
    parse_jev_proposal,
    safe_error_message,
)

FOOD_ID = UUID("11111111-1111-1111-1111-111111111111")
TYPESAFE_KEY = "synthetic-typesafe-key"


def _config(**overrides: object) -> JevClientConfig:
    values: dict[str, object] = {"typesafe_api_key": TYPESAFE_KEY}
    values.update(overrides)
    return JevClientConfig(**values)  # type: ignore[arg-type]


def _category() -> JevCategory:
    return JevCategory(id=FOOD_ID, name="Synthetic Food")


def _subject(**overrides: object) -> JevSubject:
    values: dict[str, object] = {
        "counterparty": "Synthetic Coffee",
        "amount": "-12.34",
        "currency": "SGD",
        "effective_date": "2026-01-10",
        "kind": "expense",
    }
    values.update(overrides)
    return JevSubject(**values)  # type: ignore[arg-type]


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


def test_default_min_confidence_is_half() -> None:
    assert DEFAULT_MIN_CONFIDENCE == Decimal("0.5")


def test_proposal_gating_is_fail_closed() -> None:
    categories = (_category(),)
    low_confidence = parse_jev_proposal(
        "Synthetic Food",
        0.49,
        0.99,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    low_noul = parse_jev_proposal(
        "Synthetic Food",
        0.99,
        0.49,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    boundary = parse_jev_proposal(
        "Synthetic Food",
        0.5,
        0.5,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    skip_option = parse_jev_proposal(
        SKIP_OPTION,
        0.99,
        0.99,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    unknown = parse_jev_proposal(
        "Invented",
        0.99,
        0.99,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    apply = parse_jev_proposal(
        "Synthetic Food",
        0.51,
        0.6,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    assert low_confidence.action == "skip"
    assert low_noul.action == "skip"
    assert boundary.action == "apply"
    assert skip_option.action == "skip"
    assert unknown.action == "skip"
    assert apply.action == "apply"
    assert apply.category_id == FOOD_ID
    assert apply.choice == "Synthetic Food"
    assert apply.noul == Decimal("0.6")
    assert low_confidence.choice == "Synthetic Food"
    assert low_confidence.noul == Decimal("0.99")
    assert skip_option.choice == SKIP_OPTION


def test_state_is_agent_safe_and_questions_include_skip() -> None:
    state = jev_state(_subject())
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
    assert criteria["Synthetic Food"] == "Synthetic Food"
    assert SKIP_OPTION in criteria
    assert isinstance(questions["category"], Choice)
    assert isinstance(questions["enough_evidence"], Noul)
    assert TYPESAFE_KEY not in str(state)


def test_jev_client_pins_model_and_does_not_post_on_sdk_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeTypeSafeClient.last_init = {}
    FakeTypeSafeClient.last_call = {}
    FakeTypeSafeClient.response = FakeSystemOneResponse()
    FakeTypeSafeClient.error = TypeSafeError("nope")
    monkeypatch.setattr("billzebub.jev.TypeSafeClient", FakeTypeSafeClient)
    proposer = JevProposer(_config())

    with pytest.raises(JevError, match="systemone failed") as error:
        proposer.propose(_subject(), (_category(),))

    assert TYPESAFE_KEY not in str(error.value)
    assert TYPESAFE_KEY not in str(error.value.__cause__)
    assert FakeTypeSafeClient.last_init["model"] == DEFAULT_MODEL
    assert FakeTypeSafeClient.last_init["api_key"] == TYPESAFE_KEY
    assert FakeTypeSafeClient.last_init["base_url"] == "https://api.typesafe.ai"
    assert FakeTypeSafeClient.last_call["model"] == DEFAULT_MODEL


def test_jev_client_parses_choice_and_noul(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTypeSafeClient.last_init = {}
    FakeTypeSafeClient.last_call = {}
    FakeTypeSafeClient.error = None
    FakeTypeSafeClient.response = FakeSystemOneResponse(
        choice="Synthetic Food", confidence=0.51, noul=0.6
    )
    monkeypatch.setattr("billzebub.jev.TypeSafeClient", FakeTypeSafeClient)
    proposal = JevProposer(_config()).propose(_subject(), (_category(),))
    assert proposal.action == "apply"
    assert proposal.category_id == FOOD_ID
    assert proposal.model == DEFAULT_MODEL
    state = FakeTypeSafeClient.last_call["state"]
    questions = FakeTypeSafeClient.last_call["questions"]
    assert state["counterparty"] == "Synthetic Coffee"
    assert SKIP_OPTION in questions["category"].criteria
    assert "enough_evidence" in questions


def test_duplicate_catalog_names_fail_closed() -> None:
    categories = (
        JevCategory(id=FOOD_ID, name="Synthetic Food"),
        JevCategory(id=uuid4(), name="Synthetic Food"),
    )
    proposal = parse_jev_proposal(
        "Synthetic Food",
        0.99,
        0.99,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    assert proposal.action == "skip"


def test_secret_files_and_unprefixed_env(tmp_path: Path) -> None:
    key_file = tmp_path / "typesafe-key"
    key_file.write_text(f"{TYPESAFE_KEY}\n", encoding="utf-8")
    key_file.chmod(0o600)
    config = JevClientConfig.from_environment(
        {
            "TYPESAFE_API_KEY_FILE": str(key_file),
            "BILLZEBUB_JEV_MIN_CONFIDENCE": "0.5",
        }
    )
    assert config is not None
    assert config.typesafe_api_key == TYPESAFE_KEY
    assert config.min_confidence == Decimal("0.5")
    assert config.model == DEFAULT_MODEL
    assert TYPESAFE_KEY not in repr(config)

    key_file.chmod(0o644)
    with pytest.raises(JevConfigurationError, match="unsafe"):
        JevClientConfig.from_environment({"TYPESAFE_API_KEY_FILE": str(key_file)})


def test_missing_key_can_fail_open_for_worker() -> None:
    assert JevClientConfig.from_environment({}, require_key=False) is None
    with pytest.raises(JevConfigurationError, match="TYPESAFE"):
        JevClientConfig.from_environment({}, require_key=True)


def test_endpoint_is_typesafe_system_one() -> None:
    assert TYPESAFE_ENDPOINT == "https://api.typesafe.ai/v1/systemone"


def test_safe_error_message_redacts_keys() -> None:
    message = safe_error_message(
        RuntimeError(f"api_key={TYPESAFE_KEY} boom"),
        secret=TYPESAFE_KEY,
    )
    assert TYPESAFE_KEY not in message
    assert "boom" in message
    assert "[redacted]" in message
