from pathlib import Path

import pytest

from billzebub.config import Settings
from billzebub.entrypoints import cli
from billzebub.financial_accounts import (
    FinancialAccountBootstrapCommand,
    FinancialAccountBootstrapPlan,
)
from billzebub.persistence.models import FinancialAccountKind


class FakeDatabase:
    def __init__(self, _settings: Settings) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeAliases:
    account_slug: str | None = None
    card_label: str | None = None

    def __init__(self, _database: FakeDatabase) -> None:
        pass

    def add_apple_wallet_card(self, *, account_slug: str, card_label: str) -> None:
        type(self).account_slug = account_slug
        type(self).card_label = card_label


class FakeBootstrap:
    command: FinancialAccountBootstrapCommand | None = None
    dry_run: bool | None = None

    def __init__(self, _database: FakeDatabase, *, inbox_root: Path, password_root: Path) -> None:
        self.inbox_root = inbox_root
        self.password_root = password_root

    def bootstrap(
        self,
        command: FinancialAccountBootstrapCommand,
        *,
        dry_run: bool = False,
    ) -> FinancialAccountBootstrapPlan:
        type(self).command = command
        type(self).dry_run = dry_run
        return FinancialAccountBootstrapPlan(
            slug=command.slug,
            institution=command.institution,
            kind=command.kind,
            default_currency=command.default_currency,
            statement_adapter_key=command.statement_adapter_key,
            password_configured=False,
        )


def test_account_bootstrap_cli_reads_private_identifier_and_prints_no_sensitive_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identifier_file = tmp_path / "private-identifier"
    identifier_file.write_text("synthetic-private-account-identifier\n", encoding="utf-8")
    identifier_file.chmod(0o600)
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        statement_inbox_root=tmp_path / "inbox",
        statement_password_root=tmp_path / "passwords",
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "Database", FakeDatabase)
    monkeypatch.setattr(cli, "FinancialAccountBootstrap", FakeBootstrap)

    cli.main(
        [
            "account",
            "bootstrap",
            "--slug",
            "synthetic-primary-card",
            "--display-name",
            "Synthetic Primary Card",
            "--institution",
            "synthetic",
            "--currency",
            "SGD",
            "--statement-adapter",
            "synthetic-card",
            "--statement-account-identifier-file",
            str(identifier_file),
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    assert FakeBootstrap.dry_run is True
    assert FakeBootstrap.command is not None
    assert FakeBootstrap.command.kind is FinancialAccountKind.CREDIT_CARD
    assert (
        FakeBootstrap.command.statement_account_identifier == "synthetic-private-account-identifier"
    )
    assert (
        output == "Financial Account dry run passed; no database or filesystem changes were made.\n"
    )
    assert "synthetic-private-account-identifier" not in output
    assert identifier_file.name not in output


def test_apple_wallet_alias_cli_reads_private_label_and_never_prints_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    label_file = tmp_path / "private-card-label"
    label_file.write_text("Synthetic Wallet Card Label\n", encoding="utf-8")
    label_file.chmod(0o600)
    monkeypatch.setattr(cli, "Settings", lambda: Settings(artifact_root=tmp_path / "artifacts"))
    monkeypatch.setattr(cli, "Database", FakeDatabase)
    monkeypatch.setattr(cli, "FinancialAccountAliases", FakeAliases)

    cli.main(
        [
            "account",
            "apple-wallet-alias",
            "--slug",
            "synthetic-primary-card",
            "--card-label-file",
            str(label_file),
        ]
    )

    output = capsys.readouterr().out
    assert FakeAliases.account_slug == "synthetic-primary-card"
    assert FakeAliases.card_label == "Synthetic Wallet Card Label"
    assert output == "Apple Wallet card alias configured.\n"
    assert "Synthetic Wallet Card Label" not in output
    assert label_file.name not in output


def test_account_bootstrap_cli_rejects_broadly_readable_identifier_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    identifier_file = tmp_path / "private-identifier"
    identifier_file.write_text("synthetic-private-account-identifier", encoding="utf-8")
    identifier_file.chmod(0o644)
    settings = Settings(
        artifact_root=tmp_path / "artifacts",
        statement_inbox_root=tmp_path / "inbox",
        statement_password_root=tmp_path / "passwords",
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli, "Database", FakeDatabase)

    with pytest.raises(SystemExit, match="setup failed"):
        cli.main(
            [
                "account",
                "bootstrap",
                "--slug",
                "synthetic-primary-card",
                "--display-name",
                "Synthetic Primary Card",
                "--institution",
                "synthetic",
                "--currency",
                "SGD",
                "--statement-adapter",
                "synthetic-card",
                "--statement-account-identifier-file",
                str(identifier_file),
            ]
        )
