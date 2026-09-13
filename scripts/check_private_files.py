#!/usr/bin/env python3
"""Fail when Git knows about files that can contain private financial data."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import PurePosixPath

PRIVATE_EXTENSIONS = {
    ".backup",
    ".dump",
    ".eml",
    ".key",
    ".p12",
    ".pdf",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
PRIVATE_ROOTS = {
    "artifacts",
    "backups",
    "captures",
    "pgdata",
    "postgres",
    "secrets",
}


def private_reason(path_text: str) -> str | None:
    """Return why a repository-relative path is forbidden, if it is."""
    path = PurePosixPath(path_text)
    parts = path.parts

    if parts[:2] == ("fixtures", "private"):
        return "private fixture"
    if "secrets" in parts:
        return "secret directory"
    if parts and parts[0] in PRIVATE_ROOTS:
        return "private runtime directory"
    if len(parts) >= 3 and parts[0] == "prototypes" and "runtime" in parts[2:]:
        return "prototype runtime capture"
    if path.name == ".env" or (path.name.startswith(".env.") and path.name != ".env.example"):
        return "local environment file"
    if path.suffix.lower() in PRIVATE_EXTENSIONS:
        return f"private {path.suffix.lower()} file"
    return None


def find_private_files(paths: Iterable[str]) -> list[tuple[str, str]]:
    """Return forbidden paths and their reasons in stable order."""
    return sorted((path, reason) for path in paths if (reason := private_reason(path)) is not None)


def git_visible_files() -> list[str]:
    """List tracked and non-ignored untracked files from Git."""
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    return [path.decode() for path in result.stdout.split(b"\0") if path]


def main() -> int:
    violations = find_private_files(git_visible_files())
    if not violations:
        print("private-file check passed")
        return 0

    print("Files that may contain private financial data are visible to Git:")
    for path, reason in violations:
        print(f"  {path}: {reason}")
    print("Remove them from Git; do not add an allowlist exception.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
