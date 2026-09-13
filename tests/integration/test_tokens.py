import pytest
from sqlalchemy import select

from billzebub.persistence.database import Database
from billzebub.persistence.models import AuditActorKind, IntegrationToken
from billzebub.tokens import (
    TokenAuthenticationError,
    TokenManager,
    TokenRotationError,
    TokenScope,
)


@pytest.mark.integration
def test_token_is_hashed_scoped_and_revocable(database: Database) -> None:
    manager = TokenManager(database)
    issued = manager.issue(
        name="Apple Shortcut",
        actor_kind=AuditActorKind.INTEGRATION,
        scopes=frozenset({TokenScope.SHORTCUT_CLAIMS_CREATE}),
    )

    assert issued.plaintext.startswith(f"bzb_v1_{issued.prefix}_")
    with database.transaction() as session:
        stored = session.scalar(select(IntegrationToken).where(IntegrationToken.id == issued.id))
        assert stored is not None
        assert issued.plaintext.encode() not in stored.token_digest
        assert stored.token_digest != issued.plaintext.encode()

    principal = manager.authenticate(
        issued.plaintext,
        required_scopes=frozenset({TokenScope.SHORTCUT_CLAIMS_CREATE}),
    )
    assert principal.token_id == issued.id

    with pytest.raises(TokenAuthenticationError, match="required scope"):
        manager.authenticate(
            issued.plaintext,
            required_scopes=frozenset({TokenScope.AGENT_READ}),
        )

    altered = issued.plaintext[:-1] + ("a" if issued.plaintext[-1] != "a" else "b")
    with pytest.raises(TokenAuthenticationError, match="invalid bearer token"):
        manager.authenticate(altered)

    rotated = manager.rotate(issued.id)
    assert rotated.id != issued.id
    with pytest.raises(TokenAuthenticationError, match="invalid bearer token"):
        manager.authenticate(issued.plaintext)
    assert manager.authenticate(rotated.plaintext).actor_id == principal.actor_id
    with pytest.raises(TokenRotationError, match="not active"):
        manager.rotate(issued.id)

    assert manager.revoke(rotated.id) is True
    assert manager.revoke(rotated.id) is False
    with pytest.raises(TokenAuthenticationError, match="invalid bearer token"):
        manager.authenticate(rotated.plaintext)
