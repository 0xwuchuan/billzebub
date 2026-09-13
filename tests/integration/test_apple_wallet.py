from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from uuid6 import uuid7

from billzebub.apple_wallet import AppleWalletCaptureStatus, AppleWalletIngestion
from billzebub.artifact_capture import ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.financial_account_aliases import FinancialAccountAliases
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
