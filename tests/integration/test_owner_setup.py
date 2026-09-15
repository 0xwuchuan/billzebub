from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from billzebub.api import create_app
from billzebub.config import Settings
from billzebub.financial_account_aliases import FinancialAccountAliases
from billzebub.persistence.database import Database
from billzebub.persistence.models import FinancialAccountKind


@pytest.mark.integration
def test_owner_http_creates_accounts_aliases_categories_and_tokens(
    database: Database,
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            artifact_root=tmp_path / "artifacts",
            statement_inbox_root=tmp_path / "inbox",
            statement_password_root=tmp_path / "passwords",
            development_identity="owner@example.test",
        ),
        database,
    )
    csrf = {
        "Origin": "http://testserver",
        "X-Billzebub-CSRF": "bzb-spa",
    }

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        paylah = client.post(
            "/api/v1/financial-accounts",
            headers=csrf,
            json={
                "slug": "synthetic-paylah",
                "display_name": "Synthetic PayLah",
                "institution": "dbs",
                "kind": "paylah",
                "default_currency": "SGD",
            },
        )
        card = client.post(
            "/api/v1/financial-accounts",
            headers=csrf,
            json={
                "slug": "synthetic-card",
                "display_name": "Synthetic Card",
                "institution": "dbs",
                "kind": "credit_card",
                "default_currency": "SGD",
                "statement_adapter_key": "dbs-credit-card",
                "statement_account_identifier": "synthetic-account-scope",
            },
        )
        alias = client.post(
            f"/api/v1/financial-accounts/{card.json()['id']}/aliases",
            headers=csrf,
            json={
                "kind": "apple_wallet_card",
                "card_label": "Synthetic Wallet Card",
            },
        )
        category = client.post(
            "/api/v1/categories",
            headers=csrf,
            json={"name": "Synthetic Dining"},
        )
        token = client.post(
            "/api/v1/tokens",
            headers=csrf,
            json={
                "name": "Apple Shortcut",
                "kind": "integration",
                "scopes": ["shortcut:claims:create"],
            },
        )
        accounts = client.get("/api/v1/financial-accounts")
        tokens = client.get("/api/v1/tokens")
        whoami = client.get("/api/v1/whoami")

    assert paylah.status_code == 201
    assert paylah.json()["kind"] == FinancialAccountKind.PAYLAH.value
    assert paylah.json()["inbox_ready"] is False
    assert card.status_code == 201
    assert card.json()["kind"] == "credit_card"
    assert card.json()["inbox_ready"] is True
    assert "statement_account_identifier" not in card.json()
    assert alias.status_code == 201
    assert alias.json()["display_label"] == "Synthetic Wallet Card"
    assert "••••" not in alias.text
    assert "masked_value" not in alias.json()
    assert accounts.json()["items"][1]["aliases"][0]["display_label"] == "Synthetic Wallet Card"
    assert category.status_code == 201
    assert token.status_code == 201
    plaintext = token.json()["plaintext"]
    assert plaintext.startswith("bzb_v1_")
    assert "plaintext" not in tokens.json()["items"][0]
    assert whoami.json()["login"] == "owner@example.test"
    mapped = FinancialAccountAliases(database).resolve_apple_wallet_card("Synthetic Wallet Card")
    assert mapped is not None
    assert str(mapped.id) == card.json()["id"]
