from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from billzebub.apple_wallet import AppleWalletCaptureOutcome, AppleWalletCaptureStatus
from billzebub.apple_wallet_probe import AppleWalletProbeError, import_probe_captures


class FakeIngestion:
    def __init__(self) -> None:
        self.captures: list[tuple[bytes, datetime, UUID | None]] = []

    def ingest(
        self,
        body: bytes,
        *,
        received_at: datetime,
        actor_id: UUID | None,
    ) -> AppleWalletCaptureOutcome:
        self.captures.append((body, received_at, actor_id))
        return AppleWalletCaptureOutcome(AppleWalletCaptureStatus.ACCEPTED, duplicate=False)


def test_probe_import_preserves_each_body_and_original_received_time(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    root.mkdir()
    (root / "first.json").write_text(
        '{"received_at":"2026-03-07T13:05:00+00:00"}', encoding="utf-8"
    )
    (root / "first.body").write_bytes(b'{"schema_version":"probe-2"}')
    (root / "second.json").write_text('{"received_at":"2026-03-08T13:05:00Z"}', encoding="utf-8")
    (root / "second.body").write_bytes(b'{"schema_version":"probe-2","amount":"$1.00"}')
    ingestion = FakeIngestion()

    imported = import_probe_captures(root, ingestion)

    assert imported == 2
    assert [body for body, _received_at, _actor in ingestion.captures] == [
        b'{"schema_version":"probe-2"}',
        b'{"schema_version":"probe-2","amount":"$1.00"}',
    ]
    assert ingestion.captures[0][1] == datetime(2026, 3, 7, 13, 5, tzinfo=UTC)
    assert all(actor is None for _body, _received_at, actor in ingestion.captures)


def test_probe_import_refuses_unpaired_private_files(tmp_path: Path) -> None:
    root = tmp_path / "captures"
    root.mkdir()
    (root / "unpaired.body").write_bytes(b"private synthetic payload")

    with pytest.raises(AppleWalletProbeError, match="pairing"):
        import_probe_captures(root, FakeIngestion())
