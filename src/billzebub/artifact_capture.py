"""Capture Source Artifacts and record every arrival idempotently by content."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from uuid6 import uuid7

from billzebub.artifacts import ContentAddressedStore, StoredContent
from billzebub.persistence.database import Database
from billzebub.persistence.models import ArtifactArrival, SourceArtifact


@dataclass(frozen=True, slots=True)
class ArtifactArrivalInput:
    source_type: str
    media_type: str
    received_at: datetime
    original_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_type.strip():
            raise ValueError("source_type is required")
        if not self.media_type.strip():
            raise ValueError("media_type is required")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at must include a timezone")


@dataclass(frozen=True, slots=True)
class SourceArtifactRef:
    id: UUID
    arrival_id: UUID
    sha256: str
    size: int
    duplicate_content: bool


class ArtifactCapture:
    """Own filesystem publication and PostgreSQL artifact/arrival records."""

    def __init__(self, store: ContentAddressedStore, database: Database) -> None:
        self._store = store
        self._database = database

    def capture_bytes(self, content: bytes, arrival: ArtifactArrivalInput) -> SourceArtifactRef:
        stored = self._store.put_bytes(content, original_name=arrival.original_name)
        return self._record(stored, arrival)

    def capture_file(self, source: Path, arrival: ArtifactArrivalInput) -> SourceArtifactRef:
        stored = self._store.put_file(source)
        return self._record(stored, arrival)

    def _record(self, stored: StoredContent, arrival: ArtifactArrivalInput) -> SourceArtifactRef:
        proposed_artifact_id = uuid7()
        arrival_id = uuid7()
        with self._database.transaction() as session:
            inserted_id = session.execute(
                insert(SourceArtifact)
                .values(
                    id=proposed_artifact_id,
                    sha256=stored.sha256,
                    size=stored.size,
                    media_type=arrival.media_type,
                    content_path=stored.relative_path.as_posix(),
                    captured_at=arrival.received_at,
                )
                .on_conflict_do_nothing(index_elements=[SourceArtifact.sha256])
                .returning(SourceArtifact.id)
            ).scalar_one_or_none()

            artifact_id = inserted_id
            if artifact_id is None:
                artifact_id = session.execute(
                    select(SourceArtifact.id).where(SourceArtifact.sha256 == stored.sha256)
                ).scalar_one()

            session.add(
                ArtifactArrival(
                    id=arrival_id,
                    artifact_id=artifact_id,
                    source_type=arrival.source_type,
                    original_name=arrival.original_name,
                    received_at=arrival.received_at,
                    source_metadata=arrival.metadata,
                )
            )

        return SourceArtifactRef(
            id=artifact_id,
            arrival_id=arrival_id,
            sha256=stored.sha256,
            size=stored.size,
            duplicate_content=inserted_id is None,
        )
