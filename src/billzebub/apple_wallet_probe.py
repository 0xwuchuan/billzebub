"""One-time local import of retained Apple Wallet probe bodies."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from billzebub.apple_wallet import AppleWalletCaptureOutcome


class AppleWalletProbeError(ValueError):
    """The private probe directory cannot be imported safely."""


class AppleWalletCaptureRuntime(Protocol):
    def ingest(
        self,
        body: bytes,
        *,
        received_at: datetime,
        actor_id: UUID | None,
    ) -> AppleWalletCaptureOutcome: ...


@dataclass(frozen=True, slots=True)
class ProbeCapture:
    body: bytes
    received_at: datetime


def import_probe_captures(
    capture_root: Path,
    ingestion: AppleWalletCaptureRuntime,
) -> int:
    """Import each matching metadata/body pair without exposing private contents."""
    root = _private_directory(capture_root)
    metadata_paths = sorted(root.glob("*.json"))
    body_paths = sorted(root.glob("*.body"))
    if not metadata_paths or {path.stem for path in metadata_paths} != {
        path.stem for path in body_paths
    }:
        raise AppleWalletProbeError("probe capture pairing is invalid")

    imported = 0
    for metadata_path in metadata_paths:
        capture = _capture(metadata_path, metadata_path.with_suffix(".body"))
        ingestion.ingest(capture.body, received_at=capture.received_at, actor_id=None)
        imported += 1
    return imported


def _private_directory(path: Path) -> Path:
    expanded = path.expanduser().absolute()
    try:
        metadata = expanded.lstat()
    except OSError as error:
        raise AppleWalletProbeError("probe capture directory is unavailable") from error
    if not stat.S_ISDIR(metadata.st_mode) or expanded.is_symlink():
        raise AppleWalletProbeError("probe capture directory is unsafe")
    return expanded


def _capture(metadata_path: Path, body_path: Path) -> ProbeCapture:
    for path in (metadata_path, body_path):
        try:
            metadata = path.lstat()
        except OSError as error:
            raise AppleWalletProbeError("probe capture file is unavailable") from error
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise AppleWalletProbeError("probe capture file is unsafe")
    try:
        metadata = json.loads(metadata_path.read_bytes())
        received_text = metadata["received_at"]
        if not isinstance(received_text, str):
            raise ValueError
        received_at = datetime.fromisoformat(received_text.replace("Z", "+00:00"))
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise AppleWalletProbeError("probe capture metadata is invalid") from error
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise AppleWalletProbeError("probe capture metadata is invalid")
    try:
        body = body_path.read_bytes()
    except OSError as error:
        raise AppleWalletProbeError("probe capture file is unavailable") from error
    return ProbeCapture(body=body, received_at=received_at)
