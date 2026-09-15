import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from uuid6 import uuid7

from billzebub.apple_wallet import AppleWalletCaptureStatus, AppleWalletIngestion
from billzebub.artifact_capture import ArtifactArrivalInput, ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.financial_account_aliases import FinancialAccountAliases
from billzebub.imports import ImportCatalog
from billzebub.persistence.database import Database
from billzebub.persistence.models import (
    ArtifactArrival,
    Claim,
    Extraction,
    FinancialAccount,
    FinancialAccountKind,
    PendingReview,
    SourceArtifact,
)
from billzebub.review_actions import ReviewActions
from billzebub.reviews import ReviewDecision


def _account(database: Database) -> FinancialAccount:
    account = FinancialAccount(
        id=uuid7(),
        slug="synthetic-apple-card",
        display_name="Synthetic Apple Card",
        institution="synthetic",
        kind=FinancialAccountKind.CREDIT_CARD,
        default_currency="SGD",
        statement_adapter_key="synthetic-card",
        statement_account_identifier="synthetic-account",
        active=True,
    )
    with database.transaction() as session:
        session.add(account)
    return account


def _paylah_account(database: Database, *, slug: str = "synthetic-paylah") -> FinancialAccount:
    account = FinancialAccount(
        id=uuid7(),
        slug=slug,
        display_name="Synthetic PayLah",
        institution="dbs",
        kind=FinancialAccountKind.PAYLAH,
        default_currency="SGD",
        active=True,
    )
    with database.transaction() as session:
        session.add(account)
    return account


def _body(*, card: str = "Synthetic Wallet Card", amount: str = "$12.34") -> bytes:
    return (
        "{"
        '"schema_version":"probe-2",'
        '"name":"Synthetic name",'
        '"merchant":"Synthetic merchant",'
        f'"card":"{card}",'
        f'"amount":"{amount}",'
        '"date":"7 Mar 2026 at 9:05 PM"'
        "}"
    ).encode()


def _realtime_wallet_body(
    *,
    instrument: str = "Synthetic Wallet Card",
    use_card_alias: bool = False,
    extra: dict[str, str] | None = None,
) -> bytes:
    payload: dict[str, str] = {
        "schema_version": "realtime-1",
        "source": "apple_wallet",
        "name": "Synthetic name",
        "merchant": "Synthetic merchant",
        "amount": "$12.34",
        "date": "7 Mar 2026 at 9:05 PM",
    }
    if use_card_alias:
        payload["card"] = instrument
    else:
        payload["instrument"] = instrument
    if extra:
        payload.update(extra)
    return json.dumps(payload, separators=(",", ":")).encode()


def _realtime_paylah_body(*, extra: dict[str, str] | None = None) -> bytes:
    payload: dict[str, str] = {
        "schema_version": "realtime-1",
        "source": "paylah",
        "name": "Synthetic PayLah name",
        "amount": "$8.50",
        "date": "7 Mar 2026 at 9:05 PM",
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload, separators=(",", ":")).encode()


def _ingestion(database: Database, tmp_path: Path) -> AppleWalletIngestion:
    return AppleWalletIngestion(
        database,
        ArtifactCapture(ContentAddressedStore(tmp_path), database),
        FinancialAccountAliases(database),
        timezone=ZoneInfo("Asia/Singapore"),
    )


def _payload_review_context(
    failure_code: str, *, integration: str = "apple_wallet"
) -> dict[str, str]:
    return {
        "integration": integration,
        "failure_code": failure_code,
        "subject": "Shortcut payload rejected",
        "body": f"Shortcut ingest failed closed ({failure_code}) and created no Claims.",
    }


@pytest.mark.integration
def test_apple_wallet_capture_preserves_the_exact_body_and_creates_one_real_time_claim(
    database: Database,
    tmp_path: Path,
) -> None:
    account = _account(database)
    aliases = FinancialAccountAliases(database)
    aliases.add_apple_wallet_card(account_slug=account.slug, card_label="Synthetic Wallet Card")
    store = ContentAddressedStore(tmp_path)
    ingestion = AppleWalletIngestion(
        database,
        ArtifactCapture(store, database),
        aliases,
        timezone=ZoneInfo("Asia/Singapore"),
    )
    body = _body()

    accepted = ingestion.ingest(body, received_at=datetime.now(UTC), actor_id=None)
    replay = ingestion.ingest(body, received_at=datetime.now(UTC), actor_id=None)

    assert accepted.status is AppleWalletCaptureStatus.ACCEPTED
    assert accepted.duplicate is False
    assert replay.status is AppleWalletCaptureStatus.ACCEPTED
    assert replay.duplicate is True
    with database.transaction() as session:
        claim = session.scalar(select(Claim))
        assert claim is not None
        assert claim.claim_type == "real_time"
        assert claim.financial_account_id == account.id
        assert claim.authorized_amount == Decimal("-12.34")
        assert claim.authorized_currency == "SGD"
        assert claim.occurrence_at == datetime(2026, 3, 7, 13, 5, tzinfo=UTC)
        source_artifact = session.scalar(select(SourceArtifact))
        assert source_artifact is not None
        assert (
            store.verified_path(source_artifact.sha256, source_artifact.size).read_bytes() == body
        )
        assert session.scalar(select(func.count()).select_from(SourceArtifact)) == 1
        assert session.scalar(select(func.count()).select_from(ArtifactArrival)) == 2
        assert session.scalar(select(func.count()).select_from(Extraction)) == 1
        assert session.scalar(select(func.count()).select_from(Claim)) == 1
        arrivals = session.scalars(select(ArtifactArrival)).all()
        assert {arrival.source_type for arrival in arrivals} == {"apple_wallet_shortcut"}
        assert all(arrival.source_metadata["source"] == "apple_wallet" for arrival in arrivals)
        assert all(arrival.source_metadata["schema_version"] == "probe-2" for arrival in arrivals)
        extraction = session.scalar(select(Extraction))
        assert extraction is not None
        assert extraction.adapter_key == "apple_wallet_shortcut"
        assert claim.raw_description == "Synthetic merchant — Synthetic name"


@pytest.mark.integration
def test_apple_wallet_unknown_card_creates_blocking_review_without_claim(
    database: Database,
    tmp_path: Path,
) -> None:
    ingestion = AppleWalletIngestion(
        database,
        ArtifactCapture(ContentAddressedStore(tmp_path), database),
        FinancialAccountAliases(database),
        timezone=ZoneInfo("Asia/Singapore"),
    )

    outcome = ingestion.ingest(
        _body(card="Unmapped Synthetic Wallet Card"),
        received_at=datetime.now(UTC),
        actor_id=None,
    )

    assert outcome.status is AppleWalletCaptureStatus.REVIEW_REQUIRED
    with database.transaction() as session:
        extraction = session.scalar(select(Extraction))
        review = session.scalar(select(PendingReview))
        assert extraction is not None
        assert extraction.status == "failed"
        assert extraction.failure_code == "unmapped_card"
        assert review is not None
        assert review.severity == "blocking"
        assert review.condition_code == "apple_wallet_unmapped_card"
        assert review.context == {"integration": "apple_wallet"}
        assert session.scalar(select(func.count()).select_from(Claim)) == 0


@pytest.mark.integration
def test_apple_wallet_rejects_noncanonical_dollar_amount_without_claim(
    database: Database,
    tmp_path: Path,
) -> None:
    account = _account(database)
    aliases = FinancialAccountAliases(database)
    aliases.add_apple_wallet_card(account_slug=account.slug, card_label="Synthetic Wallet Card")
    ingestion = AppleWalletIngestion(
        database,
        ArtifactCapture(ContentAddressedStore(tmp_path), database),
        aliases,
        timezone=ZoneInfo("Asia/Singapore"),
    )

    outcome = ingestion.ingest(_body(amount="$12.3"), received_at=datetime.now(UTC), actor_id=None)

    assert outcome.status is AppleWalletCaptureStatus.REVIEW_REQUIRED
    with database.transaction() as session:
        extraction = session.scalar(select(Extraction))
        assert extraction is not None
        assert extraction.status == "failed"
        assert extraction.failure_code == "invalid_amount"
        assert session.scalar(select(func.count()).select_from(Claim)) == 0
        review = session.scalar(select(PendingReview))
        assert review is not None
        assert review.severity == "attention"
        assert review.condition_code == "shortcut_payload_invalid"
        assert review.context == _payload_review_context("invalid_amount")


@pytest.mark.integration
def test_realtime_apple_wallet_creates_real_time_claim_from_instrument(
    database: Database,
    tmp_path: Path,
) -> None:
    account = _account(database)
    aliases = FinancialAccountAliases(database)
    aliases.add_apple_wallet_card(account_slug=account.slug, card_label="Synthetic Wallet Card")
    ingestion = _ingestion(database, tmp_path)
    body = _realtime_wallet_body()

    outcome = ingestion.ingest(body, received_at=datetime.now(UTC), actor_id=None)

    assert outcome.status is AppleWalletCaptureStatus.ACCEPTED
    with database.transaction() as session:
        claim = session.scalar(select(Claim))
        extraction = session.scalar(select(Extraction))
        arrival = session.scalar(select(ArtifactArrival))
        assert claim is not None
        assert claim.claim_type == "real_time"
        assert claim.financial_account_id == account.id
        assert claim.authorized_amount == Decimal("-12.34")
        assert claim.authorized_currency == "SGD"
        assert claim.occurrence_at == datetime(2026, 3, 7, 13, 5, tzinfo=UTC)
        assert claim.raw_description == "Synthetic merchant — Synthetic name"
        assert extraction is not None
        assert extraction.adapter_key == "apple_wallet_shortcut"
        assert extraction.validation_report["source"] == "apple_wallet"
        assert arrival is not None
        assert arrival.source_type == "apple_wallet_shortcut"
        assert arrival.source_metadata["source"] == "apple_wallet"
        assert arrival.source_metadata["schema_version"] == "realtime-1"


@pytest.mark.integration
def test_realtime_apple_wallet_accepts_deprecated_card_alias(
    database: Database,
    tmp_path: Path,
) -> None:
    account = _account(database)
    aliases = FinancialAccountAliases(database)
    aliases.add_apple_wallet_card(account_slug=account.slug, card_label="Synthetic Wallet Card")
    ingestion = _ingestion(database, tmp_path)

    outcome = ingestion.ingest(
        _realtime_wallet_body(use_card_alias=True),
        received_at=datetime.now(UTC),
        actor_id=None,
    )

    assert outcome.status is AppleWalletCaptureStatus.ACCEPTED
    with database.transaction() as session:
        claim = session.scalar(select(Claim))
        assert claim is not None
        assert claim.financial_account_id == account.id


@pytest.mark.integration
def test_realtime_apple_pay_source_alias_creates_provisional_claim(
    database: Database,
    tmp_path: Path,
) -> None:
    account = _account(database)
    aliases = FinancialAccountAliases(database)
    aliases.add_apple_wallet_card(account_slug=account.slug, card_label="Synthetic Wallet Card")
    ingestion = _ingestion(database, tmp_path)
    body = _realtime_wallet_body(use_card_alias=True, extra={"source": "apple-pay"})

    outcome = ingestion.ingest(body, received_at=datetime.now(UTC), actor_id=None)

    assert outcome.status is AppleWalletCaptureStatus.ACCEPTED
    with database.transaction() as session:
        claim = session.scalar(select(Claim))
        extraction = session.scalar(select(Extraction))
        arrival = session.scalar(select(ArtifactArrival))
        assert claim is not None
        assert claim.claim_type == "real_time"
        assert claim.financial_account_id == account.id
        assert claim.authorized_amount == Decimal("-12.34")
        assert extraction is not None
        assert extraction.status == "accepted"
        assert extraction.validation_report["source"] == "apple_wallet"
        assert arrival is not None
        assert arrival.source_type == "apple_wallet_shortcut"
        assert arrival.source_metadata["source"] == "apple_wallet"
        assert session.scalar(select(func.count()).select_from(PendingReview)) == 0


@pytest.mark.integration
def test_realtime_apple_wallet_unmapped_instrument_creates_blocking_review(
    database: Database,
    tmp_path: Path,
) -> None:
    ingestion = _ingestion(database, tmp_path)

    outcome = ingestion.ingest(
        _realtime_wallet_body(instrument="Unmapped Synthetic Wallet Card"),
        received_at=datetime.now(UTC),
        actor_id=None,
    )

    assert outcome.status is AppleWalletCaptureStatus.REVIEW_REQUIRED
    with database.transaction() as session:
        extraction = session.scalar(select(Extraction))
        review = session.scalar(select(PendingReview))
        assert extraction is not None
        assert extraction.failure_code == "unmapped_card"
        assert review is not None
        assert review.condition_code == "apple_wallet_unmapped_card"
        assert review.context == {"integration": "apple_wallet"}
        assert session.scalar(select(func.count()).select_from(Claim)) == 0


@pytest.mark.integration
def test_realtime_paylah_routes_to_the_single_active_paylah_account(
    database: Database,
    tmp_path: Path,
) -> None:
    account = _paylah_account(database)
    ingestion = _ingestion(database, tmp_path)
    body = _realtime_paylah_body()

    accepted = ingestion.ingest(body, received_at=datetime.now(UTC), actor_id=None)
    replay = ingestion.ingest(body, received_at=datetime.now(UTC), actor_id=None)

    assert accepted.status is AppleWalletCaptureStatus.ACCEPTED
    assert accepted.duplicate is False
    assert replay.status is AppleWalletCaptureStatus.ACCEPTED
    assert replay.duplicate is True
    with database.transaction() as session:
        claim = session.scalar(select(Claim))
        extraction = session.scalar(select(Extraction))
        arrival = session.scalar(select(ArtifactArrival))
        assert claim is not None
        assert claim.claim_type == "real_time"
        assert claim.financial_account_id == account.id
        assert claim.authorized_amount == Decimal("-8.50")
        assert claim.authorized_currency == "SGD"
        assert claim.occurrence_at == datetime(2026, 3, 7, 13, 5, tzinfo=UTC)
        assert claim.raw_description == "Synthetic PayLah name"
        assert extraction is not None
        assert extraction.adapter_key == "paylah_shortcut"
        assert extraction.validation_report["source"] == "paylah"
        assert arrival is not None
        assert arrival.source_type == "paylah_shortcut"
        assert arrival.source_metadata == {
            "adapter_key": "paylah_shortcut",
            "source": "paylah",
            "schema_version": "realtime-1",
        }
        source_artifact = session.scalar(select(SourceArtifact))
        assert source_artifact is not None
        assert (
            ContentAddressedStore(tmp_path)
            .verified_path(source_artifact.sha256, source_artifact.size)
            .read_bytes()
            == body
        )
        assert session.scalar(select(func.count()).select_from(Claim)) == 1
        assert session.scalar(select(func.count()).select_from(Extraction)) == 1


@pytest.mark.integration
def test_realtime_paylah_rejects_extra_card_field(
    database: Database,
    tmp_path: Path,
) -> None:
    _paylah_account(database)
    ingestion = _ingestion(database, tmp_path)

    outcome = ingestion.ingest(
        _realtime_paylah_body(extra={"card": "Should not be present"}),
        received_at=datetime.now(UTC),
        actor_id=None,
    )

    assert outcome.status is AppleWalletCaptureStatus.REVIEW_REQUIRED
    with database.transaction() as session:
        extraction = session.scalar(select(Extraction))
        assert extraction is not None
        assert extraction.status == "failed"
        assert extraction.failure_code == "invalid_payload_shape"
        assert session.scalar(select(func.count()).select_from(Claim)) == 0
        review = session.scalar(select(PendingReview))
        assert review is not None
        assert review.severity == "attention"
        assert review.condition_code == "shortcut_payload_invalid"
        assert review.context == _payload_review_context(
            "invalid_payload_shape", integration="paylah"
        )


@pytest.mark.integration
def test_realtime_unknown_source_fails_closed_without_claim(
    database: Database,
    tmp_path: Path,
) -> None:
    ingestion = _ingestion(database, tmp_path)
    body = json.dumps(
        {
            "schema_version": "realtime-1",
            "source": "venmo",
            "name": "Synthetic name",
            "amount": "$12.34",
            "date": "7 Mar 2026 at 9:05 PM",
        },
        separators=(",", ":"),
    ).encode()

    outcome = ingestion.ingest(body, received_at=datetime.now(UTC), actor_id=None)

    assert outcome.status is AppleWalletCaptureStatus.REVIEW_REQUIRED
    with database.transaction() as session:
        extraction = session.scalar(select(Extraction))
        assert extraction is not None
        assert extraction.status == "failed"
        assert extraction.failure_code == "unsupported_source"
        assert session.scalar(select(func.count()).select_from(Claim)) == 0
        review = session.scalar(select(PendingReview))
        catalog = ImportCatalog(database).get(extraction.id)
        assert review is not None
        assert review.severity == "attention"
        assert review.condition_code == "shortcut_payload_invalid"
        assert review.context["failure_code"] == "unsupported_source"
        assert catalog.active_review_id == review.id


@pytest.mark.integration
def test_unknown_schema_version_fails_closed_without_claim(
    database: Database,
    tmp_path: Path,
) -> None:
    ingestion = _ingestion(database, tmp_path)
    body = json.dumps(
        {
            "schema_version": "realtime-2",
            "source": "apple_wallet",
            "name": "Synthetic name",
            "merchant": "Synthetic merchant",
            "instrument": "Synthetic Wallet Card",
            "amount": "$12.34",
            "date": "7 Mar 2026 at 9:05 PM",
        },
        separators=(",", ":"),
    ).encode()

    outcome = ingestion.ingest(body, received_at=datetime.now(UTC), actor_id=None)

    assert outcome.status is AppleWalletCaptureStatus.REVIEW_REQUIRED
    with database.transaction() as session:
        extraction = session.scalar(select(Extraction))
        assert extraction is not None
        assert extraction.failure_code == "unsupported_schema_version"
        assert session.scalar(select(func.count()).select_from(Claim)) == 0
        review = session.scalar(select(PendingReview))
        assert review is not None
        assert review.condition_code == "shortcut_payload_invalid"
        assert review.context["failure_code"] == "unsupported_schema_version"


@pytest.mark.integration
def test_realtime_paylah_fails_closed_when_paylah_account_is_missing_or_ambiguous(
    database: Database,
    tmp_path: Path,
) -> None:
    ingestion = _ingestion(database, tmp_path)
    missing = ingestion.ingest(
        _realtime_paylah_body(), received_at=datetime.now(UTC), actor_id=None
    )
    _paylah_account(database, slug="synthetic-paylah-one")
    _paylah_account(database, slug="synthetic-paylah-two")
    ambiguous = ingestion.ingest(
        json.dumps(
            {
                "schema_version": "realtime-1",
                "source": "paylah",
                "name": "Another PayLah name",
                "amount": "$3.00",
                "date": "8 Mar 2026 at 9:05 PM",
            },
            separators=(",", ":"),
        ).encode(),
        received_at=datetime.now(UTC),
        actor_id=None,
    )

    assert missing.status is AppleWalletCaptureStatus.REVIEW_REQUIRED
    assert ambiguous.status is AppleWalletCaptureStatus.REVIEW_REQUIRED
    with database.transaction() as session:
        extractions = session.scalars(select(Extraction)).all()
        reviews = session.scalars(select(PendingReview)).all()
        assert {extraction.failure_code for extraction in extractions} == {
            "missing_paylah_account",
            "ambiguous_paylah_account",
        }
        assert {review.condition_code for review in reviews} == {
            "paylah_account_missing",
            "paylah_account_ambiguous",
        }
        assert all(review.context == {"integration": "paylah"} for review in reviews)
        assert session.scalar(select(func.count()).select_from(Claim)) == 0


@pytest.mark.integration
def test_malformed_json_fails_closed_with_attention_review(
    database: Database,
    tmp_path: Path,
) -> None:
    ingestion = _ingestion(database, tmp_path)

    outcome = ingestion.ingest(b"{not-json", received_at=datetime.now(UTC), actor_id=None)

    assert outcome.status is AppleWalletCaptureStatus.REVIEW_REQUIRED
    with database.transaction() as session:
        extraction = session.scalar(select(Extraction))
        review = session.scalar(select(PendingReview))
        assert extraction is not None
        assert extraction.failure_code == "invalid_json"
        assert review is not None
        assert review.severity == "attention"
        assert review.condition_code == "shortcut_payload_invalid"
        assert review.context == _payload_review_context("invalid_json")
        assert session.scalar(select(func.count()).select_from(Claim)) == 0


@pytest.mark.integration
def test_reprocess_named_failed_apple_pay_extraction_creates_provisional_claim(
    database: Database,
    tmp_path: Path,
) -> None:
    account = _account(database)
    aliases = FinancialAccountAliases(database)
    aliases.add_apple_wallet_card(account_slug=account.slug, card_label="Synthetic Wallet Card")
    store = ContentAddressedStore(tmp_path)
    capture = ArtifactCapture(store, database)
    ingestion = AppleWalletIngestion(
        database, capture, aliases, timezone=ZoneInfo("Asia/Singapore")
    )
    body = _realtime_wallet_body(use_card_alias=True, extra={"source": "apple-pay"})
    artifact = capture.capture_bytes(
        body,
        ArtifactArrivalInput(
            source_type="apple_wallet_shortcut",
            media_type="application/json",
            received_at=datetime.now(UTC),
            metadata={
                "adapter_key": "apple_wallet_shortcut",
                "source": "apple-pay",
                "schema_version": "realtime-1",
            },
        ),
    )
    with database.transaction() as session:
        failed = Extraction(
            id=uuid7(),
            artifact_id=artifact.id,
            adapter_key="apple_wallet_shortcut",
            parser_version="1",
            status="failed",
            claim_count=0,
            failure_code="unsupported_source",
            validation_report={"failure": {"code": "unsupported_source"}},
        )
        session.add(failed)
        session.flush()
        failed_id = failed.id
    ingestion.ingest(
        json.dumps(
            {
                "schema_version": "realtime-1",
                "source": "venmo",
                "name": "Synthetic decoy",
                "amount": "$1.00",
                "date": "7 Mar 2026 at 9:05 PM",
            },
            separators=(",", ":"),
        ).encode(),
        received_at=datetime.now(UTC),
        actor_id=None,
    )

    with pytest.raises(ValueError, match="failed apple_wallet_shortcut"):
        ingestion.reprocess(extraction_ids=(failed_id, uuid7()))
    with database.transaction() as session:
        assert session.scalar(select(func.count()).select_from(Claim)) == 0

    processed = ingestion.reprocess(extraction_ids=(failed_id,))
    replay = ingestion.reprocess(artifact_ids=(artifact.id,))

    assert processed == 1
    assert replay == 1
    with database.transaction() as session:
        claim = session.scalar(select(Claim))
        accepted = session.scalars(select(Extraction).where(Extraction.status == "accepted")).all()
        assert claim is not None
        assert claim.financial_account_id == account.id
        assert claim.claim_type == "real_time"
        assert len(accepted) == 1
        assert accepted[0].parser_version == "2"
        assert accepted[0].validation_report["source"] == "apple_wallet"
        assert session.scalar(select(func.count()).select_from(Claim)) == 1
        assert session.scalar(select(func.count()).select_from(Extraction)) == 3


@pytest.mark.integration
def test_shortcut_payload_invalid_review_can_be_excluded(
    database: Database,
    tmp_path: Path,
) -> None:
    ingestion = _ingestion(database, tmp_path)
    ingestion.ingest(b"{not-json", received_at=datetime.now(UTC), actor_id=None)
    with database.transaction() as session:
        review = session.scalar(select(PendingReview))
        assert review is not None
        review_id = review.id
        version = review.version

    decided = ReviewActions(database).decide(
        ReviewDecision(
            review_id=review_id,
            expected_version=version,
            choice="exclude_source_artifact",
        )
    )

    assert decided.status.value == "resolved"
    with database.transaction() as session:
        stored = session.get(PendingReview, review_id)
        assert stored is not None
        assert stored.status == "resolved"
        assert session.scalar(select(func.count()).select_from(Claim)) == 0
