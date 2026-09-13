"""Resolve the authenticated owner to one durable audit actor."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from uuid6 import uuid7

from billzebub.identity import OwnerIdentity
from billzebub.persistence.models import AuditActor, AuditActorKind

if TYPE_CHECKING:
    from billzebub.persistence.database import Database


class OwnerActors:
    """Keep owner-authored financial changes attributable without browser sessions."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def resolve(self, identity: OwnerIdentity) -> UUID:
        external_key = f"tailscale:{identity.login.casefold()}"
        with self._database.transaction() as session:
            inserted = session.execute(
                insert(AuditActor)
                .values(
                    id=uuid7(),
                    kind=AuditActorKind.OWNER.value,
                    label=identity.name,
                    external_key=external_key,
                )
                .on_conflict_do_nothing(
                    index_elements=(AuditActor.kind, AuditActor.external_key),
                )
                .returning(AuditActor.id)
            ).scalar_one_or_none()
            if inserted is not None:
                return inserted
            actor_id = session.scalar(
                select(AuditActor.id).where(
                    AuditActor.kind == AuditActorKind.OWNER.value,
                    AuditActor.external_key == external_key,
                )
            )
            if actor_id is None:
                raise RuntimeError("owner audit actor disappeared")
            return actor_id
