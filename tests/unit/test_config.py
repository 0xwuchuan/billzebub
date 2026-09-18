from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from billzebub.config import Environment, Settings


def test_nas_configuration_requires_tailscale_proxy_and_owner() -> None:
    with pytest.raises(ValidationError, match="Tailscale headers"):
        Settings(environment=Environment.NAS, tailscale_allowed_logins=("owner@example.test",))

    with pytest.raises(ValidationError, match="allowlisted"):
        Settings(environment=Environment.NAS, trust_tailscale_headers=True)


def test_nas_configuration_forbids_development_identity() -> None:
    with pytest.raises(ValidationError, match="development identity"):
        Settings(
            environment=Environment.NAS,
            trust_tailscale_headers=True,
            tailscale_allowed_logins=("owner@example.test",),
            development_identity="developer@example.test",
        )


def test_nas_configuration_reads_database_url_only_from_private_file(tmp_path: Path) -> None:
    database_url_file = tmp_path / "database-url"
    database_url_file.write_text(
        "postgresql+psycopg://synthetic@postgres/synthetic\n", encoding="utf-8"
    )
    database_url_file.chmod(0o600)

    settings = Settings(
        environment=Environment.NAS,
        trust_tailscale_headers=True,
        tailscale_allowed_logins=("owner@example.test",),
        database_url_file=database_url_file,
    )

    assert settings.database_url_value == "postgresql+psycopg://synthetic@postgres/synthetic"


def test_settings_normalize_owner_logins_and_paths(tmp_path: Path) -> None:
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        statement_inbox_root=tmp_path / "inbox",
        statement_password_root=tmp_path / "passwords",
        tailscale_allowed_logins=(" OWNER@Example.Test ",),
    )

    assert settings.artifact_root == (tmp_path / "artifacts").resolve()
    assert settings.statement_inbox_root == (tmp_path / "inbox").resolve()
    assert settings.statement_password_root == (tmp_path / "passwords").resolve()
    assert settings.tailscale_allowed_logins == ("owner@example.test",)


def test_optional_jev_webhook_settings_treat_blanks_as_unset() -> None:
    settings = Settings(jev_webhook_url="  ", jev_webhook_secret="  ")  # type: ignore[arg-type]
    assert settings.jev_webhook_url is None
    assert settings.jev_webhook_secret is None
    assert settings.jev_webhook_timeout_seconds == 5.0

    configured = Settings(
        jev_webhook_url=" https://forge.example.test/webhook ",
        jev_webhook_secret=SecretStr("synthetic-jev-webhook-sender-key"),
    )
    assert configured.jev_webhook_url == "https://forge.example.test/webhook"
    assert configured.jev_webhook_secret is not None
    assert configured.jev_webhook_secret.get_secret_value() == "synthetic-jev-webhook-sender-key"
