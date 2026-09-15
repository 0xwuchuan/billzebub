from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from billzebub.api import create_app
from billzebub.config import Settings
from billzebub.financial_account_aliases import FinancialAccountAliasRecord
from billzebub.financial_accounts import (
    FinancialAccountBootstrapCommand,
    FinancialAccountBootstrapPlan,
    FinancialAccountRecord,
    FinancialAccountSetupError,
    StatementAdapterRecord,
)
from billzebub.persistence.models import AuditActorKind, FinancialAccountKind
from billzebub.tokens import IssuedToken, TokenRecord, TokenScope


class FakeDatabase:
    def ping(self) -> None:
        pass

    def close(self) -> None:
        pass


@dataclass
class FakeAccounts:
    records: list[FinancialAccountRecord] = field(default_factory=list)
    adapters: tuple[StatementAdapterRecord, ...] = (
        StatementAdapterRecord(
            key="dbs-credit-card",
            institution="dbs",
            kind=FinancialAccountKind.CREDIT_CARD,
        ),
    )
    commands: list[FinancialAccountBootstrapCommand] = field(default_factory=list)

    def accepted_adapters(self) -> tuple[StatementAdapterRecord, ...]:
        return self.adapters

    def list(self) -> tuple[FinancialAccountRecord, ...]:
        return tuple(self.records)

    def get(self, account_id: UUID) -> FinancialAccountRecord:
        for record in self.records:
            if record.id == account_id:
                return record
        raise FinancialAccountSetupError("Financial Account was not found")

    def bootstrap(
        self,
        command: FinancialAccountBootstrapCommand,
        *,
        dry_run: bool = False,
    ) -> FinancialAccountRecord | FinancialAccountBootstrapPlan:
        self.commands.append(command)
        if dry_run:
            return FinancialAccountBootstrapPlan(
                slug=command.slug,
                institution=command.institution,
                kind=command.kind,
                default_currency=command.default_currency,
                statement_adapter_key=command.statement_adapter_key,
                password_configured=command.statement_password_secret is not None,
            )
        record = FinancialAccountRecord(
            id=uuid4(),
            slug=command.slug,
            display_name=command.display_name,
            institution=command.institution,
            kind=command.kind,
            default_currency=command.default_currency,
            statement_adapter_key=command.statement_adapter_key,
            active=True,
            password_configured=command.statement_password_secret is not None,
            inbox_ready=command.kind is FinancialAccountKind.CREDIT_CARD,
        )
        self.records.append(record)
        return record


@dataclass
class FakeAliases:
    records: list[FinancialAccountAliasRecord] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    def list(self) -> tuple[FinancialAccountAliasRecord, ...]:
        return tuple(self.records)

    def add_apple_wallet_card_for_account(
        self,
        account_id: UUID,
        *,
        card_label: str,
    ) -> FinancialAccountAliasRecord:
        self.labels.append(card_label)
        record = FinancialAccountAliasRecord(
            id=uuid4(),
            financial_account_id=account_id,
            alias_kind="apple_wallet_card",
            display_label=card_label,
        )
        self.records.append(record)
        return record


@dataclass
class FakeOwnerTokens:
    records: list[TokenRecord] = field(default_factory=list)
    issued: list[IssuedToken] = field(default_factory=list)

    def list_active(self) -> tuple[TokenRecord, ...]:
        return tuple(self.records)

    def issue(
        self,
        *,
        name: str,
        actor_kind: AuditActorKind,
        scopes: frozenset[TokenScope],
    ) -> IssuedToken:
        assert actor_kind is AuditActorKind.INTEGRATION
        issued = IssuedToken(
            id=uuid4(),
            name=name,
            plaintext="bzb_v1_abcd1234efgh_synthetic-once",
            prefix="abcd1234efgh",
            scopes=scopes,
        )
        self.issued.append(issued)
        self.records.append(
            TokenRecord(
                id=issued.id,
                name=name,
                prefix=issued.prefix,
                scopes=tuple(scope.value for scope in scopes),
                created_at=datetime(2026, 1, 10, tzinfo=UTC),
                last_used_at=None,
            )
        )
        return issued

    def rotate(self, token_id: UUID) -> IssuedToken:
        raise AssertionError(f"unexpected rotate {token_id}")

    def revoke(self, token_id: UUID) -> bool:
        before = len(self.records)
        self.records = [record for record in self.records if record.id != token_id]
        return len(self.records) != before


def _client(tmp_path: Path, **services: object) -> TestClient:
    app = create_app(
        Settings(artifact_root=tmp_path, development_identity="developer@example.test"),
        FakeDatabase(),
        **services,  # type: ignore[arg-type]
    )
    return TestClient(app, client=("127.0.0.1", 50000))


def test_owner_can_create_paylah_and_credit_card_accounts(tmp_path: Path) -> None:
    accounts = FakeAccounts()
    aliases = FakeAliases()
    with _client(tmp_path, account_bootstrap=accounts, account_aliases=aliases) as client:
        listed = client.get("/api/v1/financial-accounts")
        blocked = client.post(
            "/api/v1/financial-accounts",
            json={
                "slug": "synthetic-paylah",
                "display_name": "Synthetic PayLah",
                "institution": "dbs",
                "kind": "paylah",
                "default_currency": "SGD",
            },
        )
        created = client.post(
            "/api/v1/financial-accounts",
            headers={"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"},
            json={
                "slug": "synthetic-paylah",
                "display_name": "Synthetic PayLah",
                "institution": "dbs",
                "kind": "paylah",
                "default_currency": "SGD",
            },
        )
        adapters = client.get("/api/v1/statement-adapters")

    assert listed.status_code == 200
    assert listed.json() == {"items": []}
    assert blocked.status_code == 403
    assert created.status_code == 201
    body = created.json()
    assert body["kind"] == "paylah"
    assert body["statement_adapter_key"] is None
    assert body["inbox_ready"] is False
    assert "statement_account_identifier" not in body
    assert accounts.commands[0].kind is FinancialAccountKind.PAYLAH
    assert adapters.json()["items"][0]["key"] == "dbs-credit-card"


def test_wallet_alias_returns_owner_display_label(tmp_path: Path) -> None:
    account_id = uuid4()
    accounts = FakeAccounts(
        records=[
            FinancialAccountRecord(
                id=account_id,
                slug="synthetic-card",
                display_name="Synthetic Card",
                institution="dbs",
                kind=FinancialAccountKind.CREDIT_CARD,
                default_currency="SGD",
                statement_adapter_key="dbs-credit-card",
                active=True,
                password_configured=False,
                inbox_ready=True,
            )
        ]
    )
    aliases = FakeAliases()
    with _client(tmp_path, account_bootstrap=accounts, account_aliases=aliases) as client:
        created = client.post(
            f"/api/v1/financial-accounts/{account_id}/aliases",
            headers={"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"},
            json={"kind": "apple_wallet_card", "card_label": "Synthetic Wallet Card"},
        )
        listed = client.get("/api/v1/financial-accounts")

    assert created.status_code == 201
    assert created.json()["display_label"] == "Synthetic Wallet Card"
    assert "••••" not in created.text
    assert "masked_value" not in created.json()
    assert listed.json()["items"][0]["aliases"][0]["display_label"] == "Synthetic Wallet Card"
    assert "statement_account_identifier" not in listed.json()["items"][0]
    assert aliases.labels == ["Synthetic Wallet Card"]


def test_shortcut_token_plaintext_is_returned_once(tmp_path: Path) -> None:
    tokens = FakeOwnerTokens()
    with _client(tmp_path, owner_tokens=tokens) as client:
        blocked = client.post(
            "/api/v1/tokens",
            json={
                "name": "Apple Shortcut",
                "kind": "integration",
                "scopes": ["shortcut:claims:create"],
            },
        )
        issued = client.post(
            "/api/v1/tokens",
            headers={"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"},
            json={
                "name": "Apple Shortcut",
                "kind": "integration",
                "scopes": ["shortcut:claims:create"],
            },
        )
        listed = client.get("/api/v1/tokens")
        revoked = client.post(
            f"/api/v1/tokens/{issued.json()['id']}/revoke",
            headers={"Origin": "http://testserver", "X-Billzebub-CSRF": "bzb-spa"},
            json={},
        )

    assert blocked.status_code == 403
    assert issued.status_code == 201
    assert issued.json()["plaintext"].startswith("bzb_v1_")
    assert listed.status_code == 200
    assert "plaintext" not in listed.json()["items"][0]
    assert listed.json()["items"][0]["prefix"] == "abcd1234efgh"
    assert revoked.status_code == 200
    assert revoked.json() == {"id": issued.json()["id"], "revoked": True}
