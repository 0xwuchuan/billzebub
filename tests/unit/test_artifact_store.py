import os
from pathlib import Path

import pytest

from billzebub.artifacts import (
    ArtifactIntegrityError,
    ArtifactTooLargeError,
    ContentAddressedStore,
)


def test_stores_content_by_hash_without_exposing_original_name(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path, max_bytes=1024)

    stored = store.put_bytes(b"fictional statement", original_name="real-name.pdf")

    assert stored.relative_path.as_posix().startswith("sha256/")
    assert "real-name" not in stored.relative_path.as_posix()
    assert stored.absolute_path.read_bytes() == b"fictional statement"
    assert stored.size == len(b"fictional statement")
    assert stored.duplicate is False
    assert os.stat(stored.absolute_path).st_mode & 0o777 == 0o600


def test_duplicate_content_reuses_the_immutable_file(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path)

    first = store.put_bytes(b"same content")
    second = store.put_bytes(b"same content")

    assert second.sha256 == first.sha256
    assert second.relative_path == first.relative_path
    assert second.duplicate is True


def test_rejects_an_oversized_artifact_and_cleans_staging(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path, max_bytes=4)

    with pytest.raises(ArtifactTooLargeError):
        store.put_bytes(b"12345")

    assert not list((tmp_path / ".staging").iterdir())


def test_detects_tampering_at_an_existing_hash_path(tmp_path: Path) -> None:
    store = ContentAddressedStore(tmp_path)
    stored = store.put_bytes(b"original")
    stored.absolute_path.chmod(0o600)
    stored.absolute_path.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError):
        store.put_bytes(b"original")
