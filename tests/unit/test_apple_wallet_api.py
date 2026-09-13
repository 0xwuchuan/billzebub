from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from billzebub.api import create_app
from billzebub.apple_wallet import AppleWalletCaptureOutcome, AppleWalletCaptureStatus
from billzebub.config import Settings
from billzebub.tokens import TokenPrincipal, TokenScope


class FakeDatabase:
    def ping(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeTokenManager:
    def __init__(self) -> None:
        self.scopes: frozenset[TokenScope] | None = None

    def authenticate(
        self,
        plaintext: str,
        *,
        required_scopes: frozenset[TokenScope] = frozenset(),
    ) -> TokenPrincipal:
        assert plaintext == "synthetic-token"
        self.scopes = required_scopes
        return TokenPrincipal(token_id=uuid4(), actor_id=uuid4(), scopes=frozenset(required_scopes))


class FakeAppleWalletIngestion:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.body: bytes | None = None
        self.received_at: datetime | None = None
        self.actor_id: UUID | None = None

    def ingest(
        self,
        body: bytes,
        *,
        received_at: datetime,
        actor_id: UUID | None,
    ) -> AppleWalletCaptureOutcome:
        self.body = body
        self.received_at = received_at
        self.actor_id = actor_id
        return AppleWalletCaptureOutcome(AppleWalletCaptureStatus.ACCEPTED, self.duplicate)


def test_apple_wallet_endpoint_requires_scoped_bearer_and_preserves_raw_body(
    tmp_path: Path,
) -> None:
    tokens = FakeTokenManager()
    ingestion = FakeAppleWalletIngestion()
    app = create_app(
        Settings(artifact_root=tmp_path),
        FakeDatabase(),
        token_manager=tokens,
        apple_wallet_ingestion=ingestion,
    )
    body = b'{"schema_version":"probe-2"}'

    with TestClient(app) as client:
        blocked = client.post(
            "/api/v1/ingestions/apple-wallet",
            content=body,
            headers={"content-type": "application/json"},
        )
        accepted = client.post(
            "/api/v1/ingestions/apple-wallet",
            content=body,
            headers={
                "authorization": "Bearer synthetic-token",
                "content-type": "application/json; charset=utf-8",
            },
        )

    assert blocked.status_code == 401
    assert accepted.status_code == 201
    assert accepted.json() == {"status": "accepted", "duplicate": False}
    assert tokens.scopes == frozenset({TokenScope.SHORTCUT_CLAIMS_CREATE})
    assert ingestion.body == body
    assert ingestion.received_at is not None
    assert ingestion.received_at.tzinfo is UTC
    assert ingestion.actor_id is not None


def test_apple_wallet_endpoint_rejects_non_json_before_capture(tmp_path: Path) -> None:
    app = create_app(
        Settings(artifact_root=tmp_path),
        FakeDatabase(),
        token_manager=FakeTokenManager(),
        apple_wallet_ingestion=FakeAppleWalletIngestion(),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/ingestions/apple-wallet",
            content=b"not json",
            headers={"authorization": "Bearer synthetic-token", "content-type": "text/plain"},
        )

    assert response.status_code == 415
    assert response.json()["detail"] == "apple_wallet_content_type_invalid"
