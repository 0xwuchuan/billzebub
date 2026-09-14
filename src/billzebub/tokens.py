"""Scoped bearer tokens whose plaintext is revealed exactly once."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from uuid6 import uuid7

from billzebub.persistence.database import Database
from billzebub.persistence.models import AuditActor, AuditActorKind, IntegrationToken


class TokenScope(StrEnum):
    SHORTCUT_CLAIMS_CREATE = "shortcut:claims:create"
    AGENT_READ = "agent:read"
    AGENT_CATEGORIZE = "agent:categorize"
    AGENT_PROPOSE = "agent:propose"


class TokenAuthenticationError(Exception):
    """Token authentication failed without revealing which check failed."""


class TokenRotationError(Exception):
    """An inactive or unknown token cannot be rotated."""


@dataclass(frozen=True, slots=True)
class IssuedToken:
    id: UUID
    name: str
    plaintext: str
    prefix: str
    scopes: frozenset[TokenScope]


@dataclass(frozen=True, slots=True)
class TokenPrincipal:
    token_id: UUID
    actor_id: UUID
    scopes: frozenset[TokenScope]


@dataclass(frozen=True, slots=True)
class TokenRecord:
    id: UUID
    name: str
    prefix: str
    scopes: tuple[str, ...]
    created_at: datetime
    last_used_at: datetime | None


class TokenManager:
    """Issue, authenticate, and revoke high-entropy integration tokens."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def issue(
        self,
        *,
        name: str,
        actor_kind: AuditActorKind,
        scopes: frozenset[TokenScope],
    ) -> IssuedToken:
        if not name.strip():
            raise ValueError("token name is required")
        if not scopes:
            raise ValueError("at least one token scope is required")

        token_id, prefix, plaintext, digest = self._generate_token()
        actor_id = uuid7()

        with self._database.transaction() as session:
            session.add(
                AuditActor(
                    id=actor_id,
                    kind=actor_kind,
                    label=name,
                    external_key=f"token:{token_id}",
                )
            )
            session.add(
                IntegrationToken(
                    id=token_id,
                    actor_id=actor_id,
                    name=name,
                    token_prefix=prefix,
                    token_digest=digest,
                    scopes=sorted(scope.value for scope in scopes),
                )
            )

        return IssuedToken(
            id=token_id, name=name, plaintext=plaintext, prefix=prefix, scopes=scopes
        )

    def list_active(self) -> tuple[TokenRecord, ...]:
        with self._database.transaction() as session:
            tokens = session.scalars(
                select(IntegrationToken)
                .where(IntegrationToken.revoked_at.is_(None))
                .order_by(IntegrationToken.created_at, IntegrationToken.id)
            ).all()
            return tuple(self._record(token) for token in tokens)

    def rotate(self, token_id: UUID) -> IssuedToken:
        """Issue a replacement and revoke the prior token in one transaction."""
        replacement_id, prefix, plaintext, digest = self._generate_token()
        with self._database.transaction() as session:
            prior = session.execute(
                select(IntegrationToken)
                .where(
                    IntegrationToken.id == token_id,
                    IntegrationToken.revoked_at.is_(None),
                )
                .with_for_update()
            ).scalar_one_or_none()
            if prior is None:
                raise TokenRotationError("token was not active or did not exist")
            try:
                scopes = frozenset(TokenScope(scope) for scope in prior.scopes)
            except ValueError as error:
                raise TokenRotationError("token has invalid stored scopes") from error

            prior.revoked_at = datetime.now(UTC)
            session.add(
                IntegrationToken(
                    id=replacement_id,
                    actor_id=prior.actor_id,
                    name=prior.name,
                    token_prefix=prefix,
                    token_digest=digest,
                    scopes=sorted(scope.value for scope in scopes),
                )
            )
            name = prior.name

        return IssuedToken(
            id=replacement_id,
            name=name,
            plaintext=plaintext,
            prefix=prefix,
            scopes=scopes,
        )

    def authenticate(
        self,
        plaintext: str,
        *,
        required_scopes: frozenset[TokenScope] = frozenset(),
    ) -> TokenPrincipal:
        prefix = self._parse_prefix(plaintext)
        digest = self._digest(plaintext)

        with self._database.transaction() as session:
            token = session.execute(
                select(IntegrationToken).where(
                    IntegrationToken.token_prefix == prefix,
                    IntegrationToken.revoked_at.is_(None),
                )
            ).scalar_one_or_none()
            if token is None or not hmac.compare_digest(token.token_digest, digest):
                raise TokenAuthenticationError("invalid bearer token")

            try:
                scopes = frozenset(TokenScope(scope) for scope in token.scopes)
            except ValueError as error:
                raise TokenAuthenticationError("invalid bearer token") from error
            if not required_scopes.issubset(scopes):
                raise TokenAuthenticationError("token lacks the required scope")

            now = datetime.now(UTC)
            session.execute(
                update(IntegrationToken)
                .where(IntegrationToken.id == token.id)
                .values(last_used_at=now)
            )
            return TokenPrincipal(token_id=token.id, actor_id=token.actor_id, scopes=scopes)

    def revoke(self, token_id: UUID) -> bool:
        with self._database.transaction() as session:
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(IntegrationToken)
                    .where(
                        IntegrationToken.id == token_id,
                        IntegrationToken.revoked_at.is_(None),
                    )
                    .values(revoked_at=datetime.now(UTC))
                ),
            )
            return result.rowcount == 1

    @staticmethod
    def _record(token: IntegrationToken) -> TokenRecord:
        return TokenRecord(
            id=token.id,
            name=token.name,
            prefix=token.token_prefix,
            scopes=tuple(token.scopes),
            created_at=token.created_at,
            last_used_at=token.last_used_at,
        )

    @classmethod
    def _generate_token(cls) -> tuple[UUID, str, str, bytes]:
        token_id = uuid7()
        prefix = secrets.token_hex(6)
        secret = secrets.token_urlsafe(32)
        plaintext = f"bzb_v1_{prefix}_{secret}"
        return token_id, prefix, plaintext, cls._digest(plaintext)

    @staticmethod
    def _digest(plaintext: str) -> bytes:
        return hashlib.sha256(plaintext.encode()).digest()

    @staticmethod
    def _parse_prefix(plaintext: str) -> str:
        parts = plaintext.split("_", 3)
        if len(parts) != 4 or parts[0:2] != ["bzb", "v1"] or len(parts[2]) != 12:
            raise TokenAuthenticationError("invalid bearer token")
        return parts[2]
