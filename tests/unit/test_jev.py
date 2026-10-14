from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar
from uuid import UUID, uuid4

import pytest
from typesafe_sdk import Choice, TypeSafeAPITimeoutError, TypeSafeError

from billzebub.agent_mcp import assert_agent_safe
from billzebub.jev import (
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MODEL,
    SKIP_AMBIGUOUS_CATEGORY,
    SKIP_LOW_CONFIDENCE,
    SKIP_MISSING_CHOICE,
    SKIP_MISSING_CONFIDENCE,
    SKIP_UNKNOWN_CATEGORY,
    TYPESAFE_ENDPOINT,
    UNCATEGORIZED_NAME,
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
from billzebub.recurrings import normalize_counterparty

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


class FakeSystemOneResponse:
    def __init__(
        self,
        *,
        choice: str = "Synthetic Food",
        confidence: float = 0.91,
        model: str = DEFAULT_MODEL,
    ) -> None:
        self.model = model
        self.choices = {"category": FakeChoiceAnswer(choice, confidence)}
        self.answers = dict(self.choices)


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
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    omitted_noul = parse_jev_proposal(
        "Synthetic Food",
        0.99,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    boundary = parse_jev_proposal(
        "Synthetic Food",
        0.5,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    uncategorized_choice = parse_jev_proposal(
        UNCATEGORIZED_NAME,
        0.99,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    unknown = parse_jev_proposal(
        "Invented",
        0.99,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    apply = parse_jev_proposal(
        "Synthetic Food",
        0.51,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    assert low_confidence.action == "skip"
    assert low_confidence.skip_reason == SKIP_LOW_CONFIDENCE
    assert omitted_noul.action == "apply"
    assert omitted_noul.noul is None
    assert omitted_noul.skip_reason is None
    assert boundary.action == "apply"
    assert uncategorized_choice.action == "skip"
    assert uncategorized_choice.skip_reason == SKIP_UNKNOWN_CATEGORY
    assert unknown.action == "skip"
    assert unknown.skip_reason == SKIP_UNKNOWN_CATEGORY
    assert apply.action == "apply"
    assert apply.category_id == FOOD_ID
    assert apply.choice == "Synthetic Food"
    assert apply.noul is None
    assert low_confidence.choice == "Synthetic Food"
    assert low_confidence.noul is None
    assert uncategorized_choice.choice == UNCATEGORIZED_NAME


def test_state_is_agent_safe_and_questions_are_catalog_choice_only() -> None:
    state = jev_state(_subject())
    catalog = (
        _category(),
        JevCategory(id=uuid4(), name="Uncategorized"),
    )
    criteria = choice_criteria(catalog)
    questions = jev_questions(catalog)
    assert state == {
        "counterparty": "Synthetic Coffee",
        "normalized_counterparty": "synthetic coffee",
        "amount": "-12.34",
        "currency": "SGD",
        "effective_date": "2026-01-10",
        "kind": "expense",
    }
    assert_agent_safe(state)
    assert "source_artifact_id" not in state
    assert criteria == {"Synthetic Food": "Synthetic Food"}
    assert UNCATEGORIZED_NAME not in {name.casefold() for name in criteria}
    assert "skip" not in criteria
    assert tuple(questions) == ("category",)
    assert isinstance(questions["category"], Choice)
    assert "enough_evidence" not in questions
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


def test_typesafe_timeout_becomes_a_retryable_jev_error(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTypeSafeClient.last_call = {}
    FakeTypeSafeClient.error = TypeSafeAPITimeoutError(30.0)
    monkeypatch.setattr("billzebub.jev.TypeSafeClient", FakeTypeSafeClient)

    with pytest.raises(JevError, match="systemone failed"):
        JevProposer(_config()).propose(_subject(), (_category(),))


def test_jev_client_parses_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTypeSafeClient.last_init = {}
    FakeTypeSafeClient.last_call = {}
    FakeTypeSafeClient.error = None
    FakeTypeSafeClient.response = FakeSystemOneResponse(choice="Synthetic Food", confidence=0.51)
    monkeypatch.setattr("billzebub.jev.TypeSafeClient", FakeTypeSafeClient)
    proposal = JevProposer(_config()).propose(_subject(), (_category(),))
    assert proposal.action == "apply"
    assert proposal.category_id == FOOD_ID
    assert proposal.model == DEFAULT_MODEL
    assert proposal.noul is None
    state = FakeTypeSafeClient.last_call["state"]
    questions = FakeTypeSafeClient.last_call["questions"]
    assert state["counterparty"] == "Synthetic Coffee"
    assert state["normalized_counterparty"] == normalize_counterparty("Synthetic Coffee")
    assert questions["category"].criteria == {"Synthetic Food": "Synthetic Food"}
    assert "enough_evidence" not in questions


def test_normalized_counterparty_is_sent_beside_the_raw_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "SPOTIFY P45AE6BD59 Stockholm"
    FakeTypeSafeClient.last_call = {}
    FakeTypeSafeClient.error = None
    FakeTypeSafeClient.response = FakeSystemOneResponse(choice="Synthetic Food", confidence=0.91)
    monkeypatch.setattr("billzebub.jev.TypeSafeClient", FakeTypeSafeClient)

    JevProposer(_config()).propose(_subject(counterparty=raw), (_category(),))

    state = FakeTypeSafeClient.last_call["state"]
    assert state["counterparty"] == raw
    assert state["normalized_counterparty"] == normalize_counterparty(raw)
    assert state["normalized_counterparty"] == "spotify stockholm"
    assert_agent_safe(state)


def test_duplicate_catalog_names_fail_closed() -> None:
    categories = (
        JevCategory(id=FOOD_ID, name="Synthetic Food"),
        JevCategory(id=uuid4(), name="Synthetic Food"),
    )
    proposal = parse_jev_proposal(
        "Synthetic Food",
        0.99,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    assert proposal.action == "skip"
    assert proposal.skip_reason == SKIP_AMBIGUOUS_CATEGORY
    assert proposal.choice == "Synthetic Food"
    assert choice_criteria(categories) == {}


def test_choice_matching_accepts_paths_whitespace_and_nfkc() -> None:
    bank_id = uuid4()
    card_id = uuid4()
    bank_fees = JevCategory(id=FOOD_ID, name="Fees", parent_id=bank_id, parent_name="Bank")
    card_fees = JevCategory(id=uuid4(), name="Fees", parent_id=card_id, parent_name="Card")
    groceries = JevCategory(id=uuid4(), name="Groceries")
    slash_name = JevCategory(id=uuid4(), name="AC/DC")
    categories = (bank_fees, card_fees, groceries, slash_name)

    assert choice_criteria(categories) == {
        "Bank > Fees": "Bank > Fees",
        "Card > Fees": "Card > Fees",
        "Groceries": "Groceries",
        "AC/DC": "AC/DC",
    }

    greater = parse_jev_proposal(
        "  Bank   >   Fees ",
        0.97,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    slash = parse_jev_proposal("card/fees", 0.91, categories, Decimal("0.5"), model=DEFAULT_MODEL)
    spaced_slash = parse_jev_proposal(
        "Card / Fees",
        0.91,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    ambiguous = parse_jev_proposal("Fees", 0.99, categories, Decimal("0.5"), model=DEFAULT_MODEL)
    raw_groceries = "  " + "".join(chr(ord(char) + 0xFEE0) for char in "Groceries") + "  "
    folded = parse_jev_proposal(
        raw_groceries,
        0.95,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )
    band = parse_jev_proposal("ac/dc", 0.9, categories, Decimal("0.5"), model=DEFAULT_MODEL)
    missing_choice = parse_jev_proposal(None, 0.9, categories, Decimal("0.5"), model=DEFAULT_MODEL)
    missing_confidence = parse_jev_proposal(
        "Groceries",
        None,
        categories,
        Decimal("0.5"),
        model=DEFAULT_MODEL,
    )

    assert greater.action == "apply"
    assert greater.category_id == FOOD_ID
    assert greater.choice == "  Bank   >   Fees "
    assert slash.action == "apply"
    assert slash.category_id == card_fees.id
    assert spaced_slash.category_id == card_fees.id
    assert ambiguous.action == "skip"
    assert ambiguous.skip_reason == SKIP_AMBIGUOUS_CATEGORY
    assert ambiguous.choice == "Fees"
    assert folded.action == "apply"
    assert folded.category_id == groceries.id
    assert folded.choice == raw_groceries
    assert band.action == "apply"
    assert band.category_id == slash_name.id
    assert missing_choice.skip_reason == SKIP_MISSING_CHOICE
    assert missing_confidence.skip_reason == SKIP_MISSING_CONFIDENCE
    assert missing_confidence.choice == "Groceries"


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
