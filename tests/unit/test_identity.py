import pytest

from billzebub.config import Settings
from billzebub.identity import IdentityError, resolve_owner


def test_accepts_only_an_allowlisted_tailscale_identity() -> None:
    settings = Settings(
        trust_tailscale_headers=True,
        tailscale_allowed_logins=("owner@example.test",),
    )

    owner = resolve_owner(
        {
            "tailscale-user-login": "OWNER@example.test",
            "tailscale-user-name": "Owner",
        },
        client_host="172.20.0.1",
        settings=settings,
    )

    assert owner.login == "owner@example.test"
    assert owner.name == "Owner"


def test_rejects_untrusted_or_unallowlisted_tailscale_headers() -> None:
    headers = {"tailscale-user-login": "owner@example.test"}

    with pytest.raises(IdentityError):
        resolve_owner(headers, client_host="172.20.0.1", settings=Settings())

    with pytest.raises(IdentityError):
        resolve_owner(
            headers,
            client_host="172.20.0.1",
            settings=Settings(
                trust_tailscale_headers=True,
                tailscale_allowed_logins=("someone-else@example.test",),
            ),
        )


def test_development_identity_works_only_on_loopback() -> None:
    settings = Settings(development_identity="developer@example.test")

    assert resolve_owner({}, client_host="127.0.0.1", settings=settings).login == (
        "developer@example.test"
    )
    with pytest.raises(IdentityError):
        resolve_owner({}, client_host="192.0.2.10", settings=settings)
