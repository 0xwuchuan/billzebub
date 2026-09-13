from pathlib import Path

import pytest
from sqlalchemy import select

from billzebub.financial_accounts import (
    FinancialAccountBootstrap,
    FinancialAccountBootstrapCommand,
    FinancialAccountSetupError,
)
from billzebub.persistence.database import Database
from billzebub.persistence.models import FinancialAccount, FinancialAccountKind


@pytest.mark.integration
def test_financial_account_bootstrap_dry_run_then_creates_isolated_inbox(
    database: Database,
    tmp_path: Path,
) -> None:
    inbox_root = tmp_path / "inbox"
    bootstrap = FinancialAccountBootstrap(
        database,
        inbox_root=inbox_root,
        password_root=tmp_path / "passwords",
        adapters={"synthetic-card": "synthetic"},
    )
    command = FinancialAccountBootstrapCommand(
        slug="synthetic-primary-card",
        display_name="Synthetic Primary Card",
        institution="synthetic",
        kind=FinancialAccountKind.CREDIT_CARD,
        default_currency="sgd",
        statement_adapter_key="synthetic-card",
        statement_account_identifier="synthetic-account-scope",
    )

    plan = bootstrap.bootstrap(command, dry_run=True)

    assert plan.slug == "synthetic-primary-card"
    assert plan.default_currency == "SGD"
    assert not inbox_root.exists()
    with database.transaction() as session:
        assert session.scalar(select(FinancialAccount.id)) is None

    record = bootstrap.bootstrap(command)

    assert record.slug == "synthetic-primary-card"
    assert (inbox_root / record.slug).is_dir()
    assert (inbox_root / record.slug).stat().st_mode & 0o077 == 0
    with database.transaction() as session:
        account = session.get(FinancialAccount, record.id)
        assert account is not None
        assert account.statement_adapter_key == "synthetic-card"
        assert account.statement_account_identifier == "synthetic-account-scope"


@pytest.mark.integration
def test_financial_account_bootstrap_rejects_unsafe_secret_and_existing_folder(
    database: Database,
    tmp_path: Path,
) -> None:
    inbox_root = tmp_path / "inbox"
    password_root = tmp_path / "passwords"
    password_root.mkdir(mode=0o700)
    secret = password_root / "synthetic-password"
    secret.write_text("synthetic-password", encoding="utf-8")
    secret.chmod(0o644)
    bootstrap = FinancialAccountBootstrap(
        database,
        inbox_root=inbox_root,
        password_root=password_root,
        adapters={"synthetic-card": "synthetic"},
    )
    command = FinancialAccountBootstrapCommand(
        slug="synthetic-primary-card",
        display_name="Synthetic Primary Card",
        institution="synthetic",
        kind=FinancialAccountKind.CREDIT_CARD,
        default_currency="SGD",
        statement_adapter_key="synthetic-card",
        statement_account_identifier="synthetic-account-scope",
        statement_password_secret="synthetic-password",  # pragma: allowlist secret
    )

    with pytest.raises(FinancialAccountSetupError, match="permissions"):
        bootstrap.bootstrap(command, dry_run=True)

    secret.chmod(0o600)
    inbox_root.mkdir(mode=0o700)
    (inbox_root / command.slug).mkdir(mode=0o700)
    with pytest.raises(FinancialAccountSetupError, match="folder already exists"):
        bootstrap.bootstrap(command, dry_run=True)
    with database.transaction() as session:
        assert session.scalar(select(FinancialAccount.id)) is None
