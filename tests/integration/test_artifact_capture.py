from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from billzebub.artifact_capture import ArtifactArrivalInput, ArtifactCapture
from billzebub.artifacts import ContentAddressedStore
from billzebub.persistence.database import Database
from billzebub.persistence.models import ArtifactArrival, SourceArtifact


@pytest.mark.integration
def test_duplicate_arrivals_share_one_immutable_source_artifact(
    database: Database,
    tmp_path: Path,
) -> None:
    capture = ArtifactCapture(ContentAddressedStore(tmp_path), database)
    arrival = ArtifactArrivalInput(
        source_type="synthetic_test",
        media_type="application/pdf",
        original_name="fictional.pdf",
        received_at=datetime.now(UTC),
    )

    first = capture.capture_bytes(b"fictional statement", arrival)
    second = capture.capture_bytes(b"fictional statement", arrival)

    assert first.id == second.id
    assert first.arrival_id != second.arrival_id
    assert first.duplicate_content is False
    assert second.duplicate_content is True
    with database.transaction() as session:
        artifact_count = session.scalar(select(func.count()).select_from(SourceArtifact))
        arrival_count = session.scalar(select(func.count()).select_from(ArtifactArrival))
    assert artifact_count == 1
    assert arrival_count == 2
