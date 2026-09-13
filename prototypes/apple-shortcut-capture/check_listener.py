#!/usr/bin/env python3
"""Inspect Apple Shortcut listener health and captured payloads from Hermes."""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

CAPTURE_DIRECTORY = Path(
    os.environ.get(
        "BILLZEBUB_CAPTURE_DIRECTORY",
        "/opt/billzebub-listener/captures",
    )
)
HEALTH_URL = os.environ.get(
    "BILLZEBUB_LISTENER_HEALTH_URL",
    "http://billzebub-apple-shortcut-probe:8765/health",
)
SINGAPORE_TIMEZONE = timezone(timedelta(hours=8), name="SGT")


def parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_health() -> dict[str, Any]:
    try:
        with urlopen(HEALTH_URL, timeout=3) as response:
            body = response.read()
            return {
                "ok": response.status == 200,
                "status": response.status,
                "body": json.loads(body),
            }
    except (OSError, URLError, ValueError, json.JSONDecodeError) as error:
        return {"ok": False, "error": f"{type(error).__name__}: {error}"}


def read_body(body: bytes) -> dict[str, Any]:
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "encoding": "base64",
            "value": base64.b64encode(body).decode("ascii"),
        }

    try:
        return {"encoding": "json", "value": json.loads(decoded)}
    except json.JSONDecodeError:
        return {"encoding": "utf-8", "value": decoded}


def read_capture(metadata_path: Path) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    received_at = parse_instant(metadata["received_at"])
    body_path = metadata_path.with_suffix(".body")
    body = body_path.read_bytes()
    return {
        "received_at_sgt": received_at.astimezone(SINGAPORE_TIMEZONE).isoformat(),
        "metadata": metadata,
        "body": read_body(body),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check listener health and print full captured payloads as JSON."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="number of newest captures to return; use 0 for all (default: 1)",
    )
    parser.add_argument(
        "--since",
        type=parse_instant,
        help="return captures strictly after this RFC 3339 instant",
    )
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    metadata_files = sorted(CAPTURE_DIRECTORY.glob("*.json"))
    selected: list[Path] = []
    for metadata_path in metadata_files:
        if args.since is not None:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if parse_instant(metadata["received_at"]) <= args.since:
                continue
        selected.append(metadata_path)

    if args.limit:
        selected = selected[-args.limit :]

    result = {
        "health": read_health(),
        "capture_count": len(metadata_files),
        "matched_capture_count": len(selected),
        "captures": [read_capture(path) for path in selected],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
