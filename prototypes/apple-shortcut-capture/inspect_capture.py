#!/usr/bin/env python3
"""PROTOTYPE: inspect the newest captured request on the local machine."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAPTURES = ROOT / "runtime" / "captures"


def main() -> None:
    metadata_files = sorted(CAPTURES.glob("*.json"))
    if not metadata_files:
        raise SystemExit("No captures yet.")

    metadata_path = metadata_files[-1]
    body_path = metadata_path.with_suffix(".body")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    body = body_path.read_bytes()

    print(json.dumps(metadata, indent=2, sort_keys=True))
    print("\n--- body ---")
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        print(f"Binary body ({len(body)} bytes): {body[:64].hex()}")
        return

    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError:
        print(decoded)
    else:
        print(json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
