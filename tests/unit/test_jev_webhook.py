from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError

import pytest
from pydantic import SecretStr

from billzebub.config import Settings
from billzebub.jev_webhook import notify_jev_webhook, notify_jev_webhook_from_settings

WEBHOOK_URL = "https://forge.example.test/automations/webhook/synthetic"
WEBHOOK_SECRET = "synthetic-jev-webhook-secret"


class FakeResponse:
    def __init__(self, body: bytes = b"{}") -> None:
        self._body = body
        self.closed = False

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        self.closed = True


def test_missing_url_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_open(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("urlopen must not be called")

    monkeypatch.setattr("billzebub.jev_webhook.urlopen", fail_open)
    notify_jev_webhook(url=None)
    notify_jev_webhook(url="  ")
    notify_jev_webhook_from_settings(Settings())


def test_successful_post_sends_bearer_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr("billzebub.jev_webhook.urlopen", fake_urlopen)
    notify_jev_webhook(url=WEBHOOK_URL, secret=WEBHOOK_SECRET, timeout_seconds=4.5)

    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == WEBHOOK_URL
    assert request.get_method() == "POST"
    assert timeout == 4.5
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["authorization"] == f"Bearer {WEBHOOK_SECRET}"
    assert headers["content-type"] == "application/json"
    assert json.loads(request.data.decode()) == {"event": "categorization_needed"}
    assert WEBHOOK_SECRET not in repr(request.full_url)


def test_bearer_prefix_is_not_doubled(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        del timeout
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr("billzebub.jev_webhook.urlopen", fake_urlopen)
    notify_jev_webhook(url=WEBHOOK_URL, secret=f"Bearer {WEBHOOK_SECRET}")
    headers = {key.lower(): value for key, value in requests[0].header_items()}
    assert headers["authorization"] == f"Bearer {WEBHOOK_SECRET}"


def test_settings_secret_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: float) -> FakeResponse:
        del timeout
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr("billzebub.jev_webhook.urlopen", fake_urlopen)
    notify_jev_webhook_from_settings(
        Settings(
            jev_webhook_url=WEBHOOK_URL,
            jev_webhook_secret=SecretStr(WEBHOOK_SECRET),
        )
    )
    headers = {key.lower(): value for key, value in requests[0].header_items()}
    assert headers["authorization"] == f"Bearer {WEBHOOK_SECRET}"


@pytest.mark.parametrize(
    ("error", "logged"),
    [
        (TimeoutError(), "timeout"),
        (HTTPError(WEBHOOK_URL, 503, "nope", hdrs=None, fp=None), "HTTP 503"),  # type: ignore[arg-type]
        (URLError("down"), "request error"),
    ],
)
def test_http_failures_fail_open(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
    logged: str,
) -> None:
    def fake_urlopen(request: Any, timeout: float) -> None:
        del request, timeout
        raise error

    monkeypatch.setattr("billzebub.jev_webhook.urlopen", fake_urlopen)
    with caplog.at_level(logging.WARNING, logger="billzebub.jev_webhook"):
        notify_jev_webhook(url=WEBHOOK_URL, secret=WEBHOOK_SECRET)
    assert logged in caplog.text
    assert WEBHOOK_SECRET not in caplog.text


def test_cleartext_non_loopback_url_is_skipped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail_open(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("urlopen must not be called")

    monkeypatch.setattr("billzebub.jev_webhook.urlopen", fail_open)
    with caplog.at_level(logging.WARNING, logger="billzebub.jev_webhook"):
        notify_jev_webhook(url="http://forge.example.test/webhook")
    assert "HTTPS" in caplog.text
