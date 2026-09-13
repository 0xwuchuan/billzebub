"""Replay-safe mutation outcomes backed by durable idempotency records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from uuid6 import uuid7

from billzebub.persistence.models import IdempotencyRecord

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class IdempotencyError(ValueError):
    """An idempotency key is malformed or was reused for a different request."""


@dataclass(frozen=True, slots=True)
class IdempotentResult:
    status_code: int
    body: dict[str, Any]
    replayed: bool


class IdempotencyBook:
    """Execute one mutation once and retain its safe response for retries."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def execute(
        self,
        *,
        principal: str,
        operation: str,
        key: str,
        request: dict[str, Any],
        action: Callable[[Session], tuple[int, dict[str, Any]]],
    ) -> IdempotentResult:
        self._validate(principal, operation, key)
        digest = self._digest(request)
        with self._database.transaction() as session:
            inserted = session.execute(
                insert(IdempotencyRecord)
                .values(
                    id=uuid7(),
                    principal=principal,
                    operation=operation,
                    key=key,
                    request_digest=digest,
                )
                .on_conflict_do_nothing(
                    index_elements=(
                        IdempotencyRecord.principal,
                        IdempotencyRecord.operation,
                        IdempotencyRecord.key,
                    )
                )
                .returning(IdempotencyRecord.id)
            ).scalar_one_or_none()
            if inserted is None:
                existing = session.scalar(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.principal == principal,
                        IdempotencyRecord.operation == operation,
                        IdempotencyRecord.key == key,
                    )
                )
                if existing is None:
                    raise IdempotencyError("idempotency record disappeared")
                if existing.request_digest != digest:
                    raise IdempotencyError("idempotency key was reused with a different request")
                if existing.response_status is None or existing.response_body is None:
                    raise IdempotencyError("idempotency response is incomplete")
                return IdempotentResult(
                    status_code=existing.response_status,
                    body=dict(existing.response_body),
                    replayed=True,
                )

            status_code, body = action(session)
            record = session.get(IdempotencyRecord, inserted)
            if record is None:
                raise IdempotencyError("idempotency record disappeared")
            record.response_status = status_code
            record.response_body = dict(body)
            session.flush()
            return IdempotentResult(status_code=status_code, body=body, replayed=False)

    @staticmethod
    def _digest(request: dict[str, Any]) -> bytes:
        try:
            payload = json.dumps(
                request,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode()
        except (TypeError, ValueError) as error:
            raise IdempotencyError("request is not canonical JSON") from error
        return hashlib.sha256(payload).digest()

    @staticmethod
    def _validate(principal: str, operation: str, key: str) -> None:
        if not principal.strip() or not operation.strip() or not key.strip():
            raise IdempotencyError("principal, operation, and idempotency key are required")
        if len(principal) > 160 or len(operation) > 120 or len(key) > 255:
            raise IdempotencyError("idempotency identifiers are too long")
