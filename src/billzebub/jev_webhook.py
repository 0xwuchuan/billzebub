"""Fail-open HTTPS notify so forge can run host-side Jev.

The NAS worker never imports typesafe-sdk or runs Jev. After statement
Reconciliation creates Transactions, it POSTs a forge webhook. Failures are
logged and swallowed so import and accept never block.
"""

from __future__ import annotations

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import SecretStr

from billzebub.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0
_EVENT_BODY = {"event": "categorization_needed"}
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def notify_jev_webhook(
    *,
    url: str | None,
    secret: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """POST the forge webhook, or no-op when no URL is configured."""
    target = url.strip() if url is not None else ""
    if not target:
        return
    if not _https_or_loopback(target):
        logger.warning("jev webhook skipped: URL must use HTTPS outside loopback")
        return
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    token = secret.strip() if secret else ""
    if token:
        headers["Authorization"] = _authorization(token)
    request = Request(
        target,
        data=json.dumps(_EVENT_BODY, separators=(",", ":"), allow_nan=False).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response.read(4096)
    except HTTPError as error:
        logger.warning("jev webhook failed: HTTP %s", error.code)
    except TimeoutError:
        logger.warning("jev webhook failed: timeout")
    except URLError:
        logger.warning("jev webhook failed: request error")
    except OSError:
        logger.warning("jev webhook failed: request error")
    except Exception:
        logger.exception("jev webhook failed")


def notify_jev_webhook_from_settings(settings: Settings) -> None:
    secret = _secret_value(settings.jev_webhook_secret)
    notify_jev_webhook(
        url=settings.jev_webhook_url,
        secret=secret,
        timeout_seconds=settings.jev_webhook_timeout_seconds,
    )


def _secret_value(secret: SecretStr | None) -> str | None:
    if secret is None:
        return None
    value = secret.get_secret_value().strip()
    return value or None


def _authorization(secret: str) -> str:
    if secret.casefold().startswith("bearer "):
        return secret
    return f"Bearer {secret}"


def _https_or_loopback(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    loopback = parsed.hostname in _LOOPBACK_HOSTS
    return parsed.scheme == "https" or loopback
