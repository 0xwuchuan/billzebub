#!/usr/bin/env python3
"""PROTOTYPE: capture raw Apple Shortcut HTTP requests locally."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
CAPTURES = RUNTIME / "captures"
TOKEN_FILE = RUNTIME / "token"
MAX_BODY_BYTES = 256 * 1024
CAPTURE_DIRECTORY_MODE = 0o750
CAPTURE_FILE_MODE = 0o640


def load_or_create_token() -> str:
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()

    token = secrets.token_urlsafe(32)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(token + "\n")
    return token


TOKEN = load_or_create_token()


class CaptureHandler(BaseHTTPRequestHandler):
    server_version = "BillzebubAppleCapture/0"

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        print(
            "[DEBUG-iphone-health] request "
            f"from={self.client_address[0]} "
            f"user_agent={self.headers.get('User-Agent', '<none>')!r}",
            flush=True,
        )
        self._send_json(200, {"status": "ok"})

    def do_POST(self) -> None:
        print(
            "[DEBUG-shortcut-post] request "
            f"from={self.client_address[0]} "
            f"path={self.path!r} "
            f"content_type={self.headers.get('Content-Type', '<none>')!r} "
            f"authorization_present={bool(self.headers.get('Authorization'))}",
            flush=True,
        )
        if self.path != "/capture":
            self.send_error(404)
            return

        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {TOKEN}"
        if not hmac.compare_digest(supplied, expected):
            self._send_json(401, {"error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "invalid_content_length"})
            return

        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "body_too_large"})
            return

        body = self.rfile.read(length)
        capture_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}-{uuid4().hex}"
        digest = hashlib.sha256(body).hexdigest()
        metadata = {
            "prototype": True,
            "capture_id": capture_id,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "remote_address": self.client_address[0],
            "method": "POST",
            "path": self.path,
            "content_type": self.headers.get("Content-Type"),
            "content_length": len(body),
            "sha256": digest,
            "headers": {
                key: value
                for key, value in self.headers.items()
                if key.lower() not in {"authorization", "cookie"}
            },
        }

        CAPTURES.mkdir(mode=CAPTURE_DIRECTORY_MODE, parents=True, exist_ok=True)
        self._atomic_write(CAPTURES / f"{capture_id}.body", body)
        self._atomic_write(
            CAPTURES / f"{capture_id}.json",
            (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode(),
        )

        print(
            f"captured {capture_id}: {len(body)} bytes, "
            f"{metadata['content_type'] or 'unknown content type'}, sha256={digest}",
            flush=True,
        )
        self._send_json(
            201,
            {
                "capture_id": capture_id,
                "bytes": len(body),
                "sha256": digest,
            },
        )

    def log_message(self, format: str, *args: object) -> None:
        # Avoid placing request details in a second log. Successful captures are
        # summarized after authorization, and errors remain visible to clients.
        return

    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    @staticmethod
    def _atomic_write(destination: Path, content: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
        )
        try:
            os.fchmod(descriptor, CAPTURE_FILE_MODE)
            with os.fdopen(descriptor, "wb") as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, destination)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise


def main() -> None:
    host = os.environ.get("CAPTURE_HOST", "127.0.0.1")
    port = int(os.environ.get("CAPTURE_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), CaptureHandler)
    print("PROTOTYPE — captured request bodies remain local and must not be committed.")
    print(f"Listening on http://{host}:{port}")
    print("Authorization: bearer token loaded")
    print(f"Capture directory: {CAPTURES}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"capture server failed: {error}", file=sys.stderr)
        raise
