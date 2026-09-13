"""Owner identity derived from the trusted Tailscale Serve path."""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass

from billzebub.config import Settings


class IdentityError(Exception):
    """No configured owner identity could be established."""


@dataclass(frozen=True, slots=True)
class OwnerIdentity:
    login: str
    name: str


def resolve_owner(
    headers: Mapping[str, str],
    *,
    client_host: str,
    settings: Settings,
) -> OwnerIdentity:
    """Resolve the sole owner and fail closed outside explicit development mode."""
    normalized_headers = {key.casefold(): value for key, value in headers.items()}

    if settings.trust_tailscale_headers:
        login = normalized_headers.get("tailscale-user-login", "").strip().casefold()
        if not login or login not in settings.tailscale_allowed_logins:
            raise IdentityError("request does not belong to the configured owner")
        name = normalized_headers.get("tailscale-user-name", "").strip() or login
        return OwnerIdentity(login=login, name=name)

    if settings.development_identity is None or not _is_loopback(client_host):
        raise IdentityError("request did not arrive through a trusted identity path")

    login = settings.development_identity.strip().casefold()
    if not login:
        raise IdentityError("development identity is empty")
    return OwnerIdentity(login=login, name=login)


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
