"""Immutable content-addressed Source Artifact storage."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

_CHUNK_SIZE = 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ArtifactStoreError(Exception):
    """Base error for artifact capture."""


class ArtifactTooLargeError(ArtifactStoreError):
    """The source exceeded the configured capture limit."""


class ArtifactIntegrityError(ArtifactStoreError):
    """Existing content did not match its content-addressed path."""


@dataclass(frozen=True, slots=True)
class StoredContent:
    sha256: str
    size: int
    relative_path: Path
    absolute_path: Path
    duplicate: bool


class ContentAddressedStore:
    """Capture bytes atomically under a path derived only from their SHA-256."""

    def __init__(self, root: Path, *, max_bytes: int = 100 * 1024 * 1024) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._root = root.expanduser().resolve()
        self._max_bytes = max_bytes
        self._staging = self._root / ".staging"
        self._ensure_directory(self._root)
        self._ensure_directory(self._staging)

    def put_bytes(self, content: bytes, *, original_name: str | None = None) -> StoredContent:
        """Capture an in-memory artifact; its original name never enters the path."""
        del original_name
        return self.put_stream(BytesIO(content))

    def put_file(self, source: Path) -> StoredContent:
        """Capture a file without changing or removing the source."""
        with source.open("rb") as stream:
            return self.put_stream(stream)

    def put_stream(self, stream: BinaryIO) -> StoredContent:
        """Capture a binary stream, fsync it, and publish it without overwriting."""
        digest = hashlib.sha256()
        size = 0
        descriptor, temporary_name = tempfile.mkstemp(dir=self._staging, prefix="capture-")
        temporary_path = Path(temporary_name)
        os.chmod(temporary_path, 0o600)

        try:
            with os.fdopen(descriptor, "wb") as destination:
                while chunk := stream.read(_CHUNK_SIZE):
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise ArtifactTooLargeError(
                            f"artifact exceeds the {self._max_bytes}-byte capture limit"
                        )
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())

            sha256 = digest.hexdigest()
            relative_path = self._relative_path(sha256)
            final_path = self._root / relative_path
            self._ensure_directory(final_path.parent)

            duplicate = self._publish_or_verify(temporary_path, final_path, sha256, size)
            return StoredContent(
                sha256=sha256,
                size=size,
                relative_path=relative_path,
                absolute_path=final_path,
                duplicate=duplicate,
            )
        finally:
            temporary_path.unlink(missing_ok=True)

    def verified_path(self, sha256: str, size: int) -> Path:
        """Resolve content by address only after verifying its bytes and size."""
        if _SHA256_PATTERN.fullmatch(sha256) is None or size < 0:
            raise ArtifactIntegrityError("invalid content address")
        path = self._root / self._relative_path(sha256)
        self._verify(path, sha256, size)
        return path

    @staticmethod
    def _relative_path(sha256: str) -> Path:
        return Path("sha256") / sha256[:2] / sha256[2:4] / sha256

    def _publish_or_verify(
        self,
        temporary_path: Path,
        final_path: Path,
        expected_hash: str,
        expected_size: int,
    ) -> bool:
        try:
            os.link(temporary_path, final_path)
        except OSError as error:
            if error.errno != errno.EEXIST:
                raise
            self._verify(final_path, expected_hash, expected_size)
            return True

        self._fsync_directory(final_path.parent)
        return False

    @staticmethod
    def _verify(path: Path, expected_hash: str, expected_size: int) -> None:
        try:
            stat = path.stat()
        except OSError as error:
            raise ArtifactIntegrityError("stored artifact cannot be inspected") from error
        if not path.is_file() or stat.st_size != expected_size:
            raise ArtifactIntegrityError("stored artifact size does not match its address")

        digest = hashlib.sha256()
        try:
            with path.open("rb") as source:
                while chunk := source.read(_CHUNK_SIZE):
                    digest.update(chunk)
        except OSError as error:
            raise ArtifactIntegrityError("stored artifact cannot be read") from error
        if digest.hexdigest() != expected_hash:
            raise ArtifactIntegrityError("stored artifact content does not match its address")

    @staticmethod
    def _ensure_directory(path: Path) -> None:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
